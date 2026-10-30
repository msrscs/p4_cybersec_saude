"""Tipo de OCI e os CIDs de cada tipo (RF-08, RF-13, ADR-0024).

Catálogo público, como os demais: sem cifragem e com exclusão lógica. O prazo de diagnóstico é em
dias. Os vínculos com CID podem ser incluídos e removidos; o histórico fica no log. As permissões
são as dos catálogos (cadastro:ler e cadastro:gerenciar).

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.tipo_oci (
            id_tipo_oci       integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            tipo_oci          text NOT NULL CHECK (char_length(tipo_oci) BETWEEN 2 AND 150),
            prazo_diagnostico integer NOT NULL CHECK (prazo_diagnostico BETWEEN 1 AND 3650),
            status            text NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'inativo')),
            criado_em         timestamptz NOT NULL DEFAULT now(),
            atualizado_em     timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX tipo_oci_nome_idx ON app.tipo_oci (lower(tipo_oci))")
    op.execute(
        """
        CREATE TRIGGER tipo_oci_atualizado_em BEFORE UPDATE ON app.tipo_oci
        FOR EACH ROW EXECUTE FUNCTION app.define_atualizado_em()
        """
    )
    op.execute(
        """
        CREATE TABLE app.tipo_oci_cid (
            fk_tipo_oci_tipo_oci_id integer NOT NULL REFERENCES app.tipo_oci (id_tipo_oci),
            fk_cid_cid_hash         bytea NOT NULL REFERENCES app.cid (cid_hash),
            PRIMARY KEY (fk_tipo_oci_tipo_oci_id, fk_cid_cid_hash)
        )
        """
    )
    op.execute("CREATE INDEX tipo_oci_cid_cid_idx ON app.tipo_oci_cid (fk_cid_cid_hash)")
    op.execute("REVOKE ALL ON app.tipo_oci FROM PUBLIC")
    op.execute("REVOKE ALL ON app.tipo_oci_cid FROM PUBLIC")
    op.execute("GRANT SELECT, INSERT, UPDATE ON app.tipo_oci TO app_user")
    op.execute("GRANT SELECT, INSERT, DELETE ON app.tipo_oci_cid TO app_user")


def downgrade() -> None:
    op.execute("DROP TABLE app.tipo_oci_cid")
    op.execute("DROP TABLE app.tipo_oci")
