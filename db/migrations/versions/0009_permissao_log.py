"""Permissão log:ler para Auditor e Administrador (RF-04, ADR-0015).

Os índices da consulta (data_hora, acao, cpf_usuario_hash, seq_cadeia) já existem desde as
migrations 0002 e 0005.

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO app.permissao (permissao, descricao)
        VALUES ('log:ler', 'Consultar o log de auditoria (somente leitura)')
        """
    )
    op.execute(
        """
        INSERT INTO app.papel_permissao (fk_papel_id_papel, fk_permissao_id_permissao)
        SELECT p.id_papel, m.id_permissao
          FROM app.papel p JOIN app.permissao m ON m.permissao = 'log:ler'
         WHERE p.papel IN ('Administrador', 'Auditor')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM app.papel_permissao WHERE fk_permissao_id_permissao IN
            (SELECT id_permissao FROM app.permissao WHERE permissao = 'log:ler')
        """
    )
    op.execute("DELETE FROM app.permissao WHERE permissao = 'log:ler'")
