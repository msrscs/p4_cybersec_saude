"""Montagem de URLs do banco a partir de partes, sem concatenar credenciais à mão.

A conexão usa TLS (ADR-0013): o padrão é `verify-full` (certificado conferido contra a CA
interna e o nome do host). `DB_SSLMODE`/`DB_SSLROOTCERT` configuram; produção exige verify-full.
"""

import os
from collections.abc import Mapping

from sqlalchemy import URL

APP_DB_ROLE = "app_user"
MIGRATOR_DB_ROLE = "migrator"
MODOS_TLS = ("verify-full", "require", "disable")


def parametros_tls(modo: str, raiz: str | None) -> dict[str, str]:
    """Parâmetros libpq de TLS. Mensagens não incluem caminhos nem valores sensíveis."""
    if modo not in MODOS_TLS:
        raise ValueError(f"DB_SSLMODE deve ser um de: {', '.join(MODOS_TLS)}.")
    if modo == "verify-full" and not raiz:
        raise ValueError("DB_SSLROOTCERT (CA interna) é obrigatório com DB_SSLMODE=verify-full.")
    parametros = {"sslmode": modo}
    if raiz:
        parametros["sslrootcert"] = raiz
    return parametros


def tls_do_ambiente() -> dict[str, str]:
    """Para scripts e migrations, que não usam Settings."""
    return parametros_tls(
        os.environ.get("DB_SSLMODE", "verify-full"), os.environ.get("DB_SSLROOTCERT")
    )


def build_database_url(
    *, user: str, password: str, database: str, host: str, port: int, tls: Mapping[str, str]
) -> URL:
    return URL.create(
        "postgresql+psycopg",
        username=user,
        password=password,
        host=host,
        port=port,
        database=database,
        query=dict(tls),
    )
