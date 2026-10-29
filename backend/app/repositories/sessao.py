from sqlalchemy.orm import Session

from app.models import Sessao


def inserir(db: Session, sessao: Sessao) -> None:
    db.add(sessao)
    db.flush()
