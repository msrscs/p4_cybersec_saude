"""THREAT_MODEL E3 (menor privilégio) e estrutura da tabela usuario (RF-01)."""

import os

import psycopg
import pytest
from psycopg import errors

from scripts.bootstrap_db import bootstrap

from .conftest import BancoTeste, superuser_connect

Conn = psycopg.Connection[tuple[object, ...]]


def _insere_usuario(conn: Conn) -> bytes:
    cpf_hash = os.urandom(32)
    conn.execute(
        "INSERT INTO app.usuario (cpf_hash, email_hash, cpf_cripto, nome_cripto, email_cripto,"
        " dek_cripto, kek_versao, senha_hash) VALUES (%s, %s, %s, %s, %s, %s, 1, %s)",
        (cpf_hash, os.urandom(32), b"c", b"n", b"e", b"d", "$2b$12$hash-ficticio"),
    )
    return cpf_hash


def test_app_user_nao_cria_tabela(app_conn: Conn) -> None:
    with pytest.raises(errors.InsufficientPrivilege):
        app_conn.execute("CREATE TABLE app.invasora (id int)")


def test_app_user_nao_usa_schema_public(app_conn: Conn) -> None:
    with pytest.raises(errors.InsufficientPrivilege):
        app_conn.execute("CREATE TABLE public.invasora (id int)")


def test_app_user_nao_tem_privilegios_de_role(app_conn: Conn) -> None:
    row = app_conn.execute(
        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls FROM pg_roles"
        " WHERE rolname = current_user"
    ).fetchone()
    assert row == (False, False, False, False)


def test_app_user_crud_sem_delete_em_usuario(app_conn: Conn) -> None:
    cpf_hash = _insere_usuario(app_conn)
    app_conn.execute("UPDATE app.usuario SET status = 'inativo' WHERE cpf_hash = %s", (cpf_hash,))
    with pytest.raises(errors.InsufficientPrivilege):
        app_conn.execute("DELETE FROM app.usuario WHERE cpf_hash = %s", (cpf_hash,))


def test_usuario_rejeita_status_invalido(app_conn: Conn) -> None:
    cpf_hash = _insere_usuario(app_conn)
    with pytest.raises(errors.CheckViolation):
        app_conn.execute("UPDATE app.usuario SET status = 'root' WHERE cpf_hash = %s", (cpf_hash,))


def test_atualizado_em_e_criado_em_controlados_pelo_banco(app_conn: Conn) -> None:
    cpf_hash = _insere_usuario(app_conn)
    row = app_conn.execute(
        "UPDATE app.usuario SET criado_em = '2000-01-01', falhas_login = 1"
        " WHERE cpf_hash = %s RETURNING criado_em > '2000-01-02', atualizado_em >= criado_em",
        (cpf_hash,),
    ).fetchone()
    assert row == (True, True)


def test_bootstrap_e_idempotente(test_db: BancoTeste) -> None:
    with superuser_connect(test_db.name, test_db.host, test_db.port) as conn:
        bootstrap(
            conn,
            database=test_db.name,
            app_password=os.environ["APP_DB_PASSWORD"],
            migrator_password=os.environ["MIGRATOR_DB_PASSWORD"],
        )


def test_bootstrap_recusa_superusuario_com_nome_de_role_da_aplicacao(migrator_conn: Conn) -> None:
    with pytest.raises(RuntimeError, match="mesmo nome"):
        bootstrap(migrator_conn, database="qualquer", app_password="x", migrator_password="y")
