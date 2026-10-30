import uuid
from collections.abc import Iterable

from sqlalchemy import literal, select, tuple_
from sqlalchemy.orm import Session

from app.models import Usuario


def buscar_para_login(db: Session, cpf_hash: bytes) -> Usuario | None:
    """Trava a linha: falhas concorrentes não podem perder incrementos do contador."""
    return db.scalars(
        select(Usuario).where(Usuario.cpf_hash == cpf_hash).with_for_update()
    ).one_or_none()


def existe(db: Session, *, cpf_hash: bytes, email_hash: bytes) -> bool:
    consulta = select(Usuario.cpf_hash).where(
        (Usuario.cpf_hash == cpf_hash) | (Usuario.email_hash == email_hash)
    )
    return db.scalars(consulta.limit(1)).first() is not None


def inserir(db: Session, usuario: Usuario) -> None:
    db.add(usuario)
    db.flush()


def buscar(db: Session, cpf_hash: bytes) -> Usuario | None:
    return db.get(Usuario, cpf_hash)


def buscar_varios(db: Session, cpf_hashes: Iterable[bytes]) -> list[Usuario]:
    return list(db.scalars(select(Usuario).where(Usuario.cpf_hash.in_(list(cpf_hashes)))))


def buscar_por_id(db: Session, id_publico: uuid.UUID, *, travar: bool = False) -> Usuario | None:
    consulta = select(Usuario).where(Usuario.id_publico == id_publico)
    if travar:
        consulta = consulta.with_for_update()
    return db.scalars(consulta).one_or_none()


def email_em_uso(db: Session, email_hash: bytes, *, exceto: bytes) -> bool:
    consulta = select(Usuario.cpf_hash).where(
        Usuario.email_hash == email_hash, Usuario.cpf_hash != exceto
    )
    return db.scalars(consulta.limit(1)).first() is not None


def listar(db: Session, *, limite: int, depois: Usuario | None = None) -> list[Usuario]:
    """Mais recentes primeiro, por cursor: o nome é cifrado e não pode ser ordenado no banco."""
    consulta = (
        select(Usuario).order_by(Usuario.criado_em.desc(), Usuario.id_publico.desc()).limit(limite)
    )
    if depois is not None:
        consulta = consulta.where(
            tuple_(Usuario.criado_em, Usuario.id_publico)
            < tuple_(literal(depois.criado_em), literal(depois.id_publico))
        )
    return list(db.scalars(consulta))
