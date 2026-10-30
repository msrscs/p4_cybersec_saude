"""RF-04 / THREAT_MODEL T1, R1, E1: consulta do log, somente leitura e auditada (ADR-0015)."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.cpf import formatar_cpf
from app.core.crypto import ErroCriptografia, FinalidadeHash, hash_busca
from app.models import Log
from app.services import auditoria
from app.services.auditoria import ContextoRequisicao, Evento

from .conftest import gerar_cpf
from .test_pacientes import Logar, _novo, logar  # noqa: F401

Fabrica = sessionmaker[Session]
PERFIS = ["Administrador", "Gestor", "Gestor do Cuidado", "Navegador", "Auditor", None]
PODEM_LER = {"Administrador", "Auditor"}


def _consulta(api: TestClient, **corpo: object) -> dict[str, object]:
    resp = api.post("/logs/consulta", json=corpo)
    assert resp.status_code == 200, resp.text
    dados: dict[str, object] = resp.json()
    return dados


@pytest.mark.parametrize("perfil", PERFIS)
def test_so_auditor_e_administrador_leem_o_log(logar: Logar, perfil: str | None) -> None:  # noqa: F811
    api = logar(perfil).api
    esperado = 200 if perfil in PODEM_LER else 403
    assert api.post("/logs/consulta", json={}).status_code == esperado
    assert api.get("/logs/acoes").status_code == esperado
    assert api.get("/logs/integridade").status_code == esperado
    assert ("log:ler" in api.get("/auth/sessao").json()["permissoes"]) == (perfil in PODEM_LER)


def test_negado_e_auditado(logar: Logar, fabrica_sessao: Fabrica) -> None:  # noqa: F811
    resp = logar("Navegador").api.post("/logs/consulta", json={})
    assert resp.json() == {"detail": "Acesso negado."}
    with fabrica_sessao() as db:
        ultimo = db.scalars(
            select(Log).where(Log.acao == "access_denied").order_by(Log.seq_cadeia.desc()).limit(1)
        ).one()
    assert ultimo.resumo_acessado["permissao"] == "log:ler"


def test_sem_sessao_devolve_401(app_teste: FastAPI) -> None:
    with TestClient(app_teste, base_url="https://testserver") as api:
        assert api.post("/logs/consulta", json={}).status_code == 401


def test_exige_token_csrf(logar: Logar) -> None:  # noqa: F811
    api = logar("Auditor").api
    del api.headers["X-CSRF-Token"]
    assert api.post("/logs/consulta", json={}).status_code == 403


def test_nao_ha_rota_que_altere_o_log(logar: Logar) -> None:  # noqa: F811
    api = logar("Administrador").api
    for metodo in ("put", "patch", "delete"):
        assert getattr(api, metodo)("/logs/consulta").status_code == 405


def test_item_mostra_cpfs_decifrados_e_nenhum_outro_dado_pessoal(
    logar: Logar,  # noqa: F811
    settings_integracao: Settings,
) -> None:
    logado = logar("Administrador")
    dados = _novo(nome="Severina Consultada")
    logado.api.post("/pacientes", json=dados)
    resp = logado.api.post("/logs/consulta", json={"acao": "patient_created"})
    assert resp.headers["cache-control"] == "no-store"
    item = resp.json()["itens"][0]
    assert item["acao"] == "patient_created"
    assert item["usuario_cpf"] == formatar_cpf(logado.cpf)
    assert item["paciente_cpf"] == dados["cpf"]
    assert len(item["usuario"]) == len(item["paciente"]) == len(item["hash"]) == 12
    completo = hash_busca(settings_integracao.chave_hmac, FinalidadeHash.CPF, logado.cpf).hex()
    assert item["usuario"] == completo[:12]
    assert completo not in resp.text
    assert "Severina" not in resp.text and "exemplo.com.br" not in resp.text


def test_auditor_ve_so_o_hash_e_nenhum_cpf(logar: Logar) -> None:  # noqa: F811
    admin, auditor = logar("Administrador"), logar("Auditor")
    dados = _novo()
    admin.api.post("/pacientes", json=dados)
    resp = auditor.api.post("/logs/consulta", json={"acao": "patient_created"})
    item = resp.json()["itens"][0]
    assert item["usuario_cpf"] is None and item["paciente_cpf"] is None
    assert len(item["usuario"]) == len(item["paciente"]) == 12
    assert str(dados["cpf"]) not in resp.text and formatar_cpf(admin.cpf) not in resp.text
    assert "log:ver_cpf" not in auditor.api.get("/auth/sessao").json()["permissoes"]


def test_cpf_sem_cadastro_continua_como_hash(
    logar: Logar,  # noqa: F811
    fabrica_sessao: Fabrica,
    settings_integracao: Settings,
) -> None:
    desconhecido = hash_busca(settings_integracao.chave_hmac, FinalidadeHash.CPF, gerar_cpf())
    with fabrica_sessao() as db, db.begin():
        auditoria.registrar(
            db, Evento.LOGIN_FAILURE, ContextoRequisicao(), cpf_usuario_hash=desconhecido
        )
    item = _consulta(logar("Auditor").api, acao="login_failure")["itens"][0]  # type: ignore[index]
    assert item["usuario_cpf"] is None
    assert item["usuario"] == desconhecido.hex()[:12]


def test_cadastro_adulterado_nao_derruba_a_auditoria(
    logar: Logar,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logado = logar("Administrador")

    def falha(*_a: object) -> str:
        raise ErroCriptografia("Falha ao decifrar dado.")

    monkeypatch.setattr("app.services.usuario.cpf_em_claro", falha)
    item = _consulta(logado.api, cpf=formatar_cpf(logado.cpf))["itens"][0]  # type: ignore[index]
    assert item["usuario_cpf"] is None and len(item["usuario"]) == 12


def test_cpf_exibido_nao_e_gravado_no_log(
    logar: Logar,  # noqa: F811
    fabrica_sessao: Fabrica,
) -> None:
    logado = logar("Administrador")
    _consulta(logado.api)
    with fabrica_sessao() as db:
        evento = db.scalars(
            select(Log).where(Log.acao == "log_read").order_by(Log.seq_cadeia.desc()).limit(1)
        ).one()
    assert evento.resumo_acessado["cpfs_exibidos"] >= 1
    assert evento.resumo_acessado["seq_inicio"] >= evento.resumo_acessado["seq_fim"]
    texto = str(evento.resumo_acessado)
    assert logado.cpf not in texto and formatar_cpf(logado.cpf) not in texto


def test_sessao_devolve_o_nome_do_usuario_logado(logar: Logar) -> None:  # noqa: F811
    assert logar("Navegador").api.get("/auth/sessao").json()["nome"] == "Ana"


def test_nome_adulterado_nao_derruba_a_sessao(
    logar: Logar,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logado = logar("Navegador")

    def falha(*_a: object, **_k: object) -> str:
        raise ErroCriptografia("Falha ao decifrar dado.")

    monkeypatch.setattr("app.services.usuario.decifrar_campo", falha)
    resp = logado.api.get("/auth/sessao")
    assert resp.status_code == 200 and resp.json()["nome"] is None


def test_filtros_por_acao_usuario_e_periodo(logar: Logar) -> None:  # noqa: F811
    a, b = logar("Administrador"), logar("Administrador")
    b.api.post("/auth/logout")  # evento de outro usuário não pode aparecer no filtro de `a`
    a.api.post("/pacientes", json=_novo())

    por_cpf = _consulta(a.api, cpf=formatar_cpf(a.cpf))
    usuarios = {i["usuario"] for i in por_cpf["itens"]}  # type: ignore[attr-defined]
    assert len(usuarios) == 1

    por_acao = _consulta(a.api, acao="logout")
    assert {i["acao"] for i in por_acao["itens"]} == {"logout"}  # type: ignore[attr-defined]

    combinado = _consulta(a.api, cpf=formatar_cpf(a.cpf), acao="logout")
    assert combinado["itens"] == []

    agora = datetime.now(UTC)
    futuro = (agora + timedelta(days=1)).isoformat()
    assert _consulta(a.api, de=futuro)["itens"] == []
    passado = (agora - timedelta(days=1)).isoformat()
    assert _consulta(a.api, ate=passado)["itens"] == []
    assert _consulta(a.api, de=passado, ate=futuro)["itens"]


def test_paginacao_por_cursor_sem_repetir(
    logar: Logar,  # noqa: F811
    fabrica_sessao: Fabrica,
) -> None:
    api = logar("Auditor").api
    with fabrica_sessao() as db, db.begin():
        for _ in range(60):
            auditoria.registrar(db, Evento.RATE_LIMITED, ContextoRequisicao())
    primeira = _consulta(api, acao="rate_limited")
    assert len(primeira["itens"]) == 50  # type: ignore[arg-type]
    assert primeira["proximo"] is not None
    segunda = _consulta(api, acao="rate_limited", antes=primeira["proximo"])
    seqs = [i["seq"] for i in [*primeira["itens"], *segunda["itens"]]]  # type: ignore[misc]
    assert seqs == sorted(seqs, reverse=True)
    assert len(seqs) == len(set(seqs))
    assert len(seqs) >= 60


@pytest.mark.parametrize(
    "corpo",
    [
        {"acao": "' OR 1=1 --"},
        {"acao": "inventada"},
        {"cpf": "111.111.111-11"},
        {"de": "ontem"},
        {"de": "2026-01-01T00:00:00"},  # sem fuso: ambíguo
        {"de": "2026-02-01T00:00:00Z", "ate": "2026-01-01T00:00:00Z"},
        {"antes": 0},
        {"antes": 2**64},
        {"limite": 100000},
    ],
)
def test_entrada_invalida_e_recusada_sem_ecoar(logar: Logar, corpo: dict[str, object]) -> None:  # noqa: F811
    resp = logar("Auditor").api.post("/logs/consulta", json=corpo)
    assert resp.status_code == 422
    assert "111.111.111-11" not in resp.text and "OR 1=1" not in resp.text


def test_leitura_e_auditada_sem_cpf_em_claro(
    logar: Logar,  # noqa: F811
    fabrica_sessao: Fabrica,
    settings_integracao: Settings,
) -> None:
    auditor, alvo = logar("Auditor"), logar("Navegador")
    _consulta(auditor.api, cpf=formatar_cpf(alvo.cpf), acao="login_success")
    with fabrica_sessao() as db:
        evento = db.scalars(
            select(Log).where(Log.acao == "log_read").order_by(Log.seq_cadeia.desc()).limit(1)
        ).one()
    chave = settings_integracao.chave_hmac
    assert evento.cpf_usuario_hash == hash_busca(chave, FinalidadeHash.CPF, auditor.cpf)
    resumo = evento.resumo_acessado
    assert resumo["registros"] == 1 and resumo["acao"] == "login_success"
    assert resumo["usuario"] == hash_busca(chave, FinalidadeHash.CPF, alvo.cpf).hex()[:12]
    assert resumo["cpfs_exibidos"] == 0  # o Auditor só vê hash
    assert alvo.cpf not in str(resumo) and formatar_cpf(alvo.cpf) not in str(resumo)


def test_cada_pagina_lida_gera_um_evento(logar: Logar, fabrica_sessao: Fabrica) -> None:  # noqa: F811
    api = logar("Auditor").api

    def total() -> int:
        with fabrica_sessao() as db:
            return int(db.scalar(select(func.count()).where(Log.acao == "log_read")) or 0)

    antes = total()
    _consulta(api)
    _consulta(api)
    assert total() == antes + 2


def test_acoes_lista_todos_os_eventos(logar: Logar) -> None:  # noqa: F811
    corpo = logar("Auditor").api.get("/logs/acoes").json()
    assert corpo["acoes"] == sorted(e.value for e in Evento)


def test_integridade_mostra_a_ultima_verificacao(
    logar: Logar,  # noqa: F811
    fabrica_sessao: Fabrica,
) -> None:
    api = logar("Auditor").api
    with fabrica_sessao() as db, db.begin():
        auditoria.registrar(db, Evento.LOG_CHAIN_VERIFIED, ContextoRequisicao())
    corpo = api.get("/logs/integridade").json()
    assert corpo["integra"] is True and corpo["verificada_em"] is not None
    assert corpo["total_registros"] > 0

    with fabrica_sessao() as db, db.begin():
        auditoria.registrar(db, Evento.LOG_CHAIN_BROKEN, ContextoRequisicao())
    assert api.get("/logs/integridade").json()["integra"] is False
