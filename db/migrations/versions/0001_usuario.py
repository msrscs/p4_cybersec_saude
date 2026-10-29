"""Tabela usuario (RF-01).

Dados pessoais ficam só cifrados (AES-256-GCM, envelope encryption: T03);
busca por CPF/e-mail via HMAC-SHA256 (cpf_hash/email_hash). Sem DELETE para a
aplicação: desativação é feita pelo status.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.usuario (
            cpf_hash            bytea PRIMARY KEY CHECK (octet_length(cpf_hash) = 32),
            email_hash          bytea NOT NULL UNIQUE CHECK (octet_length(email_hash) = 32),
            cpf_cripto          bytea NOT NULL,
            nome_cripto         bytea NOT NULL,
            email_cripto        bytea NOT NULL,
            dek_cripto          bytea NOT NULL,
            kek_versao          smallint NOT NULL CHECK (kek_versao > 0),
            senha_hash          text NOT NULL,
            totp_segredo_cripto bytea,
            mfa_ativo           boolean NOT NULL DEFAULT false,
            id_unidade          integer,
            status              text NOT NULL DEFAULT 'ativo'
                                CHECK (status IN ('ativo', 'inativo', 'bloqueado')),
            falhas_login        integer NOT NULL DEFAULT 0 CHECK (falhas_login >= 0),
            bloqueado_ate       timestamptz,
            criado_em           timestamptz NOT NULL DEFAULT now(),
            atualizado_em       timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.define_atualizado_em() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.atualizado_em := now();
            NEW.criado_em := OLD.criado_em;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER usuario_atualizado_em BEFORE UPDATE ON app.usuario
        FOR EACH ROW EXECUTE FUNCTION app.define_atualizado_em()
        """
    )
    op.execute("REVOKE ALL ON app.usuario FROM PUBLIC")
    op.execute("GRANT SELECT, INSERT, UPDATE ON app.usuario TO app_user")


def downgrade() -> None:
    op.execute("DROP TABLE app.usuario")
    op.execute("DROP FUNCTION app.define_atualizado_em()")
