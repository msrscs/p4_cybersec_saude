"""Serviços oferecidos por cada unidade de saúde (RF-13, ADR-0023).

Tabela de relacionamento da SPEC. A app_user pode incluir e remover vínculos, como em
usuario_grupo: o histórico das mudanças fica no log, e as próprias unidades e serviços não são
apagados.

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.unidade_saude_servico_saude (
            fk_unidade_saude_id_unidade integer NOT NULL
                REFERENCES app.unidade_saude (id_unidade),
            fk_servico_saude_id_servico integer NOT NULL
                REFERENCES app.servico_saude (id_servico),
            PRIMARY KEY (fk_unidade_saude_id_unidade, fk_servico_saude_id_servico)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX unidade_servico_servico_idx
        ON app.unidade_saude_servico_saude (fk_servico_saude_id_servico)
        """
    )
    op.execute("REVOKE ALL ON app.unidade_saude_servico_saude FROM PUBLIC")
    op.execute("GRANT SELECT, INSERT, DELETE ON app.unidade_saude_servico_saude TO app_user")


def downgrade() -> None:
    op.execute("DROP TABLE app.unidade_saude_servico_saude")
