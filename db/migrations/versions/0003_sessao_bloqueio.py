"""Tabela sessao (pré-autenticação/sessão) e contador de bloqueios do usuário (RF-02).

Só o hash SHA-256 do token é guardado. Escopo 'mfa' vale apenas para a etapa de TOTP;
'completa' será usado na T05.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE app.usuario
            ADD COLUMN bloqueios smallint NOT NULL DEFAULT 0 CHECK (bloqueios >= 0)
        """
    )
    op.execute(
        """
        CREATE TABLE app.sessao (
            token_hash bytea PRIMARY KEY CHECK (octet_length(token_hash) = 32),
            cpf_hash   bytea NOT NULL REFERENCES app.usuario (cpf_hash),
            escopo     text NOT NULL CHECK (escopo IN ('mfa', 'completa')),
            expira_em  timestamptz NOT NULL,
            ip         inet,
            criado_em  timestamptz NOT NULL DEFAULT now(),
            CHECK (expira_em > criado_em)
        )
        """
    )
    op.execute("CREATE INDEX sessao_cpf_hash_idx ON app.sessao (cpf_hash)")
    op.execute("CREATE INDEX sessao_expira_em_idx ON app.sessao (expira_em)")
    op.execute("REVOKE ALL ON app.sessao FROM PUBLIC")
    op.execute("GRANT SELECT, INSERT, DELETE ON app.sessao TO app_user")


def downgrade() -> None:
    op.execute("DROP TABLE app.sessao")
    op.execute("ALTER TABLE app.usuario DROP COLUMN bloqueios")
