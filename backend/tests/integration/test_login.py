"""RF-02 etapa 1 / THREAT_MODEL S1, S2, S4, I5: login por CPF + senha."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core import senha as senha_mod
from app.core.config import Settings
from app.models import Log, Sessao, Usuario
from app.services import auth as auth_service
from app.services import usuario as usuario_service
from app.services.auditoria import ContextoRequisicao
from app.services.sessao import hash_token
from app.services.usuario import NovoUsuario

from .conftest import gerar_cpf

SENHA = "Saúde#Recife2026"
FALHA = {"detail": "CPF ou senha inválidos."}
CTX = ContextoRequisicao(ip="203.0.113.9")


@pytest.fixture
def usuario(fabrica_sessao: sessionmaker[Session], settings_integracao: Settings) -> str:
    cpf = gerar_cpf()
    dados = NovoUsuario(cpf=cpf, nome="Ana", email=f"a{cpf}@recife.pe.gov.br", senha=SENHA)
    with fabrica_sessao() as db, db.begin():
        usuario_service.cadastrar(db, settings_integracao, dados, ContextoRequisicao())
    return cpf


def _usuario(fabrica: sessionmaker[Session], settings: Settings, cpf: str) -> Usuario:
    from app.core.crypto import FinalidadeHash, hash_busca

    with fabrica() as db:
        return db.get_one(Usuario, hash_busca(settings.chave_hmac, FinalidadeHash.CPF, cpf))


def _eventos(fabrica: sessionmaker[Session], cpf_hash: bytes) -> list[Log]:
    with fabrica() as db:
        consulta = select(Log).where(Log.cpf_usuario_hash == cpf_hash).order_by(Log.id_log)
        return list(db.scalars(consulta))


def _login(api: TestClient, cpf: str, senha: str = SENHA) -> tuple[int, dict[str, str]]:
    resp = api.post("/auth/login", json={"cpf": cpf, "senha": senha})
    return resp.status_code, resp.json()


# --- Sucesso -----------------------------------------------------------------------------


def test_login_valido_pede_mfa_e_entrega_cookie_seguro(
    api: TestClient,
    usuario: str,
    fabrica_sessao: sessionmaker[Session],
    settings_integracao: Settings,
) -> None:
    resp = api.post("/auth/login", json={"cpf": usuario, "senha": SENHA})
    assert resp.status_code == 200
    assert resp.json() == {"etapa": "mfa_cadastro"}  # 1º acesso: MFA ainda não ativado
    assert resp.headers["cache-control"] == "no-store"

    set_cookie = resp.headers["set-cookie"]
    for atributo in ("HttpOnly", "Secure", "SameSite=strict", "Path=/auth/mfa", "Max-Age=300"):
        assert atributo in set_cookie
    token = resp.cookies["pre_auth"]
    assert len(token) >= 43

    u = _usuario(fabrica_sessao, settings_integracao, usuario)
    with fabrica_sessao() as db:
        sessao = db.get_one(Sessao, hash_token(token))
    assert sessao.cpf_hash == u.cpf_hash
    assert sessao.escopo == "mfa"
    assert timedelta(minutes=4) < sessao.expira_em - datetime.now(UTC) <= timedelta(minutes=5)
    assert [e.acao for e in _eventos(fabrica_sessao, u.cpf_hash)][-1] == "login_success"


def test_login_aceita_cpf_com_mascara(api: TestClient, usuario: str) -> None:
    mascarado = f"{usuario[:3]}.{usuario[3:6]}.{usuario[6:9]}-{usuario[9:]}"
    assert _login(api, mascarado)[0] == 200


def test_sessao_nao_guarda_token_em_claro(
    api: TestClient, usuario: str, fabrica_sessao: sessionmaker[Session]
) -> None:
    resp = api.post("/auth/login", json={"cpf": usuario, "senha": SENHA})
    token = resp.cookies["pre_auth"].encode()
    with fabrica_sessao() as db:
        assert all(token not in s.token_hash for s in db.scalars(select(Sessao)))


# --- Falhas e enumeração -----------------------------------------------------------------


def test_respostas_identicas_para_senha_errada_e_cpf_inexistente(
    api: TestClient, usuario: str
) -> None:
    assert _login(api, usuario, "Errada#Senha2026") == (401, FALHA)
    assert _login(api, gerar_cpf()) == (401, FALHA)


def test_cpf_inexistente_executa_bcrypt_ficticio(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    chamadas: list[int] = []
    original = senha_mod.verificar_ficticio

    def espiao(senha: str, rounds: int) -> None:
        chamadas.append(rounds)
        original(senha, rounds)

    monkeypatch.setattr(senha_mod, "verificar_ficticio", espiao)
    assert _login(api, gerar_cpf())[0] == 401
    assert chamadas == [4]


def test_falha_conta_e_audita_sem_dado_sensivel(
    api: TestClient,
    usuario: str,
    fabrica_sessao: sessionmaker[Session],
    settings_integracao: Settings,
) -> None:
    _login(api, usuario, "Errada#Senha2026")
    u = _usuario(fabrica_sessao, settings_integracao, usuario)
    assert u.falhas_login == 1
    evento = _eventos(fabrica_sessao, u.cpf_hash)[-1]
    assert evento.acao == "login_failure"
    assert evento.resumo_acessado == {"motivo": "senha_invalida"}
    assert evento.request_id is not None
    texto = str(evento.resumo_acessado)
    assert usuario not in texto and "Errada" not in texto


def test_conta_inativa_recusada_com_mesma_resposta(
    api: TestClient,
    usuario: str,
    fabrica_sessao: sessionmaker[Session],
    settings_integracao: Settings,
) -> None:
    u = _usuario(fabrica_sessao, settings_integracao, usuario)
    with fabrica_sessao() as db, db.begin():
        db.get_one(Usuario, u.cpf_hash).status = "inativo"
    assert _login(api, usuario) == (401, FALHA)
    assert _eventos(fabrica_sessao, u.cpf_hash)[-1].resumo_acessado == {"motivo": "conta_inativo"}


# --- Bloqueio progressivo ----------------------------------------------------------------


def test_cinco_falhas_bloqueiam_ate_a_senha_correta(
    api: TestClient,
    usuario: str,
    fabrica_sessao: sessionmaker[Session],
    settings_integracao: Settings,
) -> None:
    for _ in range(5):
        assert _login(api, usuario, "Errada#Senha2026") == (401, FALHA)

    u = _usuario(fabrica_sessao, settings_integracao, usuario)
    assert u.bloqueios == 1 and u.falhas_login == 0
    assert u.bloqueado_ate is not None
    restante = u.bloqueado_ate - datetime.now(UTC)
    assert timedelta(minutes=14) < restante <= timedelta(minutes=15)

    assert _login(api, usuario) == (401, FALHA)  # senha certa, mas bloqueada
    acoes = [e.acao for e in _eventos(fabrica_sessao, u.cpf_hash)]
    assert "account_locked" in acoes
    assert _eventos(fabrica_sessao, u.cpf_hash)[-1].resumo_acessado == {
        "motivo": "conta_bloqueada_temporariamente"
    }


def _autenticar(
    fabrica: sessionmaker[Session], settings: Settings, cpf: str, senha: str, agora: datetime
) -> bool:
    with fabrica() as db, db.begin():
        return auth_service.autenticar_senha(
            db, settings, cpf=cpf, senha=senha, ctx=CTX, agora=agora
        ).sucesso


def test_bloqueio_dobra_e_expira_e_sucesso_zera_contadores(
    usuario: str, fabrica_sessao: sessionmaker[Session], settings_integracao: Settings
) -> None:
    agora = datetime.now(UTC)
    for _ in range(5):
        _autenticar(fabrica_sessao, settings_integracao, usuario, "Errada#1aaaa", agora)
    agora += timedelta(minutes=16)  # 1º bloqueio (15 min) expirou
    for _ in range(5):
        _autenticar(fabrica_sessao, settings_integracao, usuario, "Errada#1aaaa", agora)
    u = _usuario(fabrica_sessao, settings_integracao, usuario)
    assert u.bloqueios == 2
    assert u.bloqueado_ate == agora + timedelta(minutes=30)

    assert not _autenticar(fabrica_sessao, settings_integracao, usuario, SENHA, agora)
    agora += timedelta(minutes=31)
    assert _autenticar(fabrica_sessao, settings_integracao, usuario, SENHA, agora)
    u = _usuario(fabrica_sessao, settings_integracao, usuario)
    assert (u.falhas_login, u.bloqueios, u.bloqueado_ate) == (0, 0, None)


def test_rehash_quando_custo_aumenta(
    usuario: str, fabrica_sessao: sessionmaker[Session], settings_integracao: Settings
) -> None:
    mais_caro = settings_integracao.model_copy(update={"bcrypt_rounds": 5})
    assert _autenticar(fabrica_sessao, mais_caro, usuario, SENHA, datetime.now(UTC))
    assert _usuario(fabrica_sessao, settings_integracao, usuario).senha_hash.startswith("$2b$05$")
