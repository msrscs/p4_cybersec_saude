"""RNF-04 / THREAT_MODEL T1, R2: cadeia de hashes do log e checkpoints assinados (ADR-0010).

As adulterações são feitas como superusuário com `session_replication_role = replica`
(desliga triggers e FKs, como faria um atacante com controle total do banco), dentro de uma
transação desfeita ao fim de cada teste.
"""

import os
import threading
import uuid

import psycopg
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.cadeia import Ancora, assinar_checkpoint
from app.core.config import Settings
from app.core.crypto import gerar_chave_b64
from app.core.database import criar_engine, criar_sessionmaker
from app.core.db_url import APP_DB_ROLE
from app.models import Log, LogCheckpoint
from app.services import auditoria, cadeia_log
from app.services.auditoria import ContextoRequisicao, Evento
from app.services.cadeia_log import Motivo, ResultadoVerificacao

from .conftest import BancoTeste, banco_temporario, migrar

Conn = psycopg.Connection[tuple[object, ...]]


def _chave(settings: Settings) -> bytes:
    assert settings.chave_checkpoint is not None
    return settings.chave_checkpoint


def _verificar(
    db: Session, settings: Settings, ancora: Ancora | None = None
) -> ResultadoVerificacao:
    return cadeia_log.verificar_cadeia(db, _chave(settings), ancora, lote=7)


def _registrar(fabrica: sessionmaker[Session], n: int = 1, acao: str = "teste_cadeia") -> None:
    with fabrica() as db, db.begin():
        for _ in range(n):
            auditoria.registrar(
                db,
                Evento.LOGIN_FAILURE,
                ContextoRequisicao(ip="203.0.113.9", request_id=str(uuid.uuid4())),
                cpf_usuario_hash=os.urandom(32),
                resumo={"motivo": acao},
            )


def _ultimo_seq(db: Session) -> int:
    return db.scalar(select(func.max(Log.seq_cadeia))) or 0


def _modo_atacante(db: Session) -> None:
    db.execute(text("SET LOCAL session_replication_role = replica"))


# --- Cadeia íntegra ----------------------------------------------------------------------


def test_cadeia_integra_com_campos_variados(
    fabrica_sessao: sessionmaker[Session], settings_integracao: Settings, app_conn: Conn
) -> None:
    # Python e banco precisam serializar igual: NULL x vazio, unicode, IPv6, jsonb aninhado.
    with fabrica_sessao() as db, db.begin():
        auditoria.registrar(
            db,
            Evento.LOGIN_SUCCESS,
            ContextoRequisicao(ip="2001:db8::1", request_id=str(uuid.uuid4())),
            resumo={"z": [1, 2.5, None], "a": {"ç": "ãé✓"}, "vazio": ""},
        )
        auditoria.registrar(db, Evento.LOGOUT, ContextoRequisicao())
    app_conn.execute(
        "INSERT INTO app.log (acao, geolocalizacao, cpf_paciente_hash, id_oci, ip_origem)"
        " VALUES ('teste', '', %s, 42, '10.0.0.0/8')",
        (os.urandom(32),),
    )

    with fabrica_sessao() as db:
        resultado = _verificar(db, settings_integracao)
        total = db.scalar(select(func.count()).select_from(Log))
    assert resultado.integra, resultado
    assert resultado.registros == total
    assert resultado.ultimo is not None
    assert resultado.ultimo.seq_cadeia == total


def test_primeiro_registro_parte_do_genesis(fabrica_sessao: sessionmaker[Session]) -> None:
    _registrar(fabrica_sessao)
    with fabrica_sessao() as db:
        primeiro = db.scalars(select(Log).where(Log.seq_cadeia == 1)).one()
    assert primeiro.prev_hash == bytes(32)


def test_hashes_enviados_pelo_cliente_sao_ignorados(
    app_conn: Conn, fabrica_sessao: sessionmaker[Session], settings_integracao: Settings
) -> None:
    falso = os.urandom(32)
    row = app_conn.execute(
        "INSERT INTO app.log (acao, seq_cadeia, prev_hash, hash_assinatura_worm)"
        " VALUES ('teste', 999999, %s, %s) RETURNING seq_cadeia, prev_hash, hash_assinatura_worm",
        (falso, falso),
    ).fetchone()
    assert row is not None
    assert row[0] != 999999
    assert falso not in (row[1], row[2])
    with fabrica_sessao() as db:
        assert _verificar(db, settings_integracao).integra


def test_insercoes_concorrentes_mantem_cadeia_sem_lacunas(
    fabrica_sessao: sessionmaker[Session], settings_integracao: Settings
) -> None:
    with fabrica_sessao() as db:
        antes = _ultimo_seq(db)
    erros: list[BaseException] = []

    def trabalho() -> None:
        try:
            for _ in range(5):
                _registrar(fabrica_sessao, n=2)
        except BaseException as erro:  # pragma: no cover - só em falha
            erros.append(erro)

    threads = [threading.Thread(target=trabalho) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not erros

    with fabrica_sessao() as db:
        assert _ultimo_seq(db) >= antes + 60
        resultado = _verificar(db, settings_integracao)
    assert resultado.integra, resultado


def test_transacao_desfeita_nao_deixa_lacuna(
    fabrica_sessao: sessionmaker[Session], settings_integracao: Settings
) -> None:
    with fabrica_sessao() as db:
        antes = _ultimo_seq(db)
    with fabrica_sessao() as db:
        auditoria.registrar(db, Evento.LOGOUT, ContextoRequisicao())
        db.rollback()
    _registrar(fabrica_sessao)
    with fabrica_sessao() as db:
        assert _ultimo_seq(db) == antes + 1
        assert _verificar(db, settings_integracao).integra


# --- Adulterações detectadas ---------------------------------------------------------------


def test_registro_alterado_e_detectado(
    fabrica_sessao: sessionmaker[Session],
    settings_integracao: Settings,
    sessao_superusuario: Session,
) -> None:
    _registrar(fabrica_sessao, n=3)
    db = sessao_superusuario
    alvo = _ultimo_seq(db) - 1
    _modo_atacante(db)
    db.execute(text("UPDATE app.log SET acao = 'login_success' WHERE seq_cadeia = :s"), {"s": alvo})
    resultado = _verificar(db, settings_integracao)
    assert (resultado.motivo, resultado.seq_falha) == (Motivo.HASH, alvo)
    assert resultado.registros == alvo - 1


def test_registro_removido_do_meio_e_detectado(
    fabrica_sessao: sessionmaker[Session],
    settings_integracao: Settings,
    sessao_superusuario: Session,
) -> None:
    _registrar(fabrica_sessao, n=3)
    db = sessao_superusuario
    alvo = _ultimo_seq(db) - 1
    _modo_atacante(db)
    db.execute(text("DELETE FROM app.log WHERE seq_cadeia = :s"), {"s": alvo})
    resultado = _verificar(db, settings_integracao)
    assert (resultado.motivo, resultado.seq_falha) == (Motivo.LACUNA, alvo)


def test_registro_removido_e_seq_renumerada_e_detectado(
    fabrica_sessao: sessionmaker[Session],
    settings_integracao: Settings,
    sessao_superusuario: Session,
) -> None:
    _registrar(fabrica_sessao, n=3)
    db = sessao_superusuario
    alvo = _ultimo_seq(db) - 1
    _modo_atacante(db)
    db.execute(text("DELETE FROM app.log WHERE seq_cadeia = :s"), {"s": alvo})
    db.execute(
        text("UPDATE app.log SET seq_cadeia = seq_cadeia - 1 WHERE seq_cadeia > :s"), {"s": alvo}
    )
    resultado = _verificar(db, settings_integracao)
    assert (resultado.motivo, resultado.seq_falha) == (Motivo.PREV_HASH, alvo)


def test_registro_inserido_sem_trigger_e_detectado(
    settings_integracao: Settings, sessao_superusuario: Session
) -> None:
    db = sessao_superusuario
    ultimo = db.scalars(select(Log).order_by(Log.seq_cadeia.desc()).limit(1)).one()
    _modo_atacante(db)
    db.execute(
        text(
            "INSERT INTO app.log (acao, seq_cadeia, prev_hash, hash_assinatura_worm)"
            " VALUES ('login_success', :s, :p, :h)"
        ),
        {"s": ultimo.seq_cadeia + 1, "p": ultimo.hash_assinatura_worm, "h": os.urandom(32)},
    )
    resultado = _verificar(db, settings_integracao)
    assert (resultado.motivo, resultado.seq_falha) == (Motivo.HASH, ultimo.seq_cadeia + 1)


def test_fim_removido_sem_ancora_nao_e_detectado_pela_cadeia(
    fabrica_sessao: sessionmaker[Session],
    settings_integracao: Settings,
    sessao_superusuario: Session,
) -> None:
    # Limite conhecido (ADR-0010): é por isso que existem checkpoint e âncora.
    _registrar(fabrica_sessao, n=3)
    db = sessao_superusuario
    fim = _ultimo_seq(db)
    _modo_atacante(db)
    db.execute(text("DELETE FROM app.log WHERE seq_cadeia > :s"), {"s": fim - 2})
    assert _verificar(db, settings_integracao).integra


def test_fim_removido_e_detectado_pelo_checkpoint(
    fabrica_sessao: sessionmaker[Session],
    settings_integracao: Settings,
    sessao_superusuario: Session,
) -> None:
    _registrar(fabrica_sessao, n=3)
    db = sessao_superusuario
    resultado = _verificar(db, settings_integracao)
    ponto = cadeia_log.criar_checkpoint(
        db, _chave(settings_integracao), resultado, ContextoRequisicao()
    )
    assert ponto is not None
    _modo_atacante(db)
    db.execute(text("DELETE FROM app.log WHERE seq_cadeia > :s"), {"s": ponto.seq_cadeia - 2})
    resultado = _verificar(db, settings_integracao)
    assert (resultado.motivo, resultado.seq_falha) == (Motivo.TRUNCADO, ponto.seq_cadeia - 1)


def test_fim_removido_e_detectado_pela_ancora(
    fabrica_sessao: sessionmaker[Session],
    settings_integracao: Settings,
    sessao_superusuario: Session,
) -> None:
    _registrar(fabrica_sessao, n=3)
    db = sessao_superusuario
    ancora = _verificar(db, settings_integracao).ultimo
    assert ancora is not None
    _modo_atacante(db)
    db.execute(text("DELETE FROM app.log WHERE seq_cadeia = :s"), {"s": ancora.seq_cadeia})
    resultado = _verificar(db, settings_integracao, ancora)
    assert resultado.motivo == Motivo.TRUNCADO


def test_ancora_divergente_e_detectada(
    fabrica_sessao: sessionmaker[Session], settings_integracao: Settings
) -> None:
    _registrar(fabrica_sessao)
    with fabrica_sessao() as db:
        ancora = Ancora(_ultimo_seq(db), os.urandom(32))
        resultado = _verificar(db, settings_integracao, ancora)
    assert (resultado.motivo, resultado.seq_falha) == (Motivo.ANCORA_DIVERGENTE, ancora.seq_cadeia)


def test_cadeia_recalculada_por_atacante_e_detectada_pelo_checkpoint(
    fabrica_sessao: sessionmaker[Session],
    settings_integracao: Settings,
    sessao_superusuario: Session,
) -> None:
    _registrar(fabrica_sessao, n=3)
    db = sessao_superusuario
    resultado = _verificar(db, settings_integracao)
    ponto = cadeia_log.criar_checkpoint(
        db, _chave(settings_integracao), resultado, ContextoRequisicao()
    )
    assert ponto is not None
    alvo = ponto.seq_cadeia - 2
    _modo_atacante(db)
    db.execute(text("UPDATE app.log SET acao = 'login_success' WHERE seq_cadeia = :s"), {"s": alvo})
    # Atacante recalcula a cadeia a partir do registro alterado (com a função do próprio banco).
    prev = db.scalar(select(Log.prev_hash).where(Log.seq_cadeia == alvo))
    for seq in range(alvo, _ultimo_seq(db) + 1):
        prev = db.scalar(
            text(
                "UPDATE app.log l SET prev_hash = :p, hash_assinatura_worm ="
                " app.log_calcular_hash(:p, l) WHERE seq_cadeia = :s"
                " RETURNING hash_assinatura_worm"
            ),
            {"p": prev, "s": seq},
        )
    resultado = _verificar(db, settings_integracao)
    assert (resultado.motivo, resultado.seq_falha) == (
        Motivo.CHECKPOINT_DIVERGENTE,
        ponto.seq_cadeia,
    )


def test_checkpoint_forjado_sem_a_chave_e_detectado(
    fabrica_sessao: sessionmaker[Session],
    settings_integracao: Settings,
    sessao_superusuario: Session,
) -> None:
    _registrar(fabrica_sessao)
    db = sessao_superusuario
    ponto = _verificar(db, settings_integracao).ultimo
    assert ponto is not None
    outra_chave = os.urandom(32)
    db.add(
        LogCheckpoint(
            seq_cadeia=ponto.seq_cadeia,
            hash_cadeia=ponto.hash_cadeia,
            assinatura=assinar_checkpoint(outra_chave, ponto.seq_cadeia, ponto.hash_cadeia),
        )
    )
    db.flush()
    resultado = _verificar(db, settings_integracao)
    assert (resultado.motivo, resultado.seq_falha) == (
        Motivo.CHECKPOINT_ASSINATURA,
        ponto.seq_cadeia,
    )


# --- Checkpoints e auditoria da verificação ------------------------------------------------


def test_checkpoint_gravado_e_auditado(
    fabrica_sessao: sessionmaker[Session], settings_integracao: Settings
) -> None:
    _registrar(fabrica_sessao)
    with fabrica_sessao() as db:
        resultado = _verificar(db, settings_integracao)
    with fabrica_sessao() as db, db.begin():
        cadeia_log.registrar_resultado(db, resultado, ContextoRequisicao())
        ponto = cadeia_log.criar_checkpoint(
            db, _chave(settings_integracao), resultado, ContextoRequisicao()
        )
    assert ponto is not None
    with fabrica_sessao() as db:
        eventos = db.scalars(
            select(Log).where(Log.seq_cadeia > ponto.seq_cadeia).order_by(Log.seq_cadeia)
        ).all()
        depois = _verificar(db, settings_integracao)
    assert [e.acao for e in eventos[:2]] == ["log_chain_verified", "log_checkpoint_created"]
    assert eventos[1].resumo_acessado == {"seq": ponto.seq_cadeia}
    assert depois.integra
    assert depois.checkpoints == resultado.checkpoints + 1


def test_checkpoint_nunca_gravado_sobre_cadeia_quebrada(
    fabrica_sessao: sessionmaker[Session], settings_integracao: Settings
) -> None:
    quebrada = ResultadoVerificacao(3, 0, None, Motivo.HASH, 4)
    with fabrica_sessao() as db, db.begin():
        assert (
            cadeia_log.criar_checkpoint(
                db, _chave(settings_integracao), quebrada, ContextoRequisicao()
            )
            is None
        )
        cadeia_log.registrar_resultado(db, quebrada, ContextoRequisicao())
        evento = db.scalars(select(Log).order_by(Log.seq_cadeia.desc()).limit(1)).one()
    assert evento.acao == "log_chain_broken"
    assert evento.resumo_acessado == {
        "motivo": "hash_divergente",
        "seq": 4,
        "registros_verificados": 3,
    }


def test_checkpoint_e_worm(app_conn: Conn, migrator_conn: Conn) -> None:
    for comando in (
        "UPDATE app.log_checkpoint SET seq_cadeia = 1",
        "DELETE FROM app.log_checkpoint",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app_conn.execute(comando)
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="append-only"):
        migrator_conn.execute("TRUNCATE app.log_checkpoint")


def test_checkpoint_exige_posicao_existente(app_conn: Conn) -> None:
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        app_conn.execute(
            "INSERT INTO app.log_checkpoint (seq_cadeia, hash_cadeia, assinatura)"
            " VALUES (%s, %s, %s)",
            (10**12, os.urandom(32), os.urandom(32)),
        )


# --- Registros anteriores à cadeia (migration 0005) --------------------------------------


def test_migration_encadeia_registros_existentes() -> None:
    with banco_temporario("0004") as banco:
        _popular_log_antigo(banco)
        migrar(banco, "head")
        with _conectar_app(banco) as conn:
            linhas = conn.execute(
                "SELECT id_log, seq_cadeia FROM app.log ORDER BY id_log"
            ).fetchall()
            assert [s for _, s in linhas] == [1, 2, 3]
            conn.execute("INSERT INTO app.log (acao) VALUES ('depois_da_migration')")
        settings = Settings(
            environment="test",
            postgres_db=banco.name,
            app_db_password=os.environ["APP_DB_PASSWORD"],
            db_host=banco.host,
            db_port=banco.port,
            kek_keyring=f"1:{gerar_chave_b64()}",
            kek_ativa=1,
            hmac_key=gerar_chave_b64(),
            log_checkpoint_key=gerar_chave_b64(),
            bcrypt_rounds=4,
        )
        engine = criar_engine(settings)
        try:
            with criar_sessionmaker(engine)() as db:
                resultado = _verificar(db, settings)
        finally:
            engine.dispose()
        assert resultado.integra, resultado
        assert resultado.registros == 4


def _conectar_app(banco: BancoTeste) -> Conn:
    return banco.connect(APP_DB_ROLE, os.environ["APP_DB_PASSWORD"])


def _popular_log_antigo(banco: BancoTeste) -> None:
    with _conectar_app(banco) as conn:
        conn.execute(
            "INSERT INTO app.log (acao, ip_origem, cpf_usuario_hash, resumo_acessado)"
            " VALUES ('login_failure', '203.0.113.1', %s, '{\"motivo\": \"senha_invalida\"}')",
            (os.urandom(32),),
        )
        conn.execute("INSERT INTO app.log (acao) VALUES ('login_success')")
        conn.execute("INSERT INTO app.log (acao, geolocalizacao) VALUES ('logout', 'Recife')")


# --- Script de verificação ---------------------------------------------------------------


def _rodar_script(monkeypatch: pytest.MonkeyPatch, settings: Settings, argv: list[str]) -> None:
    from scripts import verificar_log

    monkeypatch.setattr(verificar_log, "get_settings", lambda: settings)
    verificar_log.main(argv)


def test_script_verifica_grava_checkpoint_e_imprime_ancora(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fabrica_sessao: sessionmaker[Session],
    settings_integracao: Settings,
) -> None:
    _registrar(fabrica_sessao)
    _rodar_script(monkeypatch, settings_integracao, ["--checkpoint"])
    saida = capsys.readouterr().out
    assert "Cadeia íntegra" in saida
    assert "Checkpoint assinado gravado" in saida
    ancora = saida.split("Âncora (guarde fora do sistema): ")[1].split()[0]

    # A âncora impressa serve para a próxima verificação.
    _rodar_script(monkeypatch, settings_integracao, ["--ancora", ancora])
    assert "Cadeia íntegra" in capsys.readouterr().out


def test_script_sai_com_erro_se_cadeia_quebrada(
    monkeypatch: pytest.MonkeyPatch,
    fabrica_sessao: sessionmaker[Session],
    settings_integracao: Settings,
) -> None:
    quebrada = ResultadoVerificacao(3, 0, None, Motivo.LACUNA, 4)
    monkeypatch.setattr(cadeia_log, "verificar_cadeia", lambda *_a, **_k: quebrada)
    with pytest.raises(SystemExit, match="CADEIA QUEBRADA: lacuna_na_sequencia na posição 4"):
        _rodar_script(monkeypatch, settings_integracao, ["--checkpoint"])
    with fabrica_sessao() as db:
        ultimo = db.scalars(select(Log).order_by(Log.seq_cadeia.desc()).limit(1)).one()
    assert ultimo.acao == "log_chain_broken"


@pytest.mark.parametrize(
    ("argv", "esperado"), [(["--ancora", "invalida"], "seq:hash_hex"), ([], "LOG_CHECKPOINT_KEY")]
)
def test_script_recusa_ancora_invalida_ou_falta_de_chave(
    monkeypatch: pytest.MonkeyPatch, settings_integracao: Settings, argv: list[str], esperado: str
) -> None:
    sem_chave = settings_integracao.model_copy(update={"log_checkpoint_key": None})
    sem_chave.__dict__.pop("chave_checkpoint", None)
    with pytest.raises(SystemExit, match=esperado):
        _rodar_script(monkeypatch, sem_chave, argv)
