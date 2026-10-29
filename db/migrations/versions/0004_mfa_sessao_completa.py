"""MFA TOTP, códigos de recuperação e sessão completa (RF-02, T05).

- usuario.totp_ultimo_passo: último passo TOTP aceito (impede reuso de código).
- usuario.troca_senha_obrigatoria: definida pelo reset administrativo de acesso.
- sessao: tentativas na etapa MFA, último uso e expiração absoluta; a aplicação só pode
  atualizar essas colunas e expira_em.
- mfa_codigo_recuperacao: só o HMAC do código é guardado; uso e invalidação por UPDATE.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE app.usuario
            ADD COLUMN totp_ultimo_passo bigint CHECK (totp_ultimo_passo >= 0),
            ADD COLUMN troca_senha_obrigatoria boolean NOT NULL DEFAULT false
        """
    )
    op.execute(
        """
        ALTER TABLE app.sessao
            ADD COLUMN tentativas smallint NOT NULL DEFAULT 0 CHECK (tentativas >= 0),
            ADD COLUMN ultimo_uso timestamptz,
            ADD COLUMN expira_absoluta timestamptz,
            ADD CHECK (escopo <> 'completa' OR expira_absoluta IS NOT NULL),
            ADD CHECK (expira_absoluta IS NULL OR expira_em <= expira_absoluta)
        """
    )
    op.execute("GRANT UPDATE (tentativas, ultimo_uso, expira_em) ON app.sessao TO app_user")
    op.execute(
        """
        CREATE TABLE app.mfa_codigo_recuperacao (
            id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            cpf_hash      bytea NOT NULL REFERENCES app.usuario (cpf_hash),
            codigo_hash   bytea NOT NULL UNIQUE CHECK (octet_length(codigo_hash) = 32),
            criado_em     timestamptz NOT NULL DEFAULT now(),
            usado_em      timestamptz,
            invalidado_em timestamptz
        )
        """
    )
    op.execute(
        "CREATE INDEX mfa_codigo_recuperacao_cpf_hash_idx ON app.mfa_codigo_recuperacao (cpf_hash)"
    )
    op.execute("REVOKE ALL ON app.mfa_codigo_recuperacao FROM PUBLIC")
    op.execute("GRANT SELECT, INSERT ON app.mfa_codigo_recuperacao TO app_user")
    op.execute("GRANT UPDATE (usado_em, invalidado_em) ON app.mfa_codigo_recuperacao TO app_user")


def downgrade() -> None:
    op.execute("DROP TABLE app.mfa_codigo_recuperacao")
    op.execute("REVOKE UPDATE (tentativas, ultimo_uso, expira_em) ON app.sessao FROM app_user")
    op.execute(
        """
        ALTER TABLE app.sessao
            DROP COLUMN expira_absoluta, DROP COLUMN ultimo_uso, DROP COLUMN tentativas
        """
    )
    op.execute(
        "ALTER TABLE app.usuario DROP COLUMN troca_senha_obrigatoria, DROP COLUMN totp_ultimo_passo"
    )
