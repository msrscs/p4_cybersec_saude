import uuid
from collections.abc import Iterable

from sqlalchemy import literal, select, tuple_
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


def buscar_varios(db: Session, cpf_hashes: Iterable[bytes]) -> list[Paciente]:
    return list(db.scalars(select(Paciente).where(Paciente.cpf_hash.in_(list(cpf_hashes)))))


def listar(db: Session, *, limite: int, depois: Paciente | None = None) -> list[Paciente]:
    """Mais recentes primeiro, por cursor: o nome é cifrado e não pode ser ordenado no banco."""
    consulta = (
        select(Paciente)
        .order_by(Paciente.criado_em.desc(), Paciente.id_publico.desc())
        .limit(limite)
    )
    if depois is not None:
        consulta = consulta.where(
            tuple_(Paciente.criado_em, Paciente.id_publico)
            < tuple_(literal(depois.criado_em), literal(depois.id_publico))
        )
    return list(db.scalars(consulta))


def buscar_por_id(db: Session, id_publico: uuid.UUID, *, travar: bool = False) -> Paciente | None:
    consulta = select(Paciente).where(Paciente.id_publico == id_publico)
    if travar:
        consulta = consulta.with_for_update()
    return db.scalars(consulta).one_or_none()
