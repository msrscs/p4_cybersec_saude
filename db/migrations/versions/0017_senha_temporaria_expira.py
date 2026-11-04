"""Validade da senha temporária (T10, ADR-0028).

A senha gerada pelo sistema, no cadastro ou no reset, deixa de valer depois do prazo. Quem já está
com uma pendente ganha o prazo a partir de agora: não há como saber quando ela foi gerada.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE app.usuario ADD COLUMN senha_temporaria_expira_em timestamptz")
    op.execute(
        """
        UPDATE app.usuario
           SET senha_temporaria_expira_em = now() + interval '72 hours'
         WHERE troca_senha_obrigatoria
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE app.usuario DROP COLUMN senha_temporaria_expira_em")
