"""Cadastro de tipo de unidade: a lista fixa vira tabela (RF-10, ADR-0021).

Os 4 tipos da SPEC entram como dados iniciais e cada unidade existente passa a apontar para o seu.
As permissões são as mesmas dos demais catálogos (cadastro:ler e cadastro:gerenciar).

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.tipo_unidade (
            id_tipo_unidade integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            nome            text NOT NULL CHECK (char_length(nome) BETWEEN 2 AND 150),
            descricao       text NOT NULL DEFAULT '' CHECK (char_length(descricao) <= 500),
            status          text NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'inativo')),
            criado_em       timestamptz NOT NULL DEFAULT now(),
            atualizado_em   timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX tipo_unidade_nome_idx ON app.tipo_unidade (lower(nome))")
    op.execute("REVOKE ALL ON app.tipo_unidade FROM PUBLIC")
    op.execute("GRANT SELECT, INSERT, UPDATE ON app.tipo_unidade TO app_user")
    op.execute(
        """
        CREATE TRIGGER tipo_unidade_atualizado_em BEFORE UPDATE ON app.tipo_unidade
        FOR EACH ROW EXECUTE FUNCTION app.define_atualizado_em()
        """
    )
    op.execute(
        """
        INSERT INTO app.tipo_unidade (nome) VALUES
            ('Posto de Saúde'), ('Clínica'), ('Hospital'), ('Laboratório')
        """
    )

    op.execute(
        """
        ALTER TABLE app.unidade_saude ADD COLUMN id_tipo_unidade integer
        REFERENCES app.tipo_unidade (id_tipo_unidade)
        """
    )
    op.execute(
        """
        UPDATE app.unidade_saude u SET id_tipo_unidade = t.id_tipo_unidade
          FROM app.tipo_unidade t WHERE t.nome = u.tipo_unidade
        """
    )
    op.execute("ALTER TABLE app.unidade_saude ALTER COLUMN id_tipo_unidade SET NOT NULL")
    op.execute("ALTER TABLE app.unidade_saude DROP COLUMN tipo_unidade")
    op.execute("CREATE INDEX unidade_saude_tipo_idx ON app.unidade_saude (id_tipo_unidade)")


def downgrade() -> None:
    # A lista antiga só aceitava 4 valores: tipo criado depois volta como 'Posto de Saúde'.
    op.execute("ALTER TABLE app.unidade_saude ADD COLUMN tipo_unidade text")
    op.execute(
        """
        UPDATE app.unidade_saude u
           SET tipo_unidade = CASE
               WHEN t.nome IN ('Posto de Saúde', 'Clínica', 'Hospital', 'Laboratório') THEN t.nome
               ELSE 'Posto de Saúde'
           END
          FROM app.tipo_unidade t WHERE t.id_tipo_unidade = u.id_tipo_unidade
        """
    )
    op.execute("ALTER TABLE app.unidade_saude ALTER COLUMN tipo_unidade SET NOT NULL")
    op.execute(
        """
        ALTER TABLE app.unidade_saude ADD CONSTRAINT unidade_saude_tipo_unidade_check
        CHECK (tipo_unidade IN ('Posto de Saúde', 'Clínica', 'Hospital', 'Laboratório'))
        """
    )
    op.execute("ALTER TABLE app.unidade_saude DROP COLUMN id_tipo_unidade")
    op.execute("DROP TABLE app.tipo_unidade")
