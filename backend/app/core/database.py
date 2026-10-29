"""Engine e sessões do banco (role app_user, menor privilégio)."""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings


def criar_engine(settings: Settings) -> Engine:
    return create_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)


def criar_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def get_db(request: Request) -> Iterator[Session]:
    """Uma transação por requisição: commit no sucesso, rollback em erro."""
    fabrica: sessionmaker[Session] = request.app.state.sessionmaker
    with fabrica() as db, db.begin():
        yield db
