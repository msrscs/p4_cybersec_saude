"""Gestão de usuários pelo Administrador (RF-01, ADR-0017).

O administrador nunca define a senha de outra pessoa: o sistema gera uma temporária, exibida uma
vez, com troca obrigatória. Toda ação registra quem fez (cpf_usuario_hash) e sobre quem
(usuario_alvo, hash truncado), sem dado pessoal em claro. Para ninguém ficar sem acesso, a própria
conta não pode ser inativada nem resetada, e sempre resta um administrador ativo.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.crypto import (
    DekCifrada,
    ErroCriptografia,
    FinalidadeHash,
    abrir_dek,
    cifrar_campo,
    decifrar_campo,
    hash_busca,
)
from app.models import Grupo, Usuario
from app.repositories import rbac as rbac_repo
from app.repositories import sessao as sessao_repo
from app.repositories import usuario as usuario_repo
from app.services import auditoria, autorizacao, cadastro
from app.services import usuario as usuario_service
from app.services.auditoria import ContextoRequisicao, Evento
from app.services.autorizacao import GrupoNaoEncontrado
from app.services.usuario import ErroCadastro, NovoUsuario, gerar_senha_temporaria

GRUPO_ADMINISTRADOR = "Administrador"
TAMANHO_PAGINA = 20
_TABELA = "usuario"


class OperacaoProibida(Exception):
    """Ação recusada para ninguém perder o acesso; a mensagem é exibida ao administrador."""


class ErroAlteracao(Exception):
    """Mensagem genérica: não revela se o e-mail já pertence a outra pessoa."""

    def __init__(self) -> None:
        super().__init__("Não foi possível salvar os dados.")


@dataclass(frozen=True)
class ResumoUsuario:
    id_publico: uuid.UUID
    cpf: str | None = field(repr=False)  # None: cadastro ilegível (AES-GCM recusou)
    nome: str | None = field(repr=False)
    status: str
    grupos: list[str]


@dataclass(frozen=True)
class PaginaUsuarios:
    itens: list[ResumoUsuario]
    proximo: uuid.UUID | None


@dataclass(frozen=True)
class DadosUsuario:
    id_publico: uuid.UUID
    cpf: str = field(repr=False)
    nome: str = field(repr=False)
    email: str = field(repr=False)
    id_unidade: int | None
    unidade_nome: str | None
    status: str
    mfa_ativo: bool
    troca_senha_obrigatoria: bool
    bloqueado: bool
    grupos: list[str]
    proprio: bool
    criado_em: datetime
    atualizado_em: datetime


@dataclass(frozen=True)
class NovoCadastro:
    cpf: str  # só dígitos, já validado
    nome: str = field(repr=False)
    email: str = field(repr=False)
    id_unidade: int | None = None
    grupos: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Alteracoes:
    """Só os campos enviados; id_unidade=None em `campos` significa remover a unidade."""

    campos: frozenset[str]
    nome: str | None = field(default=None, repr=False)
    email: str | None = field(default=None, repr=False)
    id_unidade: int | None = None


def nomes_dos_grupos(db: Session) -> list[str]:
    return rbac_repo.nomes_dos_grupos(db)


def listar(
    db: Session, settings: Settings, depois: uuid.UUID | None, autor: bytes, ctx: ContextoRequisicao
) -> PaginaUsuarios:
    referencia = None
    if depois is not None:
        referencia = usuario_repo.buscar_por_id(db, depois)
        if referencia is None:  # cursor que não veio desta API
            return PaginaUsuarios(itens=[], proximo=None)
    linhas = usuario_repo.listar(db, limite=TAMANHO_PAGINA + 1, depois=referencia)
    pagina = linhas[:TAMANHO_PAGINA]
    grupos = rbac_repo.grupos_dos_usuarios(db, [u.cpf_hash for u in pagina])
    itens = [_resumo(settings, u, grupos.get(u.cpf_hash, [])) for u in pagina]
    resumo: dict[str, Any] = {
        "recurso": _TABELA,
        "origem": "lista",
        "usuarios": [str(u.id_publico) for u in pagina],
    }
    # Falha do AES-GCM é sinal de adulteração: fica no log, e a lista segue utilizável.
    ilegiveis = [str(i.id_publico) for i in itens if i.nome is None]
    if ilegiveis:
        resumo["ilegiveis"] = ilegiveis
    auditoria.registrar(
        db, Evento.SENSITIVE_DATA_ACCESS, ctx, cpf_usuario_hash=autor, resumo=resumo
    )
    return PaginaUsuarios(
        itens=itens,
        proximo=pagina[-1].id_publico if len(linhas) > TAMANHO_PAGINA else None,
    )


def obter(
    db: Session,
    settings: Settings,
    id_publico: uuid.UUID,
    autor: bytes,
    ctx: ContextoRequisicao,
    agora: datetime,
) -> DadosUsuario | None:
    usuario = usuario_repo.buscar_por_id(db, id_publico)
    if usuario is None:
        return None
    auditoria.registrar(
        db,
        Evento.SENSITIVE_DATA_ACCESS,
        ctx,
        cpf_usuario_hash=autor,
        resumo={"recurso": _TABELA, "origem": "consulta", "usuario_alvo": _curto(usuario)},
    )
    return _dados(db, settings, usuario, autor, agora)


def cadastrar(
    db: Session,
    settings: Settings,
    dados: NovoCadastro,
    autor: bytes,
    ctx: ContextoRequisicao,
    agora: datetime,
) -> tuple[DadosUsuario, str]:
    """Cria o usuário com senha temporária, exibida uma vez. Devolve os dados e a senha."""
    grupos = _grupos_validos(db, dados.grupos)
    if dados.id_unidade is not None:
        cadastro.validar_unidade_ativa(db, dados.id_unidade)
    temporaria = gerar_senha_temporaria()
    novo = NovoUsuario(
        cpf=dados.cpf,
        nome=dados.nome,
        email=dados.email,
        senha=temporaria,
        id_unidade=dados.id_unidade,
        troca_senha_obrigatoria=True,
    )
    cpf_hash = usuario_service.cadastrar(db, settings, novo, ctx, autor=autor)
    for grupo in grupos:
        autorizacao.aplicar_mudanca_de_grupo(
            db, cpf_hash, grupo, remover=False, ctx=ctx, autor=autor
        )
    usuario = usuario_repo.buscar(db, cpf_hash)
    if usuario is None:  # pragma: no cover - acabou de ser inserido nesta transação
        raise ErroCadastro
    db.refresh(usuario)
    return _dados(db, settings, usuario, autor, agora), temporaria


def atualizar(
    db: Session,
    settings: Settings,
    id_publico: uuid.UUID,
    alteracoes: Alteracoes,
    autor: bytes,
    ctx: ContextoRequisicao,
    agora: datetime,
) -> DadosUsuario | None:
    usuario = usuario_repo.buscar_por_id(db, id_publico, travar=True)
    if usuario is None:
        return None
    dek = _dek(settings, usuario)
    chave = usuario.cpf_hash

    def cifrar(coluna: str, valor: str) -> bytes:
        return cifrar_campo(dek, valor, tabela=_TABELA, coluna=coluna, id_registro=chave)

    if "nome" in alteracoes.campos and alteracoes.nome is not None:
        usuario.nome_cripto = cifrar("nome_cripto", alteracoes.nome)
    if "email" in alteracoes.campos and alteracoes.email is not None:
        email_hash = hash_busca(settings.chave_hmac, FinalidadeHash.EMAIL, alteracoes.email)
        if usuario_repo.email_em_uso(db, email_hash, exceto=chave):
            raise ErroAlteracao
        usuario.email_hash = email_hash
        usuario.email_cripto = cifrar("email_cripto", alteracoes.email)
    if "id_unidade" in alteracoes.campos and alteracoes.id_unidade != usuario.id_unidade:
        # Só valida se mudou: quem já está numa unidade inativa pode ter o resto editado.
        if alteracoes.id_unidade is not None:
            cadastro.validar_unidade_ativa(db, alteracoes.id_unidade)
        usuario.id_unidade = alteracoes.id_unidade
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:  # corrida: o mesmo e-mail salvo em outra requisição
        raise ErroAlteracao from None
    db.refresh(usuario)
    auditoria.registrar(
        db,
        Evento.USER_UPDATED,
        ctx,
        cpf_usuario_hash=autor,
        resumo={"campos": sorted(alteracoes.campos), "usuario_alvo": _curto(usuario)},
    )
    return _dados(db, settings, usuario, autor, agora)


def alterar_status(
    db: Session, id_publico: uuid.UUID, *, ativo: bool, autor: bytes, ctx: ContextoRequisicao
) -> bool:
    """Inativar encerra as sessões na hora. Devolve False se o usuário não existe."""
    usuario = usuario_repo.buscar_por_id(db, id_publico, travar=True)
    if usuario is None:
        return False
    if usuario.cpf_hash == autor:
        raise OperacaoProibida("Não é possível alterar a situação da própria conta.")
    novo = "ativo" if ativo else "inativo"
    if usuario.status == novo:
        return True
    if not ativo:
        _garantir_outro_administrador(db, usuario.cpf_hash)
    usuario.status = novo
    resumo: dict[str, Any] = {"usuario_alvo": _curto(usuario)}
    if not ativo:
        resumo["sessoes_encerradas"] = sessao_repo.remover_do_usuario(db, usuario.cpf_hash)
    db.flush()
    evento = Evento.USER_REACTIVATED if ativo else Evento.USER_DEACTIVATED
    auditoria.registrar(db, evento, ctx, cpf_usuario_hash=autor, resumo=resumo)
    return True


def resetar(
    db: Session,
    settings: Settings,
    id_publico: uuid.UUID,
    autor: bytes,
    ctx: ContextoRequisicao,
    agora: datetime,
) -> str | None:
    """Senha temporária e MFA zerado. Devolve a senha (uma vez) ou None se não existe."""
    usuario = usuario_repo.buscar_por_id(db, id_publico)
    if usuario is None:
        return None
    if usuario.cpf_hash == autor:
        raise OperacaoProibida("Para a própria conta, use a troca de senha em Minha conta.")
    cpf = usuario_service.cpf_em_claro(settings, usuario)
    return usuario_service.resetar_acesso(db, settings, cpf, ctx, agora, autor=autor)


def definir_grupos(
    db: Session,
    settings: Settings,
    id_publico: uuid.UUID,
    grupos: list[str],
    autor: bytes,
    ctx: ContextoRequisicao,
    agora: datetime,
) -> DadosUsuario | None:
    """Deixa o usuário exatamente nos grupos informados; cada mudança gera um role_change."""
    usuario = usuario_repo.buscar_por_id(db, id_publico, travar=True)
    if usuario is None:
        return None
    desejados = {g.grupo: g for g in _grupos_validos(db, grupos)}
    atuais = set(rbac_repo.grupos_dos_usuarios(db, [usuario.cpf_hash]).get(usuario.cpf_hash, []))
    if GRUPO_ADMINISTRADOR in atuais - desejados.keys():
        if usuario.cpf_hash == autor:
            raise OperacaoProibida("Não é possível sair do grupo Administrador.")
        _garantir_outro_administrador(db, usuario.cpf_hash)
    for nome in sorted(desejados.keys() - atuais):
        autorizacao.aplicar_mudanca_de_grupo(
            db, usuario.cpf_hash, desejados[nome], remover=False, ctx=ctx, autor=autor
        )
    for nome in sorted(atuais - desejados.keys()):
        grupo = rbac_repo.buscar_grupo(db, nome)
        if grupo is not None:
            autorizacao.aplicar_mudanca_de_grupo(
                db, usuario.cpf_hash, grupo, remover=True, ctx=ctx, autor=autor
            )
    return _dados(db, settings, usuario, autor, agora)


# --- Apoio -------------------------------------------------------------------------------


def _grupos_validos(db: Session, nomes: list[str]) -> list[Grupo]:
    grupos = []
    for nome in dict.fromkeys(nomes):
        grupo = rbac_repo.buscar_grupo(db, nome)
        if grupo is None:
            raise GrupoNaoEncontrado
        grupos.append(grupo)
    return grupos


def _garantir_outro_administrador(db: Session, cpf_hash: bytes) -> None:
    # A trava serializa quem mexe em administradores: dois podem tentar se excluir ao mesmo tempo.
    rbac_repo.travar_administradores(db)
    if not rbac_repo.esta_no_grupo(db, cpf_hash, GRUPO_ADMINISTRADOR):
        return
    if rbac_repo.outros_ativos_no_grupo(db, cpf_hash, GRUPO_ADMINISTRADOR) == 0:
        raise OperacaoProibida("Deve restar ao menos um administrador ativo.")


def _dados(
    db: Session, settings: Settings, usuario: Usuario, autor: bytes, agora: datetime
) -> DadosUsuario:
    grupos = rbac_repo.grupos_dos_usuarios(db, [usuario.cpf_hash]).get(usuario.cpf_hash, [])
    return DadosUsuario(
        id_publico=usuario.id_publico,
        cpf=_campo(settings, usuario, "cpf_cripto"),
        nome=_campo(settings, usuario, "nome_cripto"),
        email=_campo(settings, usuario, "email_cripto"),
        id_unidade=usuario.id_unidade,
        unidade_nome=cadastro.nome_da_unidade(db, usuario.id_unidade),
        status=usuario.status,
        mfa_ativo=usuario.mfa_ativo,
        troca_senha_obrigatoria=usuario.troca_senha_obrigatoria,
        bloqueado=usuario.bloqueado_ate is not None and usuario.bloqueado_ate > agora,
        grupos=grupos,
        proprio=usuario.cpf_hash == autor,
        criado_em=usuario.criado_em,
        atualizado_em=usuario.atualizado_em,
    )


def _resumo(settings: Settings, usuario: Usuario, grupos: list[str]) -> ResumoUsuario:
    try:
        cpf: str | None = _campo(settings, usuario, "cpf_cripto")
        nome: str | None = _campo(settings, usuario, "nome_cripto")
    except ErroCriptografia:
        cpf = nome = None
    return ResumoUsuario(
        id_publico=usuario.id_publico, cpf=cpf, nome=nome, status=usuario.status, grupos=grupos
    )


def _dek(settings: Settings, usuario: Usuario) -> bytes:
    return abrir_dek(settings.keyring, DekCifrada(usuario.dek_cripto, usuario.kek_versao))


def _campo(settings: Settings, usuario: Usuario, coluna: str) -> str:
    return decifrar_campo(
        _dek(settings, usuario),
        getattr(usuario, coluna),
        tabela=_TABELA,
        coluna=coluna,
        id_registro=usuario.cpf_hash,
    )


def _curto(usuario: Usuario) -> str:
    return usuario.cpf_hash.hex()[:12]
