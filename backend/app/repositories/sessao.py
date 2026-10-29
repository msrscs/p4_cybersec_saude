from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Sessao


def inserir(db: Session, sessao: Sessao) -> None:
    db.add(sessao)
    db.flush()


def buscar(db: Session, token_hash: bytes, escopo: str) -> Sessao | None:
    consulta = (
        select(Sessao)
        .where(Sessao.token_hash == token_hash, Sessao.escopo == escopo)
        .with_for_update()
    )
    return db.scalars(consulta).one_or_none()


def remover(db: Session, sessao: Sessao) -> None:
    db.delete(sessao)
    db.flush()


def remover_do_usuario(db: Session, cpf_hash: bytes, *, exceto: bytes | None = None) -> int:
    comando = delete(Sessao).where(Sessao.cpf_hash == cpf_hash)
    if exceto is not None:
        comando = comando.where(Sessao.token_hash != exceto)
    return db.execute(comando).rowcount  # type: ignore[attr-defined, no-any-return]
