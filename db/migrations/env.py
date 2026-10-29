"""Ambiente do Alembic.

Conecta sempre com a role de migration (DDL), separada da role da aplicação.
A URL vem de MIGRATION_DATABASE_URL ou é montada a partir de MIGRATOR_DB_PASSWORD,
POSTGRES_DB, DB_HOST e DB_PORT.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import URL, engine_from_config, make_url, pool

from app.core.db_url import MIGRATOR_DB_ROLE, build_database_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None
VERSION_TABLE_SCHEMA = "app"


def _database_url() -> URL:
    if url := os.environ.get("MIGRATION_DATABASE_URL"):
        return make_url(url)
    password = os.environ.get("MIGRATOR_DB_PASSWORD")
    database = os.environ.get("POSTGRES_DB")
    if not password or not database:
        raise RuntimeError("Defina MIGRATOR_DB_PASSWORD e POSTGRES_DB no ambiente.")
    return build_database_url(
        user=MIGRATOR_DB_ROLE,
        password=password,
        database=database,
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "5433")),
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        version_table_schema=VERSION_TABLE_SCHEMA,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        {"sqlalchemy.url": _database_url()},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=VERSION_TABLE_SCHEMA,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
