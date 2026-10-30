"""Contadores do limite de requisições por IP (RNF-07, T09, ADR-0013).

Janela fixa por (grupo de rotas, IP, início da janela); o incremento é um upsert atômico.
Linhas vencidas são apagadas pela rotina de limpeza (scripts.tarefas).

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.limite_requisicao (
            grupo   text NOT NULL CHECK (grupo ~ '^[a-z_]+:[0-9]+$'),
            ip      inet NOT NULL,
            janela  timestamptz NOT NULL,
            total   integer NOT NULL DEFAULT 1 CHECK (total > 0),
            PRIMARY KEY (grupo, ip, janela)
        )
        """
    )
    op.execute("CREATE INDEX limite_requisicao_janela_idx ON app.limite_requisicao (janela)")
    op.execute("REVOKE ALL ON app.limite_requisicao FROM PUBLIC")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON app.limite_requisicao TO app_user")


def downgrade() -> None:
    op.execute("DROP TABLE app.limite_requisicao")
