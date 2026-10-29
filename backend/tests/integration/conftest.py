"""Fixtures de integração: cria um banco temporário, aplica bootstrap + migrations e o remove.

Requer POSTGRES_USER, POSTGRES_PASSWORD, APP_DB_PASSWORD e MIGRATOR_DB_PASSWORD no ambiente
(localmente: `uv run --env-file ../.env pytest`). Sem elas os testes são pulados, exceto se
REQUIRE_DB_TESTS=1 (CI), quando falham.
"""

import os
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql

from app.core.db_url import APP_DB_ROLE, MIGRATOR_DB_ROLE, build_database_url
from scripts.bootstrap_db import bootstrap

ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"
_REQUIRED = ("POSTGRES_USER", "POSTGRES_PASSWORD", "APP_DB_PASSWORD", "MIGRATOR_DB_PASSWORD")


@dataclass(frozen=True)
class BancoTeste:
    name: str
    host: str
    port: int

    def connect(self, role: str, password: str) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(
            user=role,
            password=password,
            dbname=self.name,
            host=self.host,
            port=self.port,
            autocommit=True,
        )


def superuser_connect(dbname: str, host: str, port: int) -> psycopg.Connection[tuple[object, ...]]:
    return psycopg.connect(
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        dbname=dbname,
        host=host,
        port=port,
        autocommit=True,
    )


@pytest.fixture(scope="session")
def test_db() -> Iterator[BancoTeste]:
    missing = [name for name in _REQUIRED if not os.environ.get(name)]
    if missing:
        if os.environ.get("REQUIRE_DB_TESTS") == "1":
            pytest.fail(f"Variáveis ausentes para testes de banco: {missing}")
        pytest.skip(f"Testes de banco pulados; faltam: {missing}")

    host = os.environ.get("DB_HOST", "localhost")
    port = int(os.environ.get("DB_PORT", "5433"))
    admin_db = os.environ.get("POSTGRES_DB", "postgres")
    db = BancoTeste(name=f"cs_test_{secrets.token_hex(4)}", host=host, port=port)

    with superuser_connect(admin_db, host, port) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db.name)))
    try:
        with superuser_connect(db.name, host, port) as conn:
            bootstrap(
                conn,
                database=db.name,
                app_password=os.environ["APP_DB_PASSWORD"],
                migrator_password=os.environ["MIGRATOR_DB_PASSWORD"],
            )
        url = build_database_url(
            user=MIGRATOR_DB_ROLE,
            password=os.environ["MIGRATOR_DB_PASSWORD"],
            database=db.name,
            host=host,
            port=port,
        )
        previous = os.environ.get("MIGRATION_DATABASE_URL")
        os.environ["MIGRATION_DATABASE_URL"] = url.render_as_string(hide_password=False)
        try:
            command.upgrade(Config(str(ALEMBIC_INI)), "head")
        finally:
            if previous is None:
                os.environ.pop("MIGRATION_DATABASE_URL", None)
            else:
                os.environ["MIGRATION_DATABASE_URL"] = previous
        yield db
    finally:
        with superuser_connect(admin_db, host, port) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(db.name))
            )


@pytest.fixture
def app_conn(test_db: BancoTeste) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    with test_db.connect(APP_DB_ROLE, os.environ["APP_DB_PASSWORD"]) as conn:
        yield conn


@pytest.fixture
def migrator_conn(test_db: BancoTeste) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    with test_db.connect(MIGRATOR_DB_ROLE, os.environ["MIGRATOR_DB_PASSWORD"]) as conn:
        yield conn
