"""OCI e navegação (RF-12, ADR-0025).

O vínculo entre paciente e CID é dado de saúde: o resultado fica cifrado (envelope por registro,
como paciente) e o acesso é restrito por permissão e por unidade. O prazo é gravado na abertura,
para uma mudança no tipo não alterar quem já está em atendimento. A app_user não tem DELETE: OCI
é cancelada, e navegação muda de situação. Uma OCI aberta por paciente e tipo.

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERMISSOES = (
    ("oci:ler", "Consultar OCIs e navegação, conforme o alcance do perfil"),
    ("oci:criar", "Abrir OCI"),
    ("oci:editar", "Alterar OCI e marcar a navegação"),
    ("oci:concluir", "Concluir e cancelar OCI"),
    ("oci:todas_unidades", "Alcance sobre todas as unidades; sem ela, só a própria"),
)
_MATRIZ = {
    "Administrador": (
        "oci:ler",
        "oci:criar",
        "oci:editar",
        "oci:concluir",
        "oci:todas_unidades",
    ),
    "Gestor": ("oci:ler", "oci:todas_unidades"),
    "Gestor do Cuidado": ("oci:ler",),
    "Navegador": ("oci:ler", "oci:criar", "oci:editar", "oci:concluir"),
}


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.oci (
            id_oci             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            id_publico         uuid NOT NULL UNIQUE,
            id_tipo_oci        integer NOT NULL REFERENCES app.tipo_oci (id_tipo_oci),
            cpf_paciente_hash  bytea NOT NULL REFERENCES app.paciente (cpf_hash),
            cid_hash           bytea NOT NULL REFERENCES app.cid (cid_hash),
            data_criacao       timestamptz NOT NULL DEFAULT clock_timestamp(),
            prazo_em           timestamptz NOT NULL,
            resultado_cripto   bytea,
            dek_cripto         bytea,
            kek_versao         smallint CHECK (kek_versao > 0),
            resultado_cid_hash bytea REFERENCES app.cid (cid_hash),
            status             text NOT NULL DEFAULT 'aberta'
                               CHECK (status IN ('aberta', 'concluida', 'cancelada')),
            atualizado_em      timestamptz NOT NULL DEFAULT now(),
            CHECK (status <> 'concluida' OR resultado_cripto IS NOT NULL)
        )
        """
    )
    op.execute("CREATE INDEX oci_lista_idx ON app.oci (data_criacao DESC, id_publico DESC)")
    op.execute("CREATE INDEX oci_paciente_idx ON app.oci (cpf_paciente_hash)")
    op.execute("CREATE INDEX oci_tipo_idx ON app.oci (id_tipo_oci)")
    op.execute("CREATE INDEX oci_cid_idx ON app.oci (cid_hash)")
    op.execute(
        """
        CREATE UNIQUE INDEX oci_uma_aberta_idx ON app.oci (cpf_paciente_hash, id_tipo_oci)
        WHERE status = 'aberta'
        """
    )
    op.execute(
        """
        CREATE TABLE app.oci_navegacao (
            id_oci_navegacao bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            id_oci           bigint NOT NULL REFERENCES app.oci (id_oci),
            id_unidade       integer NOT NULL REFERENCES app.unidade_saude (id_unidade),
            id_servico       integer NOT NULL REFERENCES app.servico_saude (id_servico),
            data_hora        timestamptz NOT NULL,
            status           text NOT NULL DEFAULT 'agendado'
                             CHECK (status IN ('agendado', 'realizado', 'faltou', 'cancelado')),
            criado_em        timestamptz NOT NULL DEFAULT now(),
            atualizado_em    timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX oci_navegacao_oci_idx ON app.oci_navegacao (id_oci)")
    op.execute("CREATE INDEX oci_navegacao_unidade_idx ON app.oci_navegacao (id_unidade)")
    op.execute("CREATE INDEX oci_navegacao_servico_idx ON app.oci_navegacao (id_servico)")
    op.execute(
        """
        CREATE FUNCTION app.define_oci_atualizado_em() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.atualizado_em := now();
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER oci_atualizado_em BEFORE UPDATE ON app.oci
        FOR EACH ROW EXECUTE FUNCTION app.define_oci_atualizado_em()
        """
    )
    op.execute(
        """
        CREATE TRIGGER oci_navegacao_atualizado_em BEFORE UPDATE ON app.oci_navegacao
        FOR EACH ROW EXECUTE FUNCTION app.define_oci_atualizado_em()
        """
    )
    op.execute("REVOKE ALL ON app.oci FROM PUBLIC")
    op.execute("REVOKE ALL ON app.oci_navegacao FROM PUBLIC")
    op.execute("GRANT SELECT, INSERT ON app.oci TO app_user")
    op.execute(
        "GRANT UPDATE (cid_hash, resultado_cripto, dek_cripto, kek_versao, resultado_cid_hash,"
        " status) ON app.oci TO app_user"
    )
    op.execute("GRANT SELECT, INSERT ON app.oci_navegacao TO app_user")
    op.execute("GRANT UPDATE (data_hora, status) ON app.oci_navegacao TO app_user")

    for permissao, descricao in _PERMISSOES:
        op.execute(
            sa.text(
                "INSERT INTO app.permissao (permissao, descricao) VALUES (:permissao, :descricao)"
            ).bindparams(permissao=permissao, descricao=descricao)
        )
    for papel, permissoes in _MATRIZ.items():
        for permissao in permissoes:
            op.execute(
                sa.text(
                    """
                    INSERT INTO app.papel_permissao (fk_papel_id_papel, fk_permissao_id_permissao)
                    SELECT p.id_papel, m.id_permissao
                      FROM app.papel p JOIN app.permissao m ON m.permissao = :permissao
                     WHERE p.papel = :papel
                    """
                ).bindparams(papel=papel, permissao=permissao)
            )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM app.papel_permissao WHERE fk_permissao_id_permissao IN
            (SELECT id_permissao FROM app.permissao WHERE permissao LIKE 'oci:%')
        """
    )
    op.execute("DELETE FROM app.permissao WHERE permissao LIKE 'oci:%'")
    op.execute("DROP TABLE app.oci_navegacao")
    op.execute("DROP TABLE app.oci")
    op.execute("DROP FUNCTION app.define_oci_atualizado_em()")
