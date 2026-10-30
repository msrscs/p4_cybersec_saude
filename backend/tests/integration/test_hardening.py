"""T09 / THREAT_MODEL S2, S3, D1, I3: CSRF, limite por IP, headers, limpeza e TLS do banco."""

import itertools
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import psycopg
import pyotp
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core import totp
from app.core.config import Settings
from app.main import create_app
from app.models import LimiteRequisicao, Log, Sessao
from app.services import autorizacao, manutencao
from app.services import usuario as usuario_service
from app.services.auditoria import ContextoRequisicao
from app.services.limite import inicio_da_janela
from app.services.sessao import hash_token
from app.services.usuario import NovoUsuario

from .conftest import BancoTeste, com_csrf, gerar_cpf

SENHA = "Saúde#Recife2026"
Fabrica = sessionmaker[Session]


_PROXIMO_IP = itertools.count(1)


def _ip() -> str:
    # Sequencial (não aleatório): dois testes nunca dividem o mesmo contador de limite.
    n = next(_PROXIMO_IP)
    return f"198.51.{100 + n // 250}.{n % 250 + 1}"


def _cliente(app: FastAPI, ip: str | None = None) -> TestClient:
    return TestClient(app, base_url="https://testserver", client=(ip or _ip(), 50000))


def _logado(
    app: FastAPI, fabrica: Fabrica, settings: Settings, ip: str | None = None
) -> TestClient:
    cpf = gerar_cpf()
    dados = NovoUsuario(cpf=cpf, nome="Rui", email=f"r{cpf}@recife.pe.gov.br", senha=SENHA)
    with fabrica() as db, db.begin():
        usuario_service.cadastrar(db, settings, dados, ContextoRequisicao())
        autorizacao.alterar_grupo(
            db, settings, cpf=cpf, grupo="Administrador", remover=False, ctx=ContextoRequisicao()
        )
    api = _cliente(app, ip)
    assert api.post("/auth/login", json={"cpf": cpf, "senha": SENHA}).status_code == 200
    uri = api.post("/auth/mfa/cadastro").json()["otpauth_uri"]
    segredo = parse_qs(urlparse(uri).query)["secret"][0]
    codigo = pyotp.TOTP(segredo).at(totp.passo(datetime.now(UTC)) * 30)
    assert api.post("/auth/mfa/ativar", json={"codigo": codigo}).status_code == 200
    return api


def _ultimo(fabrica: Fabrica, acao: str) -> Log:
    with fabrica() as db:
        return db.scalars(
            select(Log).where(Log.acao == acao).order_by(Log.seq_cadeia.desc()).limit(1)
        ).one()


# --- CSRF (S3) ---------------------------------------------------------------------------


def test_rotas_que_alteram_dados_exigem_token_csrf(
    app_teste: FastAPI, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    api = _logado(app_teste, fabrica_sessao, settings_integracao)
    novo = {"cpf": gerar_cpf(), "nome": "Ana Paula", "data_nascimento": "1990-01-01"}

    assert api.get("/auth/sessao").status_code == 200  # leitura não exige token
    sem = api.post("/pacientes", json=novo)
    assert sem.status_code == 403
    assert sem.json() == {"detail": "Requisição recusada."}
    evento = _ultimo(fabrica_sessao, "csrf_rejected")
    assert evento.resumo_acessado == {
        "metodo": "POST",
        "rota": "/pacientes",
        "token_enviado": False,
    }

    api.headers["X-CSRF-Token"] = "0" * 64
    assert api.post("/pacientes", json=novo).status_code == 403
    assert api.post("/auth/logout").status_code == 403  # logout também

    com_csrf(api)
    assert api.post("/pacientes", json=novo).status_code == 201


def test_token_csrf_de_outra_sessao_nao_vale(
    app_teste: FastAPI, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    a = com_csrf(_logado(app_teste, fabrica_sessao, settings_integracao))
    b = com_csrf(_logado(app_teste, fabrica_sessao, settings_integracao))
    assert a.headers["X-CSRF-Token"] != b.headers["X-CSRF-Token"]
    b.headers["X-CSRF-Token"] = a.headers["X-CSRF-Token"]
    assert b.post("/auth/logout").status_code == 403
    assert a.post("/auth/logout").status_code == 204


def test_token_csrf_nao_revela_o_token_de_sessao(
    app_teste: FastAPI, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    api = com_csrf(_logado(app_teste, fabrica_sessao, settings_integracao))
    token_sessao = api.cookies["__Host-sessao"]
    csrf = api.headers["X-CSRF-Token"]
    assert token_sessao not in csrf
    assert hash_token(token_sessao).hex() != csrf


# --- Limite de requisições por IP (S2, D1) -----------------------------------------------


@pytest.fixture(scope="module")
def app_com_limite(settings_integracao: Settings) -> Iterator[FastAPI]:
    settings = Settings(**{**settings_integracao.model_dump(), "limite_requisicoes_ativo": True})
    app = create_app(settings)
    yield app
    app.state.engine.dispose()


def test_login_limitado_por_ip_com_retry_after(
    app_com_limite: FastAPI, fabrica_sessao: Fabrica
) -> None:
    ip = _ip()
    api = _cliente(app_com_limite, ip)
    corpo = {"cpf": gerar_cpf(), "senha": "Qualquer#Senha1"}
    for _ in range(10):
        assert api.post("/auth/login", json=corpo).status_code == 401
    for _ in range(3):
        resp = api.post("/auth/login", json=corpo)
        assert resp.status_code == 429
        assert resp.json() == {"detail": "Muitas requisições. Tente novamente mais tarde."}
        assert 1 <= int(resp.headers["retry-after"]) <= 60

    with fabrica_sessao() as db:
        eventos = db.scalars(
            select(Log).where(Log.acao == "rate_limited", Log.ip_origem == ip)
        ).all()
    assert len(eventos) == 1  # auditado uma vez por janela, sem inundar o log
    assert eventos[0].resumo_acessado == {"grupo": "login:60", "maximo": 10}

    # Outro IP não é afetado.
    assert _cliente(app_com_limite).post("/auth/login", json=corpo).status_code == 401


def test_tentativas_invalidas_tambem_contam(app_com_limite: FastAPI) -> None:
    api = _cliente(app_com_limite)
    for _ in range(10):
        assert api.post("/auth/login", json={"cpf": "1", "senha": "x"}).status_code == 422
    assert api.post("/auth/login", json={"cpf": "1", "senha": "x"}).status_code == 429


def test_mfa_limitado_por_ip(app_com_limite: FastAPI) -> None:
    api = _cliente(app_com_limite)
    for _ in range(15):
        assert api.post("/auth/mfa/verificar", json={"codigo": "123456"}).status_code == 401
    assert api.post("/auth/mfa/verificar", json={"codigo": "123456"}).status_code == 429


def test_busca_de_pacientes_limitada_contra_varredura(
    app_com_limite: FastAPI, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    api = com_csrf(_logado(app_com_limite, fabrica_sessao, settings_integracao))
    for _ in range(30):
        assert api.post("/pacientes/busca", json={"cpf": gerar_cpf()}).status_code == 404
    assert api.post("/pacientes/busca", json={"cpf": gerar_cpf()}).status_code == 429
    assert api.get(f"/pacientes/{uuid.uuid4()}").status_code == 404  # outras rotas seguem


def test_lista_de_pacientes_limitada_contra_extracao_em_massa(
    app_com_limite: FastAPI, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    api = com_csrf(_logado(app_com_limite, fabrica_sessao, settings_integracao))
    for _ in range(30):
        assert api.post("/pacientes/lista", json={}).status_code == 200
    resp = api.post("/pacientes/lista", json={})
    assert resp.status_code == 429
    assert "retry-after" in resp.headers


def test_janela_fixa() -> None:
    agora = datetime(2026, 10, 29, 12, 34, 56, tzinfo=UTC)
    assert inicio_da_janela(agora, timedelta(minutes=1)) == agora.replace(second=0)
    assert inicio_da_janela(agora, timedelta(hours=1)) == agora.replace(minute=0, second=0)


# --- Headers da API ----------------------------------------------------------------------


def test_headers_de_seguranca_na_api(api: TestClient) -> None:
    resp = api.get("/health")
    assert resp.headers["content-security-policy"].startswith("default-src 'none'")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert resp.headers["cache-control"] == "no-store"
    erro = api.post("/auth/login", json={})
    assert erro.headers["content-security-policy"].startswith("default-src 'none'")


# --- Limpeza periódica -------------------------------------------------------------------


def test_limpeza_remove_sessoes_e_contadores_vencidos(
    app_teste: FastAPI, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    api = _logado(app_teste, fabrica_sessao, settings_integracao)
    viva = hash_token(api.cookies["__Host-sessao"])
    agora = datetime.now(UTC)
    with fabrica_sessao() as db, db.begin():
        db.add(LimiteRequisicao(grupo="login:60", ip="192.0.2.1", janela=agora - timedelta(days=2)))
        db.add(LimiteRequisicao(grupo="login:60", ip="192.0.2.1", janela=agora))
    with fabrica_sessao() as db, db.begin():
        # Simula o relógio 9 h à frente: a sessão passou da vida máxima de 8 h.
        resultado = manutencao.limpar(db, agora + timedelta(hours=9))
    assert resultado.sessoes >= 1
    assert resultado.contadores >= 1
    with fabrica_sessao() as db:
        assert db.get(Sessao, viva) is None
        restantes = db.scalar(
            select(func.count())
            .select_from(LimiteRequisicao)
            .where(LimiteRequisicao.ip == "192.0.2.1")
        )
    assert restantes == 1


def test_script_de_tarefas(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings_integracao: Settings,
) -> None:
    from scripts import tarefas

    monkeypatch.setattr(tarefas, "get_settings", lambda: settings_integracao)
    tarefas.main(["limpar"])
    assert "Limpeza:" in capsys.readouterr().out
    tarefas.main(["verificar-log"])
    saida = capsys.readouterr().out
    assert "Cadeia íntegra" in saida and "Âncora:" in saida


def test_script_de_tarefas_sem_chave_de_checkpoint(
    monkeypatch: pytest.MonkeyPatch, settings_integracao: Settings
) -> None:
    from scripts import tarefas

    sem_chave = Settings(**{**settings_integracao.model_dump(), "log_checkpoint_key": None})
    monkeypatch.setattr(tarefas, "get_settings", lambda: sem_chave)
    with pytest.raises(SystemExit):
        tarefas.main(["verificar-log"])


# --- TLS até o banco (I3) ----------------------------------------------------------------

exige_tls = pytest.mark.skipif(
    os.environ.get("DB_SSLMODE", "verify-full") != "verify-full",
    reason="banco sem TLS neste ambiente",
)


@exige_tls
def test_aplicacao_conecta_ao_banco_com_tls(fabrica_sessao: Fabrica) -> None:
    with fabrica_sessao() as db:
        linha = db.execute(
            text("SELECT ssl, version FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
        ).one()
    assert linha.ssl is True
    assert linha.version in ("TLSv1.2", "TLSv1.3")


@exige_tls
def test_banco_recusa_conexao_sem_tls(test_db: BancoTeste) -> None:
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(
            make_conninfo(sslmode="disable"),
            user="app_user",
            password=os.environ["APP_DB_PASSWORD"],
            dbname=test_db.name,
            host=test_db.host,
            port=test_db.port,
        )
