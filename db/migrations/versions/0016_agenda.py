"""Agenda de atendimento e serviços de cada CID (RF-12, RF-13, ADR-0026).

agenda_servico diz quando cada unidade atende cada serviço, e quantas vagas há por horário: as vagas
livres são calculadas subtraindo as etapas marcadas. cid_servico_saude diz quais serviços atendem
cada CID. A etapa remarcada fica como 'remarcado', e uma nova é criada: o histórico é preservado.

Revision ID: 0016
Revises: 0015
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.agenda_servico (
            id_agenda         integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            id_unidade        integer NOT NULL REFERENCES app.unidade_saude (id_unidade),
            id_servico        integer NOT NULL REFERENCES app.servico_saude (id_servico),
            dia_semana        smallint NOT NULL CHECK (dia_semana BETWEEN 0 AND 6),
            hora_inicio       time NOT NULL,
            hora_fim          time NOT NULL,
            duracao_minutos   integer NOT NULL CHECK (duracao_minutos BETWEEN 5 AND 480),
            vagas_por_horario integer NOT NULL CHECK (vagas_por_horario BETWEEN 1 AND 100),
            status            text NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'inativo')),
            criado_em         timestamptz NOT NULL DEFAULT now(),
            atualizado_em     timestamptz NOT NULL DEFAULT now(),
            CHECK (hora_fim > hora_inicio)
        )
        """
    )
    op.execute(
        "CREATE INDEX agenda_servico_alvo_idx ON app.agenda_servico (id_unidade, id_servico)"
    )
    op.execute(
        """
        CREATE TRIGGER agenda_servico_atualizado_em BEFORE UPDATE ON app.agenda_servico
        FOR EACH ROW EXECUTE FUNCTION app.define_atualizado_em()
        """
    )
    op.execute(
        """
        CREATE TABLE app.cid_servico_saude (
            fk_cid_cid_hash             bytea NOT NULL REFERENCES app.cid (cid_hash),
            fk_servico_saude_id_servico integer NOT NULL
                REFERENCES app.servico_saude (id_servico),
            PRIMARY KEY (fk_cid_cid_hash, fk_servico_saude_id_servico)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX cid_servico_servico_idx
        ON app.cid_servico_saude (fk_servico_saude_id_servico)
        """
    )
    op.execute(
        """
        CREATE INDEX oci_navegacao_vagas_idx
        ON app.oci_navegacao (id_unidade, id_servico, data_hora)
        """
    )
    op.execute("ALTER TABLE app.oci_navegacao DROP CONSTRAINT oci_navegacao_status_check")
    op.execute(
        """
        ALTER TABLE app.oci_navegacao ADD CONSTRAINT oci_navegacao_status_check
        CHECK (status IN ('agendado', 'realizado', 'faltou', 'cancelado', 'remarcado'))
        """
    )
    op.execute("REVOKE ALL ON app.agenda_servico FROM PUBLIC")
    op.execute("REVOKE ALL ON app.cid_servico_saude FROM PUBLIC")
    op.execute("GRANT SELECT, INSERT, UPDATE ON app.agenda_servico TO app_user")
    op.execute("GRANT SELECT, INSERT, DELETE ON app.cid_servico_saude TO app_user")


def downgrade() -> None:
    # Remarcada volta como cancelada: a situação antiga não existia.
    op.execute("UPDATE app.oci_navegacao SET status = 'cancelado' WHERE status = 'remarcado'")
    op.execute("ALTER TABLE app.oci_navegacao DROP CONSTRAINT oci_navegacao_status_check")
    op.execute(
        """
        ALTER TABLE app.oci_navegacao ADD CONSTRAINT oci_navegacao_status_check
        CHECK (status IN ('agendado', 'realizado', 'faltou', 'cancelado'))
        """
    )
    op.execute("DROP INDEX app.oci_navegacao_vagas_idx")
    op.execute("DROP TABLE app.cid_servico_saude")
    op.execute("DROP TABLE app.agenda_servico")
