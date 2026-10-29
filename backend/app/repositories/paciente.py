import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Paciente


def existe(db: Session, cpf_hash: bytes) -> bool:
    return (
        db.scalars(select(Paciente.cpf_hash).where(Paciente.cpf_hash == cpf_hash)).first()
        is not None
    )


def inserir(db: Session, paciente: Paciente) -> None:
    db.add(paciente)
    db.flush()


def buscar_por_cpf_hash(db: Session, cpf_hash: bytes) -> Paciente | None:
    return db.get(Paciente, cpf_hash)


def buscar_por_id(db: Session, id_publico: uuid.UUID, *, travar: bool = False) -> Paciente | None:
    consulta = select(Paciente).where(Paciente.id_publico == id_publico)
    if travar:
        consulta = consulta.with_for_update()
    return db.scalars(consulta).one_or_none()
