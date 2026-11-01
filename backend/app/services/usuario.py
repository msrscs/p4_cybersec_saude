"""Cadastro de usuários: dados pessoais só cifrados, busca por HMAC (ADR-0004), senha bcrypt."""

import secrets
import string
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import senha as senha_mod
from app.core.config import Settings
from app.core.crypto import (
    DekCifrada,
    ErroCriptografia,
    FinalidadeHash,
    abrir_dek,
    cifrar_campo,
    decifrar_campo,
    gerar_dek,
    hash_busca,
)
from app.models import Usuario
from app.repositories import codigo_recuperacao as codigo_repo
from app.repositories import sessao as sessao_repo
from app.repositories import usuario as usuario_repo
from app.services import auditoria
from app.services import auth as auth_service
from app.services import sessao as sessao_svc
from app.services.auditoria import ContextoRequisicao, Evento
from app.services.sessao import SessaoAtual

# Senha gerada pelo sistema vale só até a primeira troca, e no máximo por este prazo (ADR-0028).
VALIDADE_SENHA_TEMPORARIA = timedelta(hours=72)


class ErroSenha(ValueError):
    """Senha atual incorreta ou nova senha recusada pela política (mensagem sem a senha)."""


class UsuarioNaoEncontrado(Exception):
    pass


class ErroCadastro(Exception):
    """Mensagem genérica: não revela se o CPF ou o e-mail já existem."""

    def __init__(self) -> None:
        super().__init__("Não foi possível cadastrar o usuário.")


@dataclass(frozen=True)
class NovoUsuario:
    cpf: str  # só dígitos, já validado
    nome: str
    email: str
    senha: str = field(repr=False)
    id_unidade: int | None = None
    troca_senha_obrigatoria: bool = False


def cadastrar(
    db: Session,
    settings: Settings,
    dados: NovoUsuario,
    ctx: ContextoRequisicao,
    *,
    autor: bytes | None = None,
) -> bytes:
    """Cria o usuário e devolve seu cpf_hash.

    Sem `autor` (script administrativo), o evento fica em nome do próprio usuário criado.
    """
    senha_mod.validar_politica(dados.senha, cpf=dados.cpf)
    cpf_hash = hash_busca(settings.chave_hmac, FinalidadeHash.CPF, dados.cpf)
    email_hash = hash_busca(settings.chave_hmac, FinalidadeHash.EMAIL, dados.email)
    if usuario_repo.existe(db, cpf_hash=cpf_hash, email_hash=email_hash):
        raise ErroCadastro

    dek, dek_cifrada = gerar_dek(settings.keyring)

    def cifrar(coluna: str, valor: str) -> bytes:
        return cifrar_campo(dek, valor, tabela="usuario", coluna=coluna, id_registro=cpf_hash)

    usuario = Usuario(
        cpf_hash=cpf_hash,
        email_hash=email_hash,
        cpf_cripto=cifrar("cpf_cripto", dados.cpf),
        nome_cripto=cifrar("nome_cripto", dados.nome),
        email_cripto=cifrar("email_cripto", dados.email.strip().lower()),
        dek_cripto=dek_cifrada.dek_cripto,
        kek_versao=dek_cifrada.kek_versao,
        senha_hash=senha_mod.gerar_hash(dados.senha, settings.bcrypt_rounds),
        id_unidade=dados.id_unidade,
        troca_senha_obrigatoria=dados.troca_senha_obrigatoria,
        senha_temporaria_expira_em=(
            datetime.now(UTC) + VALIDADE_SENHA_TEMPORARIA if dados.troca_senha_obrigatoria else None
        ),
    )
    try:
        with db.begin_nested():
            usuario_repo.inserir(db, usuario)
    except IntegrityError:
        raise ErroCadastro from None
    auditoria.registrar(
        db,
        Evento.USER_CREATED,
        ctx,
        cpf_usuario_hash=autor or cpf_hash,
        resumo=_alvo(cpf_hash) if autor else None,
    )
    return cpf_hash


def trocar_senha(
    db: Session,
    settings: Settings,
    atual: SessaoAtual,
    *,
    senha_atual: str,
    nova_senha: str,
    ctx: ContextoRequisicao,
    agora: datetime,
) -> None:
    """Troca a senha do usuário logado e encerra as demais sessões dele."""
    usuario = usuario_repo.buscar_para_login(db, atual.cpf_hash)
    if usuario is None:
        raise ErroSenha("Senha atual incorreta.")
    if auth_service.conta_bloqueada(usuario, agora):
        # Sem isto, uma sessão roubada testaria senhas sem parar, mesmo com a conta bloqueada.
        auditoria.registrar(
            db,
            Evento.LOGIN_FAILURE,
            ctx,
            cpf_usuario_hash=usuario.cpf_hash,
            resumo={"motivo": auth_service.MOTIVO_CONTA_BLOQUEADA},
        )
        raise ErroSenha("Senha atual incorreta.")
    if not senha_mod.verificar(senha_atual, usuario.senha_hash):
        auth_service.contar_falha(
            db, ctx, usuario, agora, motivo="senha_atual_invalida", evento=Evento.LOGIN_FAILURE
        )
        raise ErroSenha("Senha atual incorreta.")
    senha_mod.validar_politica(nova_senha, cpf=cpf_em_claro(settings, usuario))
    if senha_mod.verificar(nova_senha, usuario.senha_hash):
        raise ErroSenha("A nova senha deve ser diferente da atual.")

    usuario.senha_hash = senha_mod.gerar_hash(nova_senha, settings.bcrypt_rounds)
    usuario.troca_senha_obrigatoria = False
    usuario.senha_temporaria_expira_em = None
    encerradas = sessao_svc.encerrar_outras(db, atual)
    auditoria.registrar(
        db,
        Evento.PASSWORD_CHANGE,
        ctx,
        cpf_usuario_hash=usuario.cpf_hash,
        resumo={"sessoes_encerradas": encerradas},
    )


def gerar_senha_temporaria() -> str:
    especiais = "!@#$%&*+-=?"
    grupos = (string.ascii_uppercase, string.ascii_lowercase, string.digits, especiais)
    todos = "".join(grupos)
    while True:
        chars = [secrets.choice(g) for g in grupos] + [secrets.choice(todos) for _ in range(12)]
        secrets.SystemRandom().shuffle(chars)
        senha = "".join(chars)
        if not senha_mod.problemas_politica(senha):
            return senha


def resetar_acesso(
    db: Session,
    settings: Settings,
    cpf: str,
    ctx: ContextoRequisicao,
    agora: datetime,
    *,
    autor: bytes | None = None,
) -> str:
    """Reset administrativo: senha temporária, MFA zerado, sessões e códigos revogados.

    No próximo login o usuário recadastra o MFA e é obrigado a trocar a senha.
    """
    cpf_hash = hash_busca(settings.chave_hmac, FinalidadeHash.CPF, cpf)
    usuario = usuario_repo.buscar_para_login(db, cpf_hash)
    if usuario is None:
        raise UsuarioNaoEncontrado
    temporaria = gerar_senha_temporaria()
    usuario.senha_hash = senha_mod.gerar_hash(temporaria, settings.bcrypt_rounds)
    usuario.troca_senha_obrigatoria = True
    usuario.senha_temporaria_expira_em = agora + VALIDADE_SENHA_TEMPORARIA
    usuario.mfa_ativo = False
    usuario.totp_segredo_cripto = None
    usuario.totp_ultimo_passo = None
    usuario.falhas_login = 0
    usuario.bloqueios = 0
    usuario.bloqueado_ate = None
    codigo_repo.invalidar_todos(db, cpf_hash, agora)
    sessao_repo.remover_do_usuario(db, cpf_hash)
    auditoria.registrar(
        db,
        Evento.ACCESS_RESET,
        ctx,
        cpf_usuario_hash=autor or cpf_hash,
        resumo=_alvo(cpf_hash) if autor else None,
    )
    return temporaria


def _alvo(cpf_hash: bytes) -> dict[str, str]:
    return {"usuario_alvo": cpf_hash.hex()[:12]}


def cpf_em_claro(settings: Settings, usuario: Usuario) -> str:
    dek = abrir_dek(settings.keyring, DekCifrada(usuario.dek_cripto, usuario.kek_versao))
    return decifrar_campo(
        dek, usuario.cpf_cripto, tabela="usuario", coluna="cpf_cripto", id_registro=usuario.cpf_hash
    )


def nome_ou_nada(settings: Settings, usuario: Usuario) -> str | None:
    """Nome para o cabeçalho da tela: um cadastro adulterado não pode derrubar a sessão."""
    try:
        dek = abrir_dek(settings.keyring, DekCifrada(usuario.dek_cripto, usuario.kek_versao))
        return decifrar_campo(
            dek,
            usuario.nome_cripto,
            tabela="usuario",
            coluna="nome_cripto",
            id_registro=usuario.cpf_hash,
        )
    except ErroCriptografia:
        return None
