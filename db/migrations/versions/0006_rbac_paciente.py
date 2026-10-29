"""RBAC mínimo e cadastro de pacientes (RF-03, RF-05/06/07/13 parcial, T07, ADR-0011).

- papel, permissao, grupo e as tabelas de relacionamento da SPEC (RF-13). Os 5 perfis da
  SPEC entram como papéis, cada um com um grupo de mesmo nome. A aplicação só lê essas
  tabelas; a atribuição de usuário a grupo (usuario_grupo) é feita pelo script atribuir_grupo.
- paciente: dados pessoais só cifrados (envelope por registro, como usuario); identificador
  público opaco (UUID) para URLs; exclusão lógica (status). A aplicação não tem DELETE e só
  pode atualizar os campos editáveis e o status.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS = "status text NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'inativo'))"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE app.papel (
            id_papel  smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            papel     text NOT NULL UNIQUE CHECK (char_length(papel) BETWEEN 1 AND 60),
            descricao text NOT NULL DEFAULT '' CHECK (char_length(descricao) <= 300),
            {_STATUS}
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE app.permissao (
            id_permissao smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            permissao    text NOT NULL UNIQUE CHECK (permissao ~ '^[a-z_]+:[a-z_]+$'),
            descricao    text NOT NULL DEFAULT '' CHECK (char_length(descricao) <= 300),
            {_STATUS}
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE app.grupo (
            id_grupo smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            grupo    text NOT NULL UNIQUE CHECK (char_length(grupo) BETWEEN 1 AND 60),
            {_STATUS}
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.papel_permissao (
            fk_papel_id_papel         smallint NOT NULL REFERENCES app.papel (id_papel),
            fk_permissao_id_permissao smallint NOT NULL REFERENCES app.permissao (id_permissao),
            PRIMARY KEY (fk_papel_id_papel, fk_permissao_id_permissao)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.grupo_papel (
            fk_grupo_id_grupo smallint NOT NULL REFERENCES app.grupo (id_grupo),
            fk_papel_id_papel smallint NOT NULL REFERENCES app.papel (id_papel),
            PRIMARY KEY (fk_grupo_id_grupo, fk_papel_id_papel)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.usuario_grupo (
            fk_usuario_cpf_hash bytea NOT NULL REFERENCES app.usuario (cpf_hash),
            fk_grupo_id_grupo   smallint NOT NULL REFERENCES app.grupo (id_grupo),
            PRIMARY KEY (fk_usuario_cpf_hash, fk_grupo_id_grupo)
        )
        """
    )

    op.execute(
        """
        INSERT INTO app.papel (papel, descricao) VALUES
            ('Administrador', 'Acesso total ao sistema'),
            ('Gestor', 'Visualiza a execução da OCI em toda a rede de saúde'),
            ('Gestor do Cuidado', 'Visualiza a gestão da OCI na rede própria'),
            ('Navegador', 'Acompanha os pacientes da própria unidade na linha de cuidado'),
            ('Auditor', 'Somente leitura dos logs')
        """
    )
    op.execute(
        """
        INSERT INTO app.permissao (permissao, descricao) VALUES
            ('paciente:ler', 'Consultar e buscar pacientes'),
            ('paciente:criar', 'Cadastrar pacientes'),
            ('paciente:editar', 'Alterar nome, nascimento e e-mail de pacientes'),
            ('paciente:inativar', 'Inativar e reativar pacientes')
        """
    )
    op.execute(
        """
        INSERT INTO app.papel_permissao (fk_papel_id_papel, fk_permissao_id_permissao)
        SELECT p.id_papel, m.id_permissao
          FROM app.papel p JOIN app.permissao m ON
               p.papel = 'Administrador'
            OR (p.papel IN ('Gestor', 'Gestor do Cuidado', 'Navegador')
                AND m.permissao IN ('paciente:ler', 'paciente:criar', 'paciente:editar'))
        """
    )
    op.execute("INSERT INTO app.grupo (grupo) SELECT papel FROM app.papel ORDER BY id_papel")
    op.execute(
        """
        INSERT INTO app.grupo_papel (fk_grupo_id_grupo, fk_papel_id_papel)
        SELECT g.id_grupo, p.id_papel FROM app.grupo g JOIN app.papel p ON p.papel = g.grupo
        """
    )

    op.execute(
        """
        CREATE TABLE app.paciente (
            cpf_hash               bytea PRIMARY KEY CHECK (octet_length(cpf_hash) = 32),
            id_publico             uuid NOT NULL UNIQUE,
            cpf_cripto             bytea NOT NULL,
            nome_cripto            bytea NOT NULL,
            data_nascimento_cripto bytea NOT NULL,
            email_cripto           bytea,
            dek_cripto             bytea NOT NULL,
            kek_versao             smallint NOT NULL CHECK (kek_versao > 0),
            status                 text NOT NULL DEFAULT 'ativo'
                                   CHECK (status IN ('ativo', 'inativo')),
            criado_em              timestamptz NOT NULL DEFAULT now(),
            atualizado_em          timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TRIGGER paciente_atualizado_em BEFORE UPDATE ON app.paciente
        FOR EACH ROW EXECUTE FUNCTION app.define_atualizado_em()
        """
    )

    tabelas_rbac = ("papel", "permissao", "grupo", "papel_permissao", "grupo_papel")
    for tabela in (*tabelas_rbac, "usuario_grupo", "paciente"):
        op.execute(f"REVOKE ALL ON app.{tabela} FROM PUBLIC")
    for tabela in tabelas_rbac:
        op.execute(f"GRANT SELECT ON app.{tabela} TO app_user")
    op.execute("GRANT SELECT, INSERT, DELETE ON app.usuario_grupo TO app_user")
    op.execute("GRANT SELECT, INSERT ON app.paciente TO app_user")
    op.execute(
        "GRANT UPDATE (nome_cripto, data_nascimento_cripto, email_cripto, status)"
        " ON app.paciente TO app_user"
    )


def downgrade() -> None:
    for tabela in (
        "paciente",
        "usuario_grupo",
        "grupo_papel",
        "papel_permissao",
        "grupo",
        "permissao",
        "papel",
    ):
        op.execute(f"DROP TABLE app.{tabela}")
