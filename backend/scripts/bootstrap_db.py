"""Cria (ou atualiza) as roles e o schema do banco. Idempotente.

Executar uma vez, com o superusuário do Postgres, a partir de backend/:

    uv run --env-file ../.env python -m scripts.bootstrap_db

Roles criadas:
- migrator: dona do schema `app`; usada só pelo Alembic (DDL).
- app_user: usada pela API; sem DDL, privilégios concedidos tabela a tabela nas migrations.
"""

import os
import sys

import psycopg
from psycopg import sql

from app.core.db_url import APP_DB_ROLE, MIGRATOR_DB_ROLE

SCHEMA = "app"
_ROLE_ATTRS = "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"


def _upsert_role(cur: psycopg.Cursor[tuple[object, ...]], role: str, password: str) -> None:
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
    verb = "ALTER" if cur.fetchone() else "CREATE"
    # Utilitário DDL não aceita parâmetro: a senha entra como literal escapado pelo psycopg.
    cur.execute(
        sql.SQL("{verb} ROLE {role} " + _ROLE_ATTRS + " PASSWORD {pw}").format(
            verb=sql.SQL(verb), role=sql.Identifier(role), pw=sql.Literal(password)
        )
    )


def bootstrap(
    conn: psycopg.Connection[tuple[object, ...]],
    *,
    database: str,
    app_password: str,
    migrator_password: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT current_user")
        row = cur.fetchone()
    if row is None or row[0] in (APP_DB_ROLE, MIGRATOR_DB_ROLE):
        raise RuntimeError(
            "O superusuário não pode ter o mesmo nome de uma role da aplicação "
            f"({APP_DB_ROLE}/{MIGRATOR_DB_ROLE}). Use outro POSTGRES_USER."
        )
    db = sql.Identifier(database)
    app, mig, schema = (sql.Identifier(n) for n in (APP_DB_ROLE, MIGRATOR_DB_ROLE, SCHEMA))
    with conn.cursor() as cur:
        _upsert_role(cur, MIGRATOR_DB_ROLE, migrator_password)
        _upsert_role(cur, APP_DB_ROLE, app_password)
        statements: list[sql.Composed] = [
            sql.SQL("REVOKE ALL ON DATABASE {db} FROM PUBLIC").format(db=db),
            sql.SQL("GRANT CONNECT ON DATABASE {db} TO {mig}, {app}").format(
                db=db, mig=mig, app=app
            ),
            sql.SQL("REVOKE ALL ON SCHEMA public FROM PUBLIC").format(),
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {s} AUTHORIZATION {mig}").format(
                s=schema, mig=mig
            ),
            sql.SQL("REVOKE ALL ON SCHEMA {s} FROM PUBLIC").format(s=schema),
            sql.SQL("GRANT USAGE ON SCHEMA {s} TO {app}").format(s=schema, app=app),
            sql.SQL("ALTER ROLE {r} IN DATABASE {db} SET search_path = {s}").format(
                r=mig, db=db, s=schema
            ),
            sql.SQL("ALTER ROLE {r} IN DATABASE {db} SET search_path = {s}").format(
                r=app, db=db, s=schema
            ),
        ]
        for stmt in statements:
            cur.execute(stmt)


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"Variável {name} não definida.")
    return value


def main() -> None:
    database = _require("POSTGRES_DB")
    with psycopg.connect(
        user=_require("POSTGRES_USER"),
        password=_require("POSTGRES_PASSWORD"),
        dbname=database,
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "5433")),
        autocommit=True,
    ) as conn:
        bootstrap(
            conn,
            database=database,
            app_password=_require("APP_DB_PASSWORD"),
            migrator_password=_require("MIGRATOR_DB_PASSWORD"),
        )
    print("Roles e schema configurados.")


if __name__ == "__main__":
    main()
