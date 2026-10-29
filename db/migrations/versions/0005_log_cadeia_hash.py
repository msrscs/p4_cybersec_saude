"""Cadeia de hashes do log de auditoria e checkpoints assinados (RNF-04, T06, ADR-0010).

- seq_cadeia: posição na cadeia, atribuída sob lock de transação (1, 2, 3... sem lacunas).
- prev_hash / hash_assinatura_worm: SHA-256 calculado pela trigger; o valor enviado pelo
  cliente é sempre sobrescrito. O 1º registro usa prev_hash = 32 bytes zero.
- data_hora passa a ser definida pela mesma trigger, depois do lock (monotônica com a seq).
- Registros anteriores a esta migration são encadeados uma única vez, dentro desta
  transação, com a trigger de bloqueio desligada só durante o preenchimento (ADR-0010).
- log_checkpoint: (seq, hash) assinados com HMAC por chave fora do banco, também WORM.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# SQL fixo (sem interpolação). Genesis = 32 bytes zero; 7402116005 é a chave arbitrária do
# advisory lock que serializa a cadeia (a mesma em toda inserção).


def upgrade() -> None:
    op.execute("LOCK TABLE app.log IN EXCLUSIVE MODE")
    op.execute("ALTER TABLE app.log ADD COLUMN seq_cadeia bigint CHECK (seq_cadeia > 0)")

    # Parte com prefixo de tamanho (4 bytes, big-endian); NULL vira 0xFFFFFFFF sem dados.
    op.execute(
        r"""
        CREATE FUNCTION app.log_parte(v bytea) RETURNS bytea
        LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
            SELECT CASE WHEN v IS NULL THEN '\xffffffff'::bytea
                        ELSE int4send(length(v)) || v END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.log_texto(v text) RETURNS bytea
        LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
            SELECT app.log_parte(convert_to(v, 'UTF8'))
        $$
        """
    )
    # Mesma serialização de app/core/cadeia.py (a verificação recalcula em Python).
    op.execute(
        """
        CREATE FUNCTION app.log_calcular_hash(prev bytea, r app.log) RETURNS bytea
        LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
            SELECT sha256(
                app.log_texto('cybersec-saude/log/v1')
                || app.log_parte(prev)
                || app.log_texto(r.seq_cadeia::text)
                || app.log_texto(r.id_log::text)
                || app.log_texto(((extract(epoch FROM r.data_hora) * 1000000)::bigint)::text)
                || app.log_texto(r.acao)
                || app.log_texto(r.resumo_acessado::text)
                || app.log_texto(r.ip_origem::text)
                || app.log_texto(r.request_id::text)
                || app.log_texto(r.geolocalizacao)
                || app.log_parte(r.cpf_usuario_hash)
                || app.log_parte(r.cpf_paciente_hash)
                || app.log_texto(r.id_oci::text)
            )
        $$
        """
    )

    # Preenche a cadeia dos registros já existentes (única alteração permitida no log).
    op.execute("ALTER TABLE app.log DISABLE TRIGGER log_worm_linha")
    op.execute(
        """
        DO $$
        DECLARE
            r app.log;
            v_prev bytea := decode(repeat('00', 32), 'hex');
            v_seq bigint := 0;
        BEGIN
            FOR r IN SELECT * FROM app.log ORDER BY id_log LOOP
                v_seq := v_seq + 1;
                r.seq_cadeia := v_seq;
                UPDATE app.log
                   SET seq_cadeia = v_seq,
                       prev_hash = v_prev,
                       hash_assinatura_worm = app.log_calcular_hash(v_prev, r)
                 WHERE id_log = r.id_log
                RETURNING hash_assinatura_worm INTO v_prev;
            END LOOP;
        END
        $$
        """
    )
    op.execute("ALTER TABLE app.log ENABLE TRIGGER log_worm_linha")
    op.execute(
        """
        ALTER TABLE app.log
            ALTER COLUMN seq_cadeia SET NOT NULL,
            ALTER COLUMN prev_hash SET NOT NULL,
            ALTER COLUMN hash_assinatura_worm SET NOT NULL
        """
    )
    op.execute("CREATE UNIQUE INDEX log_seq_cadeia_idx ON app.log (seq_cadeia)")

    # Nova trigger de inserção: lock -> horário -> seq -> hashes. Substitui log_data_hora.
    op.execute("DROP TRIGGER log_data_hora ON app.log")
    op.execute("DROP FUNCTION app.log_define_data_hora()")
    op.execute(
        """
        CREATE FUNCTION app.log_encadear() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE
            v_seq bigint;
            v_hash bytea;
        BEGIN
            PERFORM pg_advisory_xact_lock(7402116005);
            SELECT l.seq_cadeia, l.hash_assinatura_worm INTO v_seq, v_hash
              FROM app.log l ORDER BY l.seq_cadeia DESC LIMIT 1;
            NEW.data_hora := clock_timestamp();
            NEW.seq_cadeia := coalesce(v_seq, 0) + 1;
            NEW.prev_hash := coalesce(v_hash, decode(repeat('00', 32), 'hex'));
            NEW.hash_assinatura_worm := app.log_calcular_hash(NEW.prev_hash, NEW);
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER log_encadear BEFORE INSERT ON app.log
        FOR EACH ROW EXECUTE FUNCTION app.log_encadear()
        """
    )

    op.execute(
        """
        CREATE TABLE app.log_checkpoint (
            id_checkpoint bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            criado_em     timestamptz NOT NULL DEFAULT clock_timestamp(),
            seq_cadeia    bigint NOT NULL REFERENCES app.log (seq_cadeia),
            hash_cadeia   bytea NOT NULL CHECK (octet_length(hash_cadeia) = 32),
            assinatura    bytea NOT NULL CHECK (octet_length(assinatura) = 32)
        )
        """
    )
    op.execute("CREATE INDEX log_checkpoint_seq_idx ON app.log_checkpoint (seq_cadeia)")
    op.execute(
        """
        CREATE FUNCTION app.log_checkpoint_define_data() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            NEW.criado_em := clock_timestamp();
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER log_checkpoint_data BEFORE INSERT ON app.log_checkpoint
        FOR EACH ROW EXECUTE FUNCTION app.log_checkpoint_define_data()
        """
    )
    op.execute(
        """
        CREATE TRIGGER log_checkpoint_worm_linha BEFORE UPDATE OR DELETE ON app.log_checkpoint
        FOR EACH ROW EXECUTE FUNCTION app.log_bloqueia_alteracao()
        """
    )
    op.execute(
        """
        CREATE TRIGGER log_checkpoint_worm_truncate BEFORE TRUNCATE ON app.log_checkpoint
        FOR EACH STATEMENT EXECUTE FUNCTION app.log_bloqueia_alteracao()
        """
    )
    op.execute("REVOKE ALL ON app.log_checkpoint FROM PUBLIC")
    op.execute("GRANT SELECT, INSERT ON app.log_checkpoint TO app_user")
    for funcao in ("log_parte(bytea)", "log_texto(text)", "log_calcular_hash(bytea, app.log)"):
        op.execute(f"REVOKE ALL ON FUNCTION app.{funcao} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION app.{funcao} TO app_user")


def downgrade() -> None:
    raise RuntimeError("O log de auditoria é WORM: esta migration não pode ser revertida.")
