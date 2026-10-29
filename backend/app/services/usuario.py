"""Cadastro de usuários: dados pessoais só cifrados, busca por HMAC (ADR-0004), senha bcrypt."""

from dataclasses import dataclass, field

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import senha as senha_mod
from app.core.config import Settings
from app.core.crypto import FinalidadeHash, cifrar_campo, gerar_dek, hash_busca
from app.models import Usuario
from app.repositories import usuario as usuario_repo
from app.services import auditoria
from app.services.auditoria import ContextoRequisicao, Evento


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


def cadastrar(
    db: Session, settings: Settings, dados: NovoUsuario, ctx: ContextoRequisicao
) -> bytes:
    """Cria o usuário e devolve seu cpf_hash."""
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
    )
    try:
        with db.begin_nested():
            usuario_repo.inserir(db, usuario)
    except IntegrityError:
        raise ErroCadastro from None
    auditoria.registrar(db, Evento.USER_CREATED, ctx, cpf_usuario_hash=cpf_hash)
    return cpf_hash
