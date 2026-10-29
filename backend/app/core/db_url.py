"""Montagem de URLs do banco a partir de partes, sem concatenar credenciais à mão."""

from sqlalchemy import URL

APP_DB_ROLE = "app_user"
MIGRATOR_DB_ROLE = "migrator"


def build_database_url(*, user: str, password: str, database: str, host: str, port: int) -> URL:
    return URL.create(
        "postgresql+psycopg",
        username=user,
        password=password,
        host=host,
        port=port,
        database=database,
    )
