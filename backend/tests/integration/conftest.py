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
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.crypto import gerar_chave_b64
from app.core.database import criar_engine, criar_sessionmaker
from app.core.db_url import APP_DB_ROLE, MIGRATOR_DB_ROLE, build_database_url
from app.main import create_app
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


def gerar_cpf() -> str:
    """CPF aleatório com dígitos verificadores válidos (só para testes)."""
    while True:
        base = "".join(str(secrets.randbelow(10)) for _ in range(9))
        if len(set(base)) > 1:
            break
    for _ in range(2):
        peso = len(base) + 1
        soma = sum(int(d) * p for d, p in zip(base, range(peso, 1, -1), strict=True))
        base += str(0 if soma % 11 < 2 else 11 - soma % 11)
    return base


@pytest.fixture(scope="session")
def settings_integracao(test_db: BancoTeste) -> Settings:
    return Settings(
        environment="test",
        postgres_db=test_db.name,
        app_db_password=os.environ["APP_DB_PASSWORD"],
        db_host=test_db.host,
        db_port=test_db.port,
        kek_keyring=f"1:{gerar_chave_b64()}",
        kek_ativa=1,
        hmac_key=gerar_chave_b64(),
        bcrypt_rounds=4,
    )


@pytest.fixture(scope="session")
def fabrica_sessao(settings_integracao: Settings) -> Iterator[sessionmaker[Session]]:
    engine = criar_engine(settings_integracao)
    yield criar_sessionmaker(engine)
    engine.dispose()


@pytest.fixture(scope="session")
def app_teste(settings_integracao: Settings) -> Iterator[FastAPI]:
    app = create_app(settings_integracao)
    yield app
    app.state.engine.dispose()


@pytest.fixture
def api(app_teste: FastAPI) -> Iterator[TestClient]:
    """Cliente novo por teste: cookies de um teste não vazam para outro."""
    with TestClient(app_teste, base_url="https://testserver") as client:
        yield client
