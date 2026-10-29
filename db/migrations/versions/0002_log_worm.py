"""Tabela log de auditoria append-only (WORM) (RF-04).

Duas camadas: a role da aplicação só tem INSERT/SELECT, e triggers bloqueiam
UPDATE, DELETE e TRUNCATE para qualquer role (inclusive a dona da tabela).
data_hora é sempre definida pelo servidor. O cálculo de prev_hash e
hash_assinatura_worm (cadeia SHA-256) entra na T06.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.log (
            id_log               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            data_hora            timestamptz NOT NULL DEFAULT clock_timestamp(),
            acao                 text NOT NULL CHECK (char_length(acao) BETWEEN 1 AND 100),
            resumo_acessado      jsonb NOT NULL DEFAULT '{}'::jsonb,
            ip_origem            inet,
            request_id           uuid,
            geolocalizacao       text CHECK (char_length(geolocalizacao) <= 200),
            cpf_usuario_hash     bytea CHECK (octet_length(cpf_usuario_hash) = 32),
            cpf_paciente_hash    bytea CHECK (octet_length(cpf_paciente_hash) = 32),
            id_oci               bigint,
            prev_hash            bytea CHECK (octet_length(prev_hash) = 32),
            hash_assinatura_worm bytea CHECK (octet_length(hash_assinatura_worm) = 32)
        )
        """
    )
    op.execute("CREATE INDEX log_data_hora_idx ON app.log (data_hora)")
    op.execute("CREATE INDEX log_cpf_usuario_hash_idx ON app.log (cpf_usuario_hash)")
    op.execute("CREATE INDEX log_acao_idx ON app.log (acao)")

    op.execute(
        """
        CREATE FUNCTION app.log_bloqueia_alteracao() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'log de auditoria é append-only (WORM): % bloqueado', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.log_define_data_hora() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.data_hora := clock_timestamp();
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER log_worm_linha BEFORE UPDATE OR DELETE ON app.log
        FOR EACH ROW EXECUTE FUNCTION app.log_bloqueia_alteracao()
        """
    )
    op.execute(
        """
        CREATE TRIGGER log_worm_truncate BEFORE TRUNCATE ON app.log
        FOR EACH STATEMENT EXECUTE FUNCTION app.log_bloqueia_alteracao()
        """
    )
    op.execute(
        """
        CREATE TRIGGER log_data_hora BEFORE INSERT ON app.log
        FOR EACH ROW EXECUTE FUNCTION app.log_define_data_hora()
        """
    )
    op.execute("REVOKE ALL ON app.log FROM PUBLIC")
    op.execute("GRANT SELECT, INSERT ON app.log TO app_user")


def downgrade() -> None:
    raise RuntimeError("O log de auditoria é WORM: esta migration não pode ser revertida.")
