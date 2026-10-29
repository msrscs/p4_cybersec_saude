"""RNF-04 / THREAT_MODEL T1, R2, R3, E3: log de auditoria append-only."""

import os

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import errors

from app.core.db_url import MIGRATOR_DB_ROLE, build_database_url

from .conftest import ALEMBIC_INI, BancoTeste

Conn = psycopg.Connection[tuple[object, ...]]


def _insere_log(conn: Conn, acao: str = "login_success") -> int:
    row = conn.execute(
        "INSERT INTO app.log (acao, cpf_usuario_hash, ip_origem) VALUES (%s, %s, %s)"
        " RETURNING id_log",
        (acao, os.urandom(32), "203.0.113.7"),
    ).fetchone()
    assert row is not None
    id_log = row[0]
    assert isinstance(id_log, int)
    return id_log


def test_app_user_insere_e_le_log(app_conn: Conn) -> None:
    id_log = _insere_log(app_conn)
    row = app_conn.execute("SELECT acao FROM app.log WHERE id_log = %s", (id_log,)).fetchone()
    assert row == ("login_success",)


@pytest.mark.parametrize(
    "comando",
    [
        "UPDATE app.log SET acao = 'adulterado' WHERE id_log = %s",
        "DELETE FROM app.log WHERE id_log = %s",
    ],
)
def test_app_user_nao_altera_nem_apaga_log(app_conn: Conn, comando: str) -> None:
    id_log = _insere_log(app_conn)
    with pytest.raises(errors.InsufficientPrivilege):
        app_conn.execute(comando, (id_log,))


def test_app_user_nao_trunca_log(app_conn: Conn) -> None:
    with pytest.raises(errors.InsufficientPrivilege):
        app_conn.execute("TRUNCATE app.log")


@pytest.mark.parametrize(
    "comando",
    [
        "UPDATE app.log SET acao = 'adulterado' WHERE id_log = %s",
        "DELETE FROM app.log WHERE id_log = %s",
    ],
)
def test_trigger_bloqueia_alteracao_ate_para_dono_da_tabela(
    app_conn: Conn, migrator_conn: Conn, comando: str
) -> None:
    id_log = _insere_log(app_conn)
    with pytest.raises(errors.InsufficientPrivilege, match="append-only"):
        migrator_conn.execute(comando, (id_log,))


def test_trigger_bloqueia_truncate_ate_para_dono_da_tabela(migrator_conn: Conn) -> None:
    with pytest.raises(errors.InsufficientPrivilege, match="append-only"):
        migrator_conn.execute("TRUNCATE app.log")


def test_data_hora_sempre_definida_pelo_servidor(app_conn: Conn) -> None:
    row = app_conn.execute(
        "INSERT INTO app.log (acao, data_hora) VALUES ('teste', '2000-01-01T00:00:00Z')"
        " RETURNING data_hora > now() - interval '1 minute'"
    ).fetchone()
    assert row == (True,)


def test_hashes_exigem_32_bytes(app_conn: Conn) -> None:
    with pytest.raises(errors.CheckViolation):
        app_conn.execute(
            "INSERT INTO app.log (acao, cpf_usuario_hash) VALUES ('teste', %s)", (b"curto",)
        )


def test_downgrade_do_log_e_recusado(test_db: BancoTeste, monkeypatch: pytest.MonkeyPatch) -> None:
    url = build_database_url(
        user=MIGRATOR_DB_ROLE,
        password=os.environ["MIGRATOR_DB_PASSWORD"],
        database=test_db.name,
        host=test_db.host,
        port=test_db.port,
    )
    monkeypatch.setenv("MIGRATION_DATABASE_URL", url.render_as_string(hide_password=False))
    with pytest.raises(RuntimeError, match="WORM"):
        command.downgrade(Config(str(ALEMBIC_INI)), "0001")
