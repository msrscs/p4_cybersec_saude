"""T10 / THREAT_MODEL S1, S2, E1 (ADR-0028): achados da revisão de segurança.

- Senha correta não zera contadores: sem isso, novos logins permitiam palpites ilimitados de TOTP.
- O bloqueio da conta vale também nas rotas com sessão.
- Senha temporária expira.
- Toda rota exige sessão, salvo a lista fechada das etapas de login.
"""

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pyotp
import pytest
from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import sessao_atual
from app.core import totp
from app.core.config import Settings
from app.core.crypto import FinalidadeHash, hash_busca
from app.models import Log, Usuario
from app.services import auth as auth_service
from app.services import usuario as usuario_service
from app.services.auditoria import ContextoRequisicao
from app.services.usuario import VALIDADE_SENHA_TEMPORARIA, NovoUsuario

from .conftest import com_csrf, gerar_cpf
from .test_pacientes import Logado, Logar, logar  # noqa: F401

SENHA = "Saúde#Recife2026"
NOVA = "Outra#Senha2026x"
Fabrica = sessionmaker[Session]
ROTAS_SEM_SESSAO = {
    "/health",
    "/auth/login",
    "/auth/mfa/cadastro",
    "/auth/mfa/ativar",
    "/auth/mfa/verificar",
    "/auth/mfa/recuperar",
}


@pytest.fixture
def cpf(fabrica_sessao: Fabrica, settings_integracao: Settings) -> str:
    cpf = gerar_cpf()
    dados = NovoUsuario(cpf=cpf, nome="Bia", email=f"b{cpf}@recife.pe.gov.br", senha=SENHA)
    with fabrica_sessao() as db, db.begin():
        usuario_service.cadastrar(db, settings_integracao, dados, ContextoRequisicao())
    return cpf


def _hash(settings: Settings, cpf: str) -> bytes:
    return hash_busca(settings.chave_hmac, FinalidadeHash.CPF, cpf)


def _usuario(fabrica: Fabrica, settings: Settings, cpf: str) -> Usuario:
    with fabrica() as db:
        return db.get_one(Usuario, _hash(settings, cpf))


def _alterar(fabrica: Fabrica, settings: Settings, cpf: str, **campos: object) -> None:
    with fabrica() as db, db.begin():
        usuario = db.get_one(Usuario, _hash(settings, cpf))
        for nome, valor in campos.items():
            setattr(usuario, nome, valor)


def _codigo(segredo: str, deslocamento: int = 0) -> str:
    return pyotp.TOTP(segredo).at((totp.passo(datetime.now(UTC)) + deslocamento) * 30)


def _codigo_errado(segredo: str) -> str:
    validos = {_codigo(segredo, d) for d in range(-2, 3)}
    return next(c for c in (f"{n:06d}" for n in range(10)) if c not in validos)


def _ativar(api: TestClient, cpf: str) -> str:
    assert api.post("/auth/login", json={"cpf": cpf, "senha": SENHA}).status_code == 200
    prov = api.post("/auth/mfa/cadastro").json()
    segredo = str(parse_qs(urlparse(prov["otpauth_uri"]).query)["secret"][0])
    assert api.post("/auth/mfa/ativar", json={"codigo": _codigo(segredo)}).status_code == 200
    com_csrf(api)
    return segredo


@pytest.fixture
def admin(logar: Logar) -> Logado:  # noqa: F811
    return logar("Administrador")


# --- Senha correta não zera os contadores -------------------------------------------------


def test_novo_login_nao_zera_as_falhas_de_mfa(
    api: TestClient, cpf: str, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    """Ataque: com a senha roubada, 4 palpites de TOTP, novo login, mais 4, sem nunca bloquear."""
    segredo = _ativar(api, cpf)
    errado = _codigo_errado(segredo)
    for _ in range(2):
        assert api.post("/auth/login", json={"cpf": cpf, "senha": SENHA}).status_code == 200
        for _ in range(2):
            api.post("/auth/mfa/verificar", json={"codigo": errado})
    assert api.post("/auth/login", json={"cpf": cpf, "senha": SENHA}).status_code == 200
    api.post("/auth/mfa/verificar", json={"codigo": errado})

    u = _usuario(fabrica_sessao, settings_integracao, cpf)
    assert u.bloqueios == 1 and u.bloqueado_ate is not None
    assert api.post("/auth/login", json={"cpf": cpf, "senha": SENHA}).status_code == 401


def test_bloqueio_continua_dobrando_com_a_senha_correta(
    api: TestClient, cpf: str, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    segredo = _ativar(api, cpf)
    errado = _codigo_errado(segredo)
    _alterar(
        fabrica_sessao,
        settings_integracao,
        cpf,
        bloqueios=1,
        falhas_login=0,
        bloqueado_ate=datetime.now(UTC) - timedelta(minutes=1),
    )
    assert api.post("/auth/login", json={"cpf": cpf, "senha": SENHA}).status_code == 200
    for _ in range(5):
        api.post("/auth/mfa/verificar", json={"codigo": errado})

    u = _usuario(fabrica_sessao, settings_integracao, cpf)
    assert u.bloqueios == 2
    assert u.bloqueado_ate is not None
    assert u.bloqueado_ate - datetime.now(UTC) > timedelta(minutes=29)


def test_segundo_fator_correto_zera_os_contadores(
    api: TestClient, cpf: str, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    segredo = _ativar(api, cpf)
    _alterar(
        fabrica_sessao,
        settings_integracao,
        cpf,
        bloqueios=2,
        falhas_login=3,
        totp_ultimo_passo=totp.passo(datetime.now(UTC)) - 5,
    )
    assert api.post("/auth/login", json={"cpf": cpf, "senha": SENHA}).status_code == 200
    u = _usuario(fabrica_sessao, settings_integracao, cpf)
    assert (u.falhas_login, u.bloqueios) == (3, 2), "só a senha não zera"

    resp = api.post("/auth/mfa/verificar", json={"codigo": _codigo(segredo)})
    assert resp.status_code == 200, resp.text
    u = _usuario(fabrica_sessao, settings_integracao, cpf)
    assert (u.falhas_login, u.bloqueios, u.bloqueado_ate) == (0, 0, None)


def test_codigo_de_recuperacao_correto_zera_os_contadores(
    api: TestClient, cpf: str, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    assert api.post("/auth/login", json={"cpf": cpf, "senha": SENHA}).status_code == 200
    prov = api.post("/auth/mfa/cadastro").json()
    segredo = parse_qs(urlparse(prov["otpauth_uri"]).query)["secret"][0]
    codigos = api.post("/auth/mfa/ativar", json={"codigo": _codigo(segredo)}).json()
    _alterar(fabrica_sessao, settings_integracao, cpf, bloqueios=2, falhas_login=3)
    assert api.post("/auth/login", json={"cpf": cpf, "senha": SENHA}).status_code == 200

    codigo = codigos["codigos_recuperacao"][0]
    assert api.post("/auth/mfa/recuperar", json={"codigo": codigo}).status_code == 200
    u = _usuario(fabrica_sessao, settings_integracao, cpf)
    assert (u.falhas_login, u.bloqueios, u.bloqueado_ate) == (0, 0, None)


# --- O bloqueio vale nas rotas com sessão -------------------------------------------------


def test_troca_de_senha_recusada_durante_o_bloqueio(
    api: TestClient, cpf: str, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    """Ataque: com a sessão roubada, testar senhas sem parar, ignorando o bloqueio da conta."""
    _ativar(api, cpf)
    hash_antes = _usuario(fabrica_sessao, settings_integracao, cpf).senha_hash
    _alterar(
        fabrica_sessao,
        settings_integracao,
        cpf,
        bloqueado_ate=datetime.now(UTC) + timedelta(minutes=10),
    )
    resp = api.post("/auth/senha", json={"senha_atual": SENHA, "nova_senha": NOVA})
    assert resp.status_code == 422
    assert resp.json() == {"detail": "Senha atual incorreta."}

    u = _usuario(fabrica_sessao, settings_integracao, cpf)
    assert u.senha_hash == hash_antes
    assert u.falhas_login == 0, "tentativa recusada não conta nem prolonga o bloqueio"
    with fabrica_sessao() as db:
        motivos = db.scalars(
            select(Log.resumo_acessado).where(
                Log.cpf_usuario_hash == u.cpf_hash, Log.acao == "login_failure"
            )
        ).all()
    assert any(m and m.get("motivo") == "conta_bloqueada_temporariamente" for m in motivos)


def test_novos_codigos_recusados_durante_o_bloqueio(
    api: TestClient, cpf: str, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    segredo = _ativar(api, cpf)
    _alterar(
        fabrica_sessao,
        settings_integracao,
        cpf,
        bloqueado_ate=datetime.now(UTC) + timedelta(minutes=10),
    )
    resp = api.post("/auth/mfa/codigos", json={"codigo": _codigo(segredo, 1)})
    assert resp.status_code == 401
    assert _usuario(fabrica_sessao, settings_integracao, cpf).falhas_login == 0


# --- Senha temporária expira --------------------------------------------------------------


def _temporario(fabrica: Fabrica, settings: Settings) -> tuple[str, str]:
    cpf = gerar_cpf()
    senha = usuario_service.gerar_senha_temporaria()
    dados = NovoUsuario(
        cpf=cpf,
        nome="Caio",
        email=f"c{cpf}@recife.pe.gov.br",
        senha=senha,
        troca_senha_obrigatoria=True,
    )
    with fabrica() as db, db.begin():
        usuario_service.cadastrar(db, settings, dados, ContextoRequisicao())
    return cpf, senha


def test_senha_temporaria_tem_validade(
    fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    cpf, _ = _temporario(fabrica_sessao, settings_integracao)
    u = _usuario(fabrica_sessao, settings_integracao, cpf)
    assert u.senha_temporaria_expira_em is not None
    restante = u.senha_temporaria_expira_em - datetime.now(UTC)
    assert timedelta(0) < restante <= VALIDADE_SENHA_TEMPORARIA


def test_senha_temporaria_vencida_nao_entra_e_nao_revela_o_motivo(
    api: TestClient, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    cpf, senha = _temporario(fabrica_sessao, settings_integracao)
    assert api.post("/auth/login", json={"cpf": cpf, "senha": senha}).status_code == 200
    _alterar(
        fabrica_sessao,
        settings_integracao,
        cpf,
        senha_temporaria_expira_em=datetime.now(UTC) - timedelta(seconds=1),
    )
    resp = api.post("/auth/login", json={"cpf": cpf, "senha": senha})
    assert resp.status_code == 401
    assert resp.json() == {"detail": "CPF ou senha inválidos."}

    u = _usuario(fabrica_sessao, settings_integracao, cpf)
    with fabrica_sessao() as db:
        motivos = db.scalars(
            select(Log.resumo_acessado).where(
                Log.cpf_usuario_hash == u.cpf_hash, Log.acao == "login_failure"
            )
        ).all()
    assert any(m and m.get("motivo") == "senha_temporaria_expirada" for m in motivos)


def test_reset_renova_a_validade_e_a_troca_a_encerra(
    api: TestClient, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    cpf, _ = _temporario(fabrica_sessao, settings_integracao)
    _alterar(
        fabrica_sessao,
        settings_integracao,
        cpf,
        senha_temporaria_expira_em=datetime.now(UTC) - timedelta(days=1),
    )
    with fabrica_sessao() as db, db.begin():
        temporaria = usuario_service.resetar_acesso(
            db, settings_integracao, cpf, ContextoRequisicao(), datetime.now(UTC)
        )
    u = _usuario(fabrica_sessao, settings_integracao, cpf)
    assert u.senha_temporaria_expira_em is not None
    assert u.senha_temporaria_expira_em > datetime.now(UTC)

    assert api.post("/auth/login", json={"cpf": cpf, "senha": temporaria}).status_code == 200
    prov = api.post("/auth/mfa/cadastro").json()
    segredo = parse_qs(urlparse(prov["otpauth_uri"]).query)["secret"][0]
    assert api.post("/auth/mfa/ativar", json={"codigo": _codigo(segredo)}).status_code == 200
    com_csrf(api)
    resp = api.post("/auth/senha", json={"senha_atual": temporaria, "nova_senha": NOVA})
    assert resp.status_code == 204, resp.text
    u = _usuario(fabrica_sessao, settings_integracao, cpf)
    assert u.senha_temporaria_expira_em is None and not u.troca_senha_obrigatoria


def test_senha_definida_pelo_usuario_nao_expira(
    cpf: str, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    u = _usuario(fabrica_sessao, settings_integracao, cpf)
    assert u.senha_temporaria_expira_em is None
    assert (
        auth_service.senha_temporaria_vencida(u, datetime.now(UTC) + timedelta(days=3650)) is False
    )


# --- Inventário das rotas -----------------------------------------------------------------


def _chamadas(dependente: Dependant) -> set[object]:
    encontradas: set[object] = {dependente.call}
    for sub in dependente.dependencies:
        encontradas |= _chamadas(sub)
    return encontradas


def _rotas(rotas: Iterable[object]) -> list[APIRoute]:
    """Inclui as rotas dos routers incluídos, que o FastAPI guarda aninhadas."""
    achadas: list[APIRoute] = []
    for rota in rotas:
        if isinstance(rota, APIRoute):
            achadas.append(rota)
        else:
            incluido = getattr(rota, "original_router", None)
            achadas += _rotas(incluido.routes if incluido is not None else [])
    return achadas


def test_toda_rota_exige_sessao_salvo_as_etapas_de_login(app_teste: FastAPI) -> None:
    """Protege as rotas novas: quem esquecer a dependência de sessão reprova aqui."""
    rotas = _rotas(app_teste.router.routes)
    assert len(rotas) > 50
    abertas = {r.path for r in rotas if sessao_atual not in _chamadas(r.dependant)}
    assert abertas == ROTAS_SEM_SESSAO


# --- Entradas hostis, com sessão de administrador ----------------------------------------


@pytest.mark.parametrize(
    "termo",
    [
        "' OR '1'='1",
        "'; DROP TABLE app.log; --",
        "%",
        "_",
        "\\",
        "<script>alert(1)</script>",
        "{{7*7}}",
        "../../etc/passwd",
    ],
)
def test_busca_trata_entrada_hostil_como_texto(admin: Logado, termo: str) -> None:
    """Nem curinga, nem SQL: a busca devolve vazio em vez de erro ou da tabela inteira."""
    for rota in ("/unidades/lista", "/servicos/lista", "/cids/lista", "/tipos-oci/lista"):
        resp = admin.api.post(rota, json={"busca": termo})
        assert resp.status_code in (200, 422), f"{rota}: {resp.status_code}"
        if resp.status_code == 200:
            assert resp.json()["itens"] == [], rota
    resp = admin.api.post("/usuarios/lista", json={"busca": termo})
    assert resp.status_code in (200, 422)
    if resp.status_code == 200:
        assert resp.json()["itens"] == []


def test_erro_de_validacao_nao_ecoa_a_entrada(admin: Logado) -> None:
    segredo = "valor-secreto-<script>"
    resp = admin.api.post("/pacientes/busca", json={"cpf": segredo})
    assert resp.status_code == 422
    assert segredo not in resp.text
    assert set(resp.json()) == {"detail", "campos"}


def test_campo_desconhecido_e_recusado(admin: Logado) -> None:
    """Sem atribuição em massa: não dá para mandar status ou grupo junto de outro campo."""
    cpf = gerar_cpf()
    resp = admin.api.post(
        "/usuarios",
        json={
            "cpf": cpf,
            "nome": "Ana Lima",
            "email": f"a{cpf}@recife.pe.gov.br",
            "mfa_ativo": True,
            "senha_hash": "x",
        },
    )
    assert resp.status_code == 422
