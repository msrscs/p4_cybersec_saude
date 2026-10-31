"""ADR-0027 / THREAT_MODEL E1, E2, I1: dashboard de OCI, só agregados e com alcance por unidade."""

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings

from .test_ocis import (  # noqa: F401
    TEXTO_CLINICO,
    Cenario,
    _abrir,
    _na_unidade,
    _novo_paciente,
    _quando,
    _ultimo,
    cenario,
)
from .test_pacientes import Logar, logar  # noqa: F401

Fabrica = sessionmaker[Session]
Conn = psycopg.Connection[tuple[object, ...]]


def _dashboard(api: TestClient, id_tipo: int, **extra: object) -> dict[str, Any]:
    """Filtra pelo tipo do cenário: o banco de teste é compartilhado entre os testes."""
    resp = api.post("/ocis/dashboard", json={"id_tipo_oci": id_tipo, **extra})
    assert resp.status_code == 200, resp.text
    corpo: dict[str, Any] = resp.json()
    return corpo


def _etapa(api: TestClient, oci: dict[str, Any], situacao: str) -> None:
    url = f"/ocis/{oci['id']}/navegacoes/{oci['navegacoes'][0]['id']}"
    assert api.patch(url, json={"status": situacao}).status_code == 200


@pytest.mark.parametrize(
    ("perfil", "esperado"),
    [
        ("Administrador", 200),
        ("Gestor", 200),
        ("Gestor do Cuidado", 200),
        ("Navegador", 200),
        ("Auditor", 403),
        (None, 403),
    ],
)
def test_matriz_de_permissoes(
    logar: Logar,  # noqa: F811
    perfil: str | None,
    esperado: int,
) -> None:
    assert logar(perfil).api.post("/ocis/dashboard", json={}).status_code == esperado


def test_sem_sessao_e_sem_csrf_sao_recusados(
    cenario: Cenario,  # noqa: F811
    api: TestClient,
) -> None:
    assert api.post("/ocis/dashboard", json={}).status_code == 401
    del cenario.admin.headers["X-CSRF-Token"]
    assert cenario.admin.post("/ocis/dashboard", json={}).status_code == 403


@pytest.mark.parametrize(
    "corpo",
    [{"dias": 7}, {"dias": "muitos"}, {"id_tipo_oci": 0}, {"id_unidade": -1}, {"sql": "x"}],
)
def test_entrada_invalida(cenario: Cenario, corpo: dict[str, object]) -> None:  # noqa: F811
    assert cenario.admin.post("/ocis/dashboard", json=corpo).status_code == 422


def test_conta_as_ocis_e_as_etapas(cenario: Cenario) -> None:  # noqa: F811
    admin, tipo = cenario.admin, cenario.tipo["id"]
    aberta = _abrir(cenario)
    _etapa(admin, aberta, "realizado")
    concluida = _abrir(cenario, cpf=_novo_paciente(admin))
    _etapa(admin, concluida, "faltou")
    resp = admin.post(f"/ocis/{concluida['id']}/concluir", json={"resultado": TEXTO_CLINICO})
    assert resp.status_code == 200
    cancelada = _abrir(cenario, cpf=_novo_paciente(admin))
    assert admin.post(f"/ocis/{cancelada['id']}/cancelar").status_code == 200

    corpo = _dashboard(admin, tipo)

    assert corpo["alcance"] == "todas" and corpo["dias"] == 90
    assert corpo["abertas"]["em_aberto"] == 1 and corpo["abertas"]["atrasadas"] == 0
    assert corpo["abertas_no_periodo"] == 3 and corpo["canceladas_no_periodo"] == 1
    assert corpo["conclusoes"]["concluidas"] == 1 and corpo["conclusoes"]["no_prazo"] == 1
    assert 0 <= corpo["conclusoes"]["mediana_dias"] < 1
    assert corpo["por_tipo"] == [
        {
            "nome": cenario.tipo["tipo_oci"],
            "aberta": 1,
            "concluida": 1,
            "cancelada": 1,
        }
    ]
    assert [c["codigo"] for c in corpo["por_cid"]] == [cenario.cid["cid"]]
    assert corpo["por_cid"][0]["total"] == 3
    etapas = corpo["etapas"]
    assert etapas["realizado"] == 1 and etapas["faltou"] == 1 and etapas["cancelado"] == 1
    assert [g["nome"] for g in corpo["por_servico"]] == [cenario.servico["nome"]]
    assert [g["nome"] for g in corpo["por_unidade"]] == [cenario.unidade["nome"]]
    assert sum(p["abertas"] for p in corpo["serie"]) == 3
    assert sum(p["concluidas"] for p in corpo["serie"]) == 1


def test_agrupa_por_semana_e_por_mes_sem_buracos(cenario: Cenario) -> None:  # noqa: F811
    _abrir(cenario)
    tipo = cenario.tipo["id"]
    semanas = _dashboard(cenario.admin, tipo, dias=90)
    assert semanas["granularidade"] == "week" and 13 <= len(semanas["serie"]) <= 15
    meses = _dashboard(cenario.admin, tipo, dias=365)
    assert meses["granularidade"] == "month" and 12 <= len(meses["serie"]) <= 13
    assert all(p["inicio"].endswith("-01") for p in meses["serie"])
    assert sum(p["abertas"] for p in meses["serie"]) == 1


def test_proximas_etapas_so_na_janela(cenario: Cenario) -> None:  # noqa: F811
    tipo = cenario.tipo["id"]
    _abrir(cenario, data_hora=_quando(dias=2))
    _abrir(cenario, cpf=_novo_paciente(cenario.admin), data_hora=_quando(dias=20))
    assert _dashboard(cenario.admin, tipo)["proximas_etapas"] == 1


def test_prazo_vencido_e_prazo_em_alerta(
    cenario: Cenario,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _abrir(cenario)
    prazo = timedelta(days=cenario.tipo["prazo_diagnostico"])
    tipo = cenario.tipo["id"]

    def visto_em(instante: datetime) -> dict[str, int]:
        monkeypatch.setattr("app.api.ocis.agora", lambda: instante)
        resumo: dict[str, int] = _dashboard(cenario.admin, tipo, dias=365)["abertas"]
        return resumo

    hoje = datetime.now(UTC)
    assert visto_em(hoje + prazo - timedelta(days=3)) == {
        "em_aberto": 1,
        "atrasadas": 0,
        "vencem_em_breve": 1,
    }
    assert visto_em(hoje + prazo + timedelta(days=3)) == {
        "em_aberto": 1,
        "atrasadas": 1,
        "vencem_em_breve": 0,
    }


def test_conclusao_depois_do_prazo_nao_conta_como_no_prazo(
    cenario: Cenario,  # noqa: F811
    migrator_conn: Conn,
) -> None:
    oci = _abrir(cenario)
    migrator_conn.execute(
        "UPDATE app.oci SET prazo_em = now() - interval '1 day' WHERE id_publico = %s", (oci["id"],)
    )
    resp = cenario.admin.post(f"/ocis/{oci['id']}/concluir", json={"resultado": TEXTO_CLINICO})
    assert resp.status_code == 200
    conclusoes = _dashboard(cenario.admin, cenario.tipo["id"])["conclusoes"]
    assert conclusoes["concluidas"] == 1 and conclusoes["no_prazo"] == 0


# --- Alcance por unidade -----------------------------------------------------------------


@pytest.mark.parametrize("perfil", ["Navegador", "Gestor do Cuidado"])
def test_perfil_local_so_conta_a_propria_unidade(
    logar: Logar,  # noqa: F811
    cenario: Cenario,  # noqa: F811
    fabrica_sessao: Fabrica,
    settings_integracao: Settings,
    perfil: str,
) -> None:
    admin, tipo = cenario.admin, cenario.tipo["id"]
    _abrir(cenario)
    _abrir(cenario, cpf=_novo_paciente(admin), id_unidade=cenario.outra_unidade["id"])
    local = _na_unidade(logar(perfil), cenario.unidade["id"], fabrica_sessao, settings_integracao)

    assert _dashboard(admin, tipo)["abertas"]["em_aberto"] == 2
    corpo = _dashboard(local, tipo)

    assert corpo["alcance"] == "unidade"
    assert corpo["abertas"]["em_aberto"] == 1 and corpo["abertas_no_periodo"] == 1
    assert [g["nome"] for g in corpo["por_unidade"]] == [cenario.unidade["nome"]]
    assert corpo["etapas"]["agendado"] == 1
    assert cenario.outra_unidade["nome"] not in str(corpo)


def test_filtrar_outra_unidade_nao_amplia_o_alcance(
    logar: Logar,  # noqa: F811
    cenario: Cenario,  # noqa: F811
    fabrica_sessao: Fabrica,
    settings_integracao: Settings,
) -> None:
    tipo = cenario.tipo["id"]
    _abrir(cenario, id_unidade=cenario.outra_unidade["id"])
    local = _na_unidade(
        logar("Navegador"), cenario.unidade["id"], fabrica_sessao, settings_integracao
    )
    corpo = _dashboard(local, tipo, id_unidade=cenario.outra_unidade["id"])
    assert corpo["abertas"]["em_aberto"] == 0 and corpo["por_unidade"] == []
    assert sum(p["abertas"] for p in corpo["serie"]) == 0


def test_filtro_de_unidade_do_gestor(logar: Logar, cenario: Cenario) -> None:  # noqa: F811
    tipo = cenario.tipo["id"]
    _abrir(cenario)
    _abrir(cenario, cpf=_novo_paciente(cenario.admin), id_unidade=cenario.outra_unidade["id"])
    gestor = logar("Gestor").api
    assert _dashboard(gestor, tipo)["abertas"]["em_aberto"] == 2
    filtrado = _dashboard(gestor, tipo, id_unidade=cenario.unidade["id"])
    assert filtrado["abertas"]["em_aberto"] == 1
    assert [g["nome"] for g in filtrado["por_unidade"]] == [cenario.unidade["nome"]]


def test_unidade_que_recebeu_etapa_conta_a_oci_mas_so_a_propria_etapa(
    logar: Logar,  # noqa: F811
    cenario: Cenario,  # noqa: F811
    fabrica_sessao: Fabrica,
    settings_integracao: Settings,
) -> None:
    oci = _abrir(cenario)
    etapa = {
        "id_unidade": cenario.outra_unidade["id"],
        "id_servico": cenario.servico["id"],
        "data_hora": _quando(dias=2),
    }
    resp = cenario.admin.post(f"/ocis/{oci['id']}/navegacoes", json=etapa)
    assert resp.status_code == 201, resp.text
    destino = _na_unidade(
        logar("Navegador"), cenario.outra_unidade["id"], fabrica_sessao, settings_integracao
    )
    corpo = _dashboard(destino, cenario.tipo["id"])
    assert corpo["abertas"]["em_aberto"] == 1
    assert corpo["etapas"]["agendado"] == 1  # a outra etapa é da unidade de origem
    assert [g["nome"] for g in corpo["por_unidade"]] == [cenario.outra_unidade["nome"]]


def test_usuario_sem_unidade_nao_ve_nada(
    logar: Logar,  # noqa: F811
    cenario: Cenario,  # noqa: F811
) -> None:
    _abrir(cenario)
    corpo = _dashboard(logar("Navegador").api, cenario.tipo["id"])
    assert corpo["alcance"] == "nenhuma"
    assert corpo["abertas"]["em_aberto"] == 0 and corpo["serie"] == []


# --- Sem dado de paciente, e auditado ----------------------------------------------------


def test_resposta_nao_identifica_paciente_nem_oci(cenario: Cenario) -> None:  # noqa: F811
    oci = _abrir(cenario)
    resp = cenario.admin.post("/ocis/dashboard", json={"id_tipo_oci": cenario.tipo["id"]})
    assert resp.headers["cache-control"] == "no-store"
    for dado in (cenario.cpf, "Paciente da OCI", oci["id"], oci["cid"]["id"]):
        assert dado not in resp.text


def test_consulta_fica_no_log_so_com_os_filtros(
    cenario: Cenario,  # noqa: F811
    fabrica_sessao: Fabrica,
) -> None:
    _abrir(cenario)
    tipo = cenario.tipo["id"]
    _dashboard(cenario.admin, tipo, dias=30)
    registro = _ultimo(fabrica_sessao, "oci_dashboard_read")
    assert registro.resumo_acessado == {
        "recurso": "dashboard_oci",
        "dias": 30,
        "id_tipo_oci": tipo,
        "id_unidade": None,
    }
    assert registro.cpf_usuario_hash is not None
    assert registro.cpf_paciente_hash is None and registro.id_oci is None
