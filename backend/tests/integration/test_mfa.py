"""RF-02 / THREAT_MODEL S1, S3, S4, S5: MFA TOTP, códigos de recuperação e sessão completa."""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core import totp
from app.core.config import Settings
from app.core.crypto import FinalidadeHash, hash_busca
from app.models import CodigoRecuperacao, Log, Sessao, Usuario
from app.repositories import codigo_recuperacao as codigo_repo
from app.services import mfa as mfa_service
from app.services import sessao as sessao_svc
from app.services import usuario as usuario_service
from app.services.auditoria import ContextoRequisicao
from app.services.sessao import hash_token
from app.services.usuario import NovoUsuario

from .conftest import gerar_cpf

SENHA = "Saúde#Recife2026"
CTX = ContextoRequisicao(ip="203.0.113.10")
Fabrica = sessionmaker[Session]


# --- Apoio -------------------------------------------------------------------------------


@pytest.fixture
def cpf(fabrica_sessao: Fabrica, settings_integracao: Settings) -> str:
    cpf = gerar_cpf()
    dados = NovoUsuario(cpf=cpf, nome="Bia", email=f"b{cpf}@recife.pe.gov.br", senha=SENHA)
    with fabrica_sessao() as db, db.begin():
        usuario_service.cadastrar(db, settings_integracao, dados, ContextoRequisicao())
    return cpf


def _cpf_hash(settings: Settings, cpf: str) -> bytes:
    return hash_busca(settings.chave_hmac, FinalidadeHash.CPF, cpf)


def _usuario(fabrica: Fabrica, settings: Settings, cpf: str) -> Usuario:
    with fabrica() as db:
        return db.get_one(Usuario, _cpf_hash(settings, cpf))


def _codigo(segredo: str, deslocamento: int = 0) -> str:
    return pyotp.TOTP(segredo).at((totp.passo(datetime.now(UTC)) + deslocamento) * 30)


def _entrar(api: TestClient, cpf: str, senha: str = SENHA) -> str:
    resp = api.post("/auth/login", json={"cpf": cpf, "senha": senha})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["etapa"])


def _ativar(api: TestClient, cpf: str) -> tuple[str, list[str]]:
    """1º acesso completo pela API; devolve o segredo TOTP e os códigos de recuperação."""
    assert _entrar(api, cpf) == "mfa_cadastro"
    prov = api.post("/auth/mfa/cadastro").json()
    segredo = parse_qs(urlparse(prov["otpauth_uri"]).query)["secret"][0]
    resp = api.post("/auth/mfa/ativar", json={"codigo": _codigo(segredo)})
    assert resp.status_code == 200, resp.text
    return segredo, resp.json()["codigos_recuperacao"]


# --- Primeiro acesso (cadastro do MFA) ---------------------------------------------------


def test_primeiro_acesso_exige_cadastro_e_abre_sessao(
    api: TestClient, cpf: str, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    assert _entrar(api, cpf) == "mfa_cadastro"
    assert api.get("/auth/sessao").status_code == 401  # pré-auth não é sessão

    prov = api.post("/auth/mfa/cadastro")
    assert prov.status_code == 200
    assert prov.headers["cache-control"] == "no-store"
    corpo = prov.json()
    assert corpo["qr_svg"].startswith("<svg")
    segredo = corpo["chave"]
    assert parse_qs(urlparse(corpo["otpauth_uri"]).query)["secret"] == [segredo]

    u = _usuario(fabrica_sessao, settings_integracao, cpf)
    assert u.totp_segredo_cripto is not None and segredo.encode() not in u.totp_segredo_cripto
    assert not u.mfa_ativo

    assert api.post("/auth/mfa/ativar", json={"codigo": "000000"}).json() == {
        "detail": "Código inválido."
    }
    resp = api.post("/auth/mfa/ativar", json={"codigo": _codigo(segredo)})
    assert resp.status_code == 200
    codigos = resp.json()["codigos_recuperacao"]
    assert len(codigos) == 10 and len(set(codigos)) == 10

    set_cookie = resp.headers.get_list("set-cookie")
    sessao_cookie = next(c for c in set_cookie if c.startswith("__Host-sessao="))
    for atributo in ("HttpOnly", "Secure", "SameSite=strict", "Path=/"):
        assert atributo in sessao_cookie
    assert "Max-Age" not in sessao_cookie and "Domain" not in sessao_cookie
    assert any(c.startswith("pre_auth=") and "Max-Age=0" in c for c in set_cookie)

    sessao = api.get("/auth/sessao")
    assert sessao.status_code == 200
    assert sessao.json()["troca_senha_obrigatoria"] is False
    assert _usuario(fabrica_sessao, settings_integracao, cpf).mfa_ativo


def test_cadastro_exige_pre_auth_valida(api: TestClient, cpf: str) -> None:
    assert api.post("/auth/mfa/cadastro").status_code == 401
    api.cookies.set("pre_auth", "token-inventado", domain="testserver.local", path="/auth/mfa")
    assert api.post("/auth/mfa/cadastro").status_code == 401


def test_mfa_ativo_nao_pode_ser_recadastrado(api: TestClient, cpf: str) -> None:
    _ativar(api, cpf)
    assert _entrar(api, cpf) == "mfa"
    assert api.post("/auth/mfa/cadastro").status_code == 401
    assert api.post("/auth/mfa/ativar", json={"codigo": "123456"}).status_code == 401


def test_pre_auth_expirada_e_recusada(
    cpf: str, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    agora = datetime.now(UTC)
    with fabrica_sessao() as db, db.begin():
        token = sessao_svc.criar_pre_auth(db, _cpf_hash(settings_integracao, cpf), CTX, agora)
    with fabrica_sessao() as db, db.begin(), pytest.raises(mfa_service.PreAuthInvalida):
        mfa_service.iniciar_cadastro(db, settings_integracao, token, agora + timedelta(minutes=6))


# --- Verificação TOTP --------------------------------------------------------------------


def test_login_com_totp_e_reuso_do_codigo_recusado(api: TestClient, cpf: str) -> None:
    segredo, _ = _ativar(api, cpf)
    codigo = _codigo(segredo, 1)  # passo seguinte ao usado na ativação

    assert _entrar(api, cpf) == "mfa"
    assert api.post("/auth/mfa/verificar", json={"codigo": codigo}).json() == {
        "autenticado": True,
        "codigos_restantes": None,
    }
    assert api.get("/auth/sessao").status_code == 200

    assert _entrar(api, cpf) == "mfa"
    assert api.post("/auth/mfa/verificar", json={"codigo": codigo}).status_code == 401


def test_cinco_codigos_errados_invalidam_token_e_bloqueiam_conta(
    api: TestClient, cpf: str, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    segredo, _ = _ativar(api, cpf)
    _entrar(api, cpf)
    for _ in range(5):
        resp = api.post("/auth/mfa/verificar", json={"codigo": "000000"})
        assert resp.json() == {"detail": "Código inválido."}
    resp = api.post("/auth/mfa/verificar", json={"codigo": _codigo(segredo, 1)})
    assert resp.status_code == 401
    assert "Entre novamente" in resp.json()["detail"]

    u = _usuario(fabrica_sessao, settings_integracao, cpf)
    assert u.bloqueios == 1 and u.bloqueado_ate is not None
    assert api.post("/auth/login", json={"cpf": cpf, "senha": SENHA}).status_code == 401


def test_codigo_com_formato_invalido_e_422(api: TestClient, cpf: str) -> None:
    _entrar(api, cpf)
    resp = api.post("/auth/mfa/verificar", json={"codigo": "12ab56"})
    assert resp.status_code == 422
    assert "12ab56" not in resp.text


# --- Códigos de recuperação --------------------------------------------------------------


def test_codigo_de_recuperacao_vale_uma_vez(
    api: TestClient, cpf: str, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    _, codigos = _ativar(api, cpf)
    with fabrica_sessao() as db:
        guardados = db.scalars(select(CodigoRecuperacao.codigo_hash)).all()
    assert all(c.replace("-", "").encode() not in h for c in codigos for h in guardados)

    _entrar(api, cpf)
    resp = api.post("/auth/mfa/recuperar", json={"codigo": codigos[0].lower().replace("-", "")})
    assert resp.json() == {"autenticado": True, "codigos_restantes": 9}
    assert api.get("/auth/sessao").status_code == 200

    _entrar(api, cpf)
    assert api.post("/auth/mfa/recuperar", json={"codigo": codigos[0]}).status_code == 401


def test_uso_concorrente_do_mesmo_codigo_so_vence_uma_vez(
    cpf: str, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    cpf_hash = _cpf_hash(settings_integracao, cpf)
    codigo_hash = hash_busca(settings_integracao.chave_hmac, FinalidadeHash.CODIGO_RECUPERACAO, "X")
    with fabrica_sessao() as db, db.begin():
        codigo_repo.inserir(db, cpf_hash, [codigo_hash])
    agora = datetime.now(UTC)
    with fabrica_sessao() as db1, fabrica_sessao() as db2:
        with db1.begin():
            assert codigo_repo.usar(db1, cpf_hash, codigo_hash, agora)
        with db2.begin():
            assert not codigo_repo.usar(db2, cpf_hash, codigo_hash, agora)


def test_novos_codigos_exigem_totp_e_invalidam_os_antigos(api: TestClient, cpf: str) -> None:
    segredo, antigos = _ativar(api, cpf)
    assert api.post("/auth/mfa/codigos", json={"codigo": "000000"}).status_code == 401
    resp = api.post("/auth/mfa/codigos", json={"codigo": _codigo(segredo, 1)})
    assert resp.status_code == 200
    novos = resp.json()["codigos_recuperacao"]
    assert not set(novos) & set(antigos)

    api.post("/auth/logout")
    _entrar(api, cpf)
    assert api.post("/auth/mfa/recuperar", json={"codigo": antigos[1]}).status_code == 401
    assert api.post("/auth/mfa/recuperar", json={"codigo": novos[0]}).status_code == 200


def test_novos_codigos_sem_sessao_e_recusado(api: TestClient) -> None:
    assert api.post("/auth/mfa/codigos", json={"codigo": "123456"}).status_code == 401


# --- Sessão completa ---------------------------------------------------------------------


def _sessao_completa(fabrica: Fabrica, settings: Settings, cpf: str, agora: datetime) -> str:
    with fabrica() as db, db.begin():
        pre = sessao_svc.criar_pre_auth(db, _cpf_hash(settings, cpf), CTX, agora)
        obj = sessao_svc.obter_pre_auth(db, pre, agora)
        assert obj is not None
        return sessao_svc.promover(db, obj, CTX, agora, metodo="teste")


def test_sessao_expira_por_inatividade(
    cpf: str, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    agora = datetime.now(UTC)
    token = _sessao_completa(fabrica_sessao, settings_integracao, cpf, agora)
    with fabrica_sessao() as db, db.begin():
        assert sessao_svc.validar(db, token, agora + timedelta(minutes=16)) is None
    with fabrica_sessao() as db:
        assert db.get(Sessao, hash_token(token)) is None  # removida ao expirar


def test_uso_renova_mas_vida_maxima_e_8h(
    cpf: str, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    agora = datetime.now(UTC)
    token = _sessao_completa(fabrica_sessao, settings_integracao, cpf, agora)
    for minutos in range(10, 8 * 60, 10):  # uso a cada 10 min mantém a sessão viva
        with fabrica_sessao() as db, db.begin():
            atual = sessao_svc.validar(db, token, agora + timedelta(minutes=minutos))
            assert atual is not None
            assert atual.expira_em <= agora + timedelta(hours=8)
    with fabrica_sessao() as db, db.begin():
        assert sessao_svc.validar(db, token, agora + timedelta(hours=8)) is None


def test_token_de_pre_auth_nao_vale_como_sessao(
    api: TestClient, cpf: str, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    agora = datetime.now(UTC)
    with fabrica_sessao() as db, db.begin():
        pre = sessao_svc.criar_pre_auth(db, _cpf_hash(settings_integracao, cpf), CTX, agora)
    api.cookies.set("__Host-sessao", pre, domain="testserver.local", path="/")
    assert api.get("/auth/sessao").status_code == 401

    # Controle positivo: o mesmo mecanismo de cookie com um token de sessão real funciona.
    real = _sessao_completa(fabrica_sessao, settings_integracao, cpf, agora)
    api.cookies.set("__Host-sessao", real, domain="testserver.local", path="/")
    assert api.get("/auth/sessao").status_code == 200


def test_logout_encerra_no_servidor(
    api: TestClient, cpf: str, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    _ativar(api, cpf)
    token = api.cookies.get("__Host-sessao")
    assert token
    resp = api.post("/auth/logout")
    assert resp.status_code == 204
    assert any("__Host-sessao=" in c for c in resp.headers.get_list("set-cookie"))
    with fabrica_sessao() as db:
        assert db.get(Sessao, hash_token(token)) is None
    api.cookies.set("__Host-sessao", token, domain="testserver.local", path="/")
    assert api.get("/auth/sessao").status_code == 401


# --- Troca de senha ----------------------------------------------------------------------


def test_troca_de_senha(
    api: TestClient,
    cpf: str,
    fabrica_sessao: Fabrica,
    settings_integracao: Settings,
) -> None:
    _ativar(api, cpf)
    outra = _sessao_completa(fabrica_sessao, settings_integracao, cpf, datetime.now(UTC))
    nova = "Nova#Senha#2026"

    errada = api.post("/auth/senha", json={"senha_atual": "Errada#2026xx", "nova_senha": nova})
    assert errada.json() == {"detail": "Senha atual incorreta."}
    assert _usuario(fabrica_sessao, settings_integracao, cpf).falhas_login == 1

    fraca = api.post("/auth/senha", json={"senha_atual": SENHA, "nova_senha": "fraca"})
    assert fraca.status_code == 422 and "fraca" not in fraca.text
    com_cpf = api.post("/auth/senha", json={"senha_atual": SENHA, "nova_senha": f"Ab#{cpf}"})
    assert "não conter o CPF" in com_cpf.json()["detail"]
    igual = api.post("/auth/senha", json={"senha_atual": SENHA, "nova_senha": SENHA})
    assert igual.json() == {"detail": "A nova senha deve ser diferente da atual."}

    assert (
        api.post("/auth/senha", json={"senha_atual": SENHA, "nova_senha": nova}).status_code == 204
    )
    assert api.get("/auth/sessao").status_code == 200  # a sessão atual continua
    with fabrica_sessao() as db:
        assert db.get(Sessao, hash_token(outra)) is None  # as outras foram encerradas
        evento = db.scalars(
            select(Log).where(Log.acao == "password_change").order_by(Log.id_log.desc())
        ).first()
    assert evento is not None and evento.resumo_acessado == {"sessoes_encerradas": 1}

    api.post("/auth/logout")
    assert api.post("/auth/login", json={"cpf": cpf, "senha": SENHA}).status_code == 401
    assert _entrar(api, cpf, nova) == "mfa"


# --- Reset administrativo ----------------------------------------------------------------


def test_reset_de_acesso_forca_novo_mfa_e_troca_de_senha(
    api: TestClient, cpf: str, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    _, codigos = _ativar(api, cpf)
    with fabrica_sessao() as db, db.begin():
        temporaria = usuario_service.resetar_acesso(
            db, settings_integracao, cpf, ContextoRequisicao(), datetime.now(UTC)
        )
    assert api.get("/auth/sessao").status_code == 401  # sessões revogadas
    u = _usuario(fabrica_sessao, settings_integracao, cpf)
    assert (u.mfa_ativo, u.totp_segredo_cripto, u.troca_senha_obrigatoria) == (False, None, True)

    assert api.post("/auth/login", json={"cpf": cpf, "senha": SENHA}).status_code == 401
    segredo, _ = _ativar_com_senha(api, cpf, temporaria)
    assert api.get("/auth/sessao").json()["troca_senha_obrigatoria"] is True
    bloqueado = api.post("/auth/mfa/codigos", json={"codigo": _codigo(segredo, 1)})
    assert bloqueado.json() == {"detail": "Troca de senha obrigatória."}

    nova = "Depois#Reset2026"
    resp = api.post("/auth/senha", json={"senha_atual": temporaria, "nova_senha": nova})
    assert resp.status_code == 204
    assert api.get("/auth/sessao").json()["troca_senha_obrigatoria"] is False
    assert api.post("/auth/mfa/codigos", json={"codigo": _codigo(segredo, 1)}).status_code == 200

    api.post("/auth/logout")
    _entrar(api, cpf, nova)
    assert api.post("/auth/mfa/recuperar", json={"codigo": codigos[0]}).status_code == 401


def _ativar_com_senha(api: TestClient, cpf: str, senha: str) -> tuple[str, list[str]]:
    assert _entrar(api, cpf, senha) == "mfa_cadastro"
    segredo = api.post("/auth/mfa/cadastro").json()["chave"]
    resp = api.post("/auth/mfa/ativar", json={"codigo": _codigo(segredo)})
    assert resp.status_code == 200
    return segredo, resp.json()["codigos_recuperacao"]


def test_reset_de_cpf_inexistente(fabrica_sessao: Fabrica, settings_integracao: Settings) -> None:
    with (
        fabrica_sessao() as db,
        db.begin(),
        pytest.raises(usuario_service.UsuarioNaoEncontrado),
    ):
        usuario_service.resetar_acesso(
            db, settings_integracao, gerar_cpf(), ContextoRequisicao(), datetime.now(UTC)
        )


@pytest.mark.parametrize("resposta", ["RESETAR", "não"])
def test_script_de_reset(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    cpf: str,
    settings_integracao: Settings,
    resposta: str,
) -> None:
    from scripts import resetar_acesso

    monkeypatch.setattr("builtins.input", lambda _prompt: resposta)
    monkeypatch.setattr(resetar_acesso, "get_settings", lambda: settings_integracao)
    if resposta == "RESETAR":
        resetar_acesso.main(["--cpf", cpf])
        assert "Senha temporária" in capsys.readouterr().out
    else:
        with pytest.raises(SystemExit, match="Cancelado"):
            resetar_acesso.main(["--cpf", cpf])


def test_script_de_reset_valida_cpf(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import resetar_acesso

    with pytest.raises(SystemExit, match="CPF inválido"):
        resetar_acesso.main(["--cpf", "111.111.111-11"])
    monkeypatch.setattr("builtins.input", lambda _prompt: "RESETAR")
    with pytest.raises(SystemExit, match="não encontrado"):
        resetar_acesso.main(["--cpf", gerar_cpf()])


# --- Auditoria ---------------------------------------------------------------------------


def test_eventos_de_mfa_auditados_sem_segredos(
    api: TestClient, cpf: str, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    segredo, codigos = _ativar(api, cpf)
    _entrar(api, cpf)
    api.post("/auth/mfa/verificar", json={"codigo": "000000"})
    api.post("/auth/mfa/recuperar", json={"codigo": codigos[0]})
    api.post("/auth/logout")

    with fabrica_sessao() as db:
        eventos = db.scalars(
            select(Log)
            .where(Log.cpf_usuario_hash == _cpf_hash(settings_integracao, cpf))
            .order_by(Log.id_log)
        ).all()
    acoes = [e.acao for e in eventos]
    for esperado in (
        "mfa_enrolled",
        "recovery_codes_generated",
        "session_created",
        "mfa_failure",
        "mfa_recovery_used",
        "logout",
    ):
        assert esperado in acoes
    texto = " ".join(str(e.resumo_acessado) for e in eventos)
    assert segredo not in texto
    assert not any(c in texto or c.replace("-", "") in texto for c in codigos)
