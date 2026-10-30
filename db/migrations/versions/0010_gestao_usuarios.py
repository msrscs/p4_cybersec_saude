"""Gestão de usuários pela API e CPF em claro no log só para o Administrador (RF-01, ADR-0017).

- Permissões usuario:* e log:ver_cpf, só para o papel Administrador.
- usuario.id_publico: identificador opaco para URLs, como em paciente (o CPF nunca vai na URL).

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERMISSOES = (
    ("usuario:ler", "Consultar e listar usuários"),
    ("usuario:criar", "Cadastrar usuários"),
    ("usuario:editar", "Alterar nome, e-mail e unidade de usuários"),
    ("usuario:inativar", "Inativar e reativar usuários"),
    ("usuario:resetar", "Resetar senha e MFA de usuários"),
    ("usuario:grupos", "Alterar os grupos de usuários"),
    ("log:ver_cpf", "Ver CPFs em claro na consulta do log"),
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE app.usuario ADD COLUMN id_publico uuid NOT NULL DEFAULT gen_random_uuid()"
    )
    op.execute("ALTER TABLE app.usuario ADD CONSTRAINT usuario_id_publico_key UNIQUE (id_publico)")
    op.execute("CREATE INDEX usuario_lista_idx ON app.usuario (criado_em DESC, id_publico DESC)")
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
          FROM app.papel p JOIN app.permissao m
            ON m.permissao LIKE 'usuario:%' OR m.permissao = 'log:ver_cpf'
         WHERE p.papel = 'Administrador'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM app.papel_permissao WHERE fk_permissao_id_permissao IN
            (SELECT id_permissao FROM app.permissao
              WHERE permissao LIKE 'usuario:%' OR permissao = 'log:ver_cpf')
        """
    )
    op.execute(
        "DELETE FROM app.permissao WHERE permissao LIKE 'usuario:%' OR permissao = 'log:ver_cpf'"
    )
    op.execute("DROP INDEX app.usuario_lista_idx")
    op.execute("ALTER TABLE app.usuario DROP COLUMN id_publico")
