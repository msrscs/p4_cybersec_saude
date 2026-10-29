from sqlalchemy import select
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
