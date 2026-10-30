"""Autorização RBAC (ADR-0011): usuário -> grupos -> papéis -> permissões.

Verificada no backend a cada requisição; nada é guardado em cache na sessão, então uma
mudança de grupo vale na próxima requisição.
"""

from enum import StrEnum

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.crypto import FinalidadeHash, hash_busca
from app.repositories import rbac as rbac_repo
from app.repositories import usuario as usuario_repo
from app.services import auditoria
from app.services.auditoria import ContextoRequisicao, Evento
from app.services.usuario import UsuarioNaoEncontrado


class Permissao(StrEnum):
    PACIENTE_LER = "paciente:ler"
    PACIENTE_LISTAR = "paciente:listar"
    PACIENTE_CRIAR = "paciente:criar"
    PACIENTE_EDITAR = "paciente:editar"
    PACIENTE_INATIVAR = "paciente:inativar"
    LOG_LER = "log:ler"


class GrupoNaoEncontrado(Exception):
    pass


def permissoes(db: Session, cpf_hash: bytes) -> frozenset[str]:
    return rbac_repo.permissoes(db, cpf_hash)


def tem_permissao(db: Session, cpf_hash: bytes, permissao: Permissao) -> bool:
    return permissao.value in rbac_repo.permissoes(db, cpf_hash)


def registrar_negado(
    db: Session, cpf_hash: bytes, permissao: Permissao, ctx: ContextoRequisicao
) -> None:
    auditoria.registrar(
        db,
        Evento.ACCESS_DENIED,
        ctx,
        cpf_usuario_hash=cpf_hash,
        resumo={"permissao": permissao.value},
    )


def alterar_grupo(
    db: Session,
    settings: Settings,
    *,
    cpf: str,
    grupo: str,
    remover: bool,
    ctx: ContextoRequisicao,
) -> bool:
    """Inclui (ou remove) o usuário no grupo. Devolve False se nada mudou."""
    cpf_hash = hash_busca(settings.chave_hmac, FinalidadeHash.CPF, cpf)
    if usuario_repo.buscar(db, cpf_hash) is None:
        raise UsuarioNaoEncontrado
    alvo = rbac_repo.buscar_grupo(db, grupo)
    if alvo is None:
        raise GrupoNaoEncontrado
    if remover:
        mudou = rbac_repo.remover_do_grupo(db, cpf_hash, alvo.id_grupo)
    else:
        mudou = rbac_repo.adicionar_ao_grupo(db, cpf_hash, alvo.id_grupo)
    if mudou:
        auditoria.registrar(
            db,
            Evento.ROLE_CHANGE,
            ctx,
            cpf_usuario_hash=cpf_hash,
            resumo={"grupo": alvo.grupo, "operacao": "remover" if remover else "adicionar"},
        )
    return mudou
