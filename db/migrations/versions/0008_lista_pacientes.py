"""Permissão paciente:listar e índice da listagem paginada (RF-03, ADR-0014).

Só os perfis de acesso global (Administrador e Gestor) recebem a permissão: Gestor do Cuidado e
Navegador têm visão restrita pela SPEC, e o recorte por unidade ainda não existe (RF-10/12).

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO app.permissao (permissao, descricao)
        VALUES ('paciente:listar', 'Listar pacientes com dados resumidos e CPF mascarado')
        """
    )
    op.execute(
        """
        INSERT INTO app.papel_permissao (fk_papel_id_papel, fk_permissao_id_permissao)
        SELECT p.id_papel, m.id_permissao
          FROM app.papel p JOIN app.permissao m ON m.permissao = 'paciente:listar'
         WHERE p.papel IN ('Administrador', 'Gestor')
        """
    )
    op.execute("CREATE INDEX paciente_lista_idx ON app.paciente (criado_em DESC, id_publico DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX app.paciente_lista_idx")
    op.execute(
        """
        DELETE FROM app.papel_permissao WHERE fk_permissao_id_permissao IN
            (SELECT id_permissao FROM app.permissao WHERE permissao = 'paciente:listar')
        """
    )
    op.execute("DELETE FROM app.permissao WHERE permissao = 'paciente:listar'")
