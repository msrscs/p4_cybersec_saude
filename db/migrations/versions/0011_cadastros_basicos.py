"""Cadastros de unidade de saúde, serviço e CID (RF-09, RF-10, RF-11, ADR-0019).

Dados de catálogo, públicos: sem cifragem. O vínculo sensível (paciente x CID) vem com a OCI.
Exclusão lógica (status): as OCIs vão apontar para estes registros, por isso a app_user não tem
DELETE. usuario.id_unidade passa a referenciar unidade_saude; um código já digitado vira uma
unidade provisória, para não perder o dado informado.

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS = "status text NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'inativo'))"
_DATAS = (
    "criado_em timestamptz NOT NULL DEFAULT now(), atualizado_em timestamptz NOT NULL DEFAULT now()"
)
_TABELAS = ("unidade_saude", "servico_saude", "cid")
_PERMISSOES = (
    ("cadastro:ler", "Consultar unidades, serviços e CID"),
    ("cadastro:gerenciar", "Criar, alterar e inativar unidades, serviços e CID"),
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE app.unidade_saude (
            id_unidade   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            tipo_unidade text NOT NULL
                         CHECK (tipo_unidade IN
                                ('Posto de Saúde', 'Clínica', 'Hospital', 'Laboratório')),
            nome         text NOT NULL CHECK (char_length(nome) BETWEEN 2 AND 150),
            endereco     text NOT NULL CHECK (char_length(endereco) BETWEEN 3 AND 300),
            telefone     text CHECK (telefone ~ '^[0-9]{{10,11}}$'),
            {_STATUS},
            {_DATAS}
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX unidade_saude_nome_idx ON app.unidade_saude (lower(nome))")
    op.execute(
        f"""
        CREATE TABLE app.servico_saude (
            id_servico integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            nome       text NOT NULL CHECK (char_length(nome) BETWEEN 2 AND 150),
            descricao  text NOT NULL DEFAULT '' CHECK (char_length(descricao) <= 500),
            {_STATUS},
            {_DATAS}
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX servico_saude_nome_idx ON app.servico_saude (lower(nome))")
    op.execute(
        f"""
        CREATE TABLE app.cid (
            cid_hash  bytea PRIMARY KEY CHECK (octet_length(cid_hash) = 32),
            cid       text NOT NULL UNIQUE CHECK (cid ~ '^[A-Z][0-9]{{2}}(\\.[0-9A-Z]{{1,2}})?$'),
            descricao text NOT NULL CHECK (char_length(descricao) BETWEEN 2 AND 500),
            {_STATUS},
            {_DATAS}
        )
        """
    )
    for tabela in _TABELAS:
        op.execute(f"REVOKE ALL ON app.{tabela} FROM PUBLIC")
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON app.{tabela} TO app_user")
        op.execute(
            f"CREATE TRIGGER {tabela}_atualizado_em BEFORE UPDATE ON app.{tabela} "
            "FOR EACH ROW EXECUTE FUNCTION app.define_atualizado_em()"
        )

    # Códigos já digitados no campo livre viram unidades provisórias, a revisar na tela.
    op.execute(
        """
        INSERT INTO app.unidade_saude (id_unidade, tipo_unidade, nome, endereco)
        OVERRIDING SYSTEM VALUE
        SELECT DISTINCT id_unidade, 'Posto de Saúde',
               'Unidade ' || id_unidade || ' (revisar cadastro)', 'A preencher'
          FROM app.usuario WHERE id_unidade IS NOT NULL
        """
    )
    op.execute(
        """
        SELECT setval(pg_get_serial_sequence('app.unidade_saude', 'id_unidade'),
                      coalesce((SELECT max(id_unidade) FROM app.unidade_saude), 1),
                      (SELECT count(*) > 0 FROM app.unidade_saude))
        """
    )
    op.execute(
        """
        ALTER TABLE app.usuario ADD CONSTRAINT usuario_id_unidade_fkey
        FOREIGN KEY (id_unidade) REFERENCES app.unidade_saude (id_unidade)
        """
    )
    op.execute("CREATE INDEX usuario_id_unidade_idx ON app.usuario (id_unidade)")

    for permissao, descricao in _PERMISSOES:
        op.execute(
            sa.text(
                "INSERT INTO app.permissao (permissao, descricao) VALUES (:permissao, :descricao)"
            ).bindparams(permissao=permissao, descricao=descricao)
        )
    op.execute(
        """
        INSERT INTO app.papel_permissao (fk_papel_id_papel, fk_permissao_id_permissao)
        SELECT p.id_papel, m.id_permissao
          FROM app.papel p JOIN app.permissao m ON
               (p.papel = 'Administrador' AND m.permissao LIKE 'cadastro:%')
            OR (p.papel IN ('Gestor', 'Gestor do Cuidado', 'Navegador')
                AND m.permissao = 'cadastro:ler')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM app.papel_permissao WHERE fk_permissao_id_permissao IN
            (SELECT id_permissao FROM app.permissao WHERE permissao LIKE 'cadastro:%')
        """
    )
    op.execute("DELETE FROM app.permissao WHERE permissao LIKE 'cadastro:%'")
    op.execute("DROP INDEX app.usuario_id_unidade_idx")
    op.execute("ALTER TABLE app.usuario DROP CONSTRAINT usuario_id_unidade_fkey")
    for tabela in _TABELAS:
        op.execute(f"DROP TABLE app.{tabela}")
