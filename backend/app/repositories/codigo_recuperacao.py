from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import CodigoRecuperacao

_VALIDO = (CodigoRecuperacao.usado_em.is_(None), CodigoRecuperacao.invalidado_em.is_(None))


def inserir(db: Session, cpf_hash: bytes, hashes: list[bytes]) -> None:
    db.add_all(CodigoRecuperacao(cpf_hash=cpf_hash, codigo_hash=h) for h in hashes)
    db.flush()


def usar(db: Session, cpf_hash: bytes, codigo_hash: bytes, agora: datetime) -> bool:
    """Marca o código como usado de forma atômica: só um uso concorrente vence."""
    comando = (
        update(CodigoRecuperacao)
        .where(
            CodigoRecuperacao.cpf_hash == cpf_hash,
            CodigoRecuperacao.codigo_hash == codigo_hash,
            *_VALIDO,
        )
        .values(usado_em=agora)
        .returning(CodigoRecuperacao.id)
    )
    return db.execute(comando).first() is not None


def invalidar_todos(db: Session, cpf_hash: bytes, agora: datetime) -> None:
    db.execute(
        update(CodigoRecuperacao)
        .where(CodigoRecuperacao.cpf_hash == cpf_hash, *_VALIDO)
        .values(invalidado_em=agora)
    )


def restantes(db: Session, cpf_hash: bytes) -> int:
    consulta = select(func.count()).where(CodigoRecuperacao.cpf_hash == cpf_hash, *_VALIDO)
    return db.scalar(consulta) or 0
