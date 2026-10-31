"""RF-12 / THREAT_MODEL E1, E2, T4, I1, R1: OCI e navegação, com alcance por unidade (ADR-0025)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.cpf import formatar_cpf
from app.core.crypto import FinalidadeHash, hash_busca
from app.models import Cid, Log, Oci, Paciente, Usuario

from .conftest import gerar_cpf
from .test_cadastros import _cid, _servico, _tipo_oci, _unidade
from .test_pacientes import Logado, Logar, logar  # noqa: F401

Fabrica = sessionmaker[Session]
Conn = psycopg.Connection[tuple[object, ...]]
TEXTO_CLINICO = "Laudo sigiloso de teste"


class Cenario(NamedTuple):
    admin: TestClient
    tipo: dict[str, Any]
    cid: dict[str, Any]
    servico: dict[str, Any]
    unidade: dict[str, Any]
    outra_unidade: dict[str, Any]
    cpf: str


def _quando(dias: int = 1) -> str:
    return (datetime.now(UTC) + timedelta(days=dias)).isoformat()


def _novo_paciente(admin: TestClient) -> str:
    cpf = gerar_cpf()
    corpo = {"cpf": cpf, "nome": "Paciente da OCI", "data_nascimento": "1980-01-01"}
    assert admin.post("/pacientes", json=corpo).status_code == 201
    return cpf


@pytest.fixture
def cenario(logar: Logar) -> Cenario:  # noqa: F811
    admin = logar("Administrador").api
    cid = admin.post("/cids", json=_cid()).json()
    tipo = admin.post("/tipos-oci", json=_tipo_oci(cids=[cid["id"]])).json()
    servico = admin.post("/servicos", json=_servico()).json()
    unidade = admin.post("/unidades", json=_unidade(servicos=[servico["id"]])).json()
    outra = admin.post("/unidades", json=_unidade(servicos=[servico["id"]])).json()
    return Cenario(admin, tipo, cid, servico, unidade, outra, _novo_paciente(admin))


def _corpo(c: Cenario, **extra: object) -> dict[str, object]:
    return {
        "cpf": c.cpf,
        "id_tipo_oci": c.tipo["id"],
        "cid": c.cid["id"],
        "id_unidade": c.unidade["id"],
        "id_servico": c.servico["id"],
        "data_hora": _quando(),
        **extra,
    }


def _abrir(c: Cenario, api: TestClient | None = None, **extra: object) -> dict[str, Any]:
    resp = (api or c.admin).post("/ocis", json=_corpo(c, **extra))
    assert resp.status_code == 201, resp.text
    corpo: dict[str, Any] = resp.json()
    return corpo


def _na_unidade(
    logado: Logado, id_unidade: int, fabrica: Fabrica, settings: Settings
) -> TestClient:
    cpf_hash = hash_busca(settings.chave_hmac, FinalidadeHash.CPF, logado.cpf)
    with fabrica() as db, db.begin():
        usuario = db.get(Usuario, cpf_hash)
        assert usuario is not None
        usuario.id_unidade = id_unidade
    return logado.api


def _ultimo(fabrica: Fabrica, acao: str) -> Log:
    with fabrica() as db:
        return db.scalars(
            select(Log).where(Log.acao == acao).order_by(Log.seq_cadeia.desc()).limit(1)
        ).one()


# --- Permissões --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("perfil", "ler", "criar", "editar", "concluir"),
    [
        ("Administrador", 200, 201, 200, 200),
        ("Gestor", 200, 403, 403, 403),
        ("Gestor do Cuidado", 200, 403, 403, 403),
        ("Navegador", 200, 201, 200, 200),
        ("Auditor", 403, 403, 403, 403),
        (None, 403, 403, 403, 403),
    ],
)
def test_matriz_de_permissoes(
    logar: Logar,  # noqa: F811
    cenario: Cenario,
    fabrica_sessao: Fabrica,
    settings_integracao: Settings,
    perfil: str | None,
    ler: int,
    criar: int,
    editar: int,
    concluir: int,
) -> None:
    api = _na_unidade(logar(perfil), cenario.unidade["id"], fabrica_sessao, settings_integracao)
    oci = _abrir(cenario)
    url = f"/ocis/{oci['id']}"
    assert api.post("/ocis/lista", json={}).status_code == ler
    assert api.get("/ocis/opcoes").status_code == ler
    assert api.get(url).status_code == ler
    outra = _novo_paciente(cenario.admin)
    assert api.post("/ocis", json=_corpo(cenario, cpf=outra)).status_code == criar
    assert api.patch(url, json={"cid": cenario.cid["id"]}).status_code == editar
    corpo = {"resultado": "Concluída no teste"}
    assert api.post(f"{url}/concluir", json=corpo).status_code == concluir


def test_sem_token_csrf_e_recusado(cenario: Cenario) -> None:
    del cenario.admin.headers["X-CSRF-Token"]
    assert cenario.admin.post("/ocis", json=_corpo(cenario)).status_code == 403


# --- Alcance por unidade -----------------------------------------------------------------


def test_navegador_so_alcanca_a_propria_unidade(
    logar: Logar,  # noqa: F811
    cenario: Cenario,
    fabrica_sessao: Fabrica,
    settings_integracao: Settings,
) -> None:
    oci = _abrir(cenario)
    daqui = _na_unidade(
        logar("Navegador"), cenario.unidade["id"], fabrica_sessao, settings_integracao
    )
    de_fora = _na_unidade(
        logar("Navegador"), cenario.outra_unidade["id"], fabrica_sessao, settings_integracao
    )
    assert daqui.get(f"/ocis/{oci['id']}").status_code == 200
    assert oci["id"] in {i["id"] for i in daqui.post("/ocis/lista", json={}).json()["itens"]}

    # Fora do alcance, a resposta é igual à de uma OCI que não existe.
    resp = de_fora.get(f"/ocis/{oci['id']}")
    assert resp.status_code == 404
    assert resp.json() == de_fora.get(f"/ocis/{uuid.uuid4()}").json()
    assert oci["id"] not in {i["id"] for i in de_fora.post("/ocis/lista", json={}).json()["itens"]}
    evento = _ultimo(fabrica_sessao, "access_denied")
    assert evento.resumo_acessado["motivo"] == "fora_da_unidade"

    for resposta in (
        de_fora.patch(f"/ocis/{oci['id']}", json={"cid": cenario.cid["id"]}),
        de_fora.post(f"/ocis/{oci['id']}/concluir", json={"resultado": "Tentativa"}),
        de_fora.post(f"/ocis/{oci['id']}/cancelar"),
        de_fora.post(
            f"/ocis/{oci['id']}/navegacoes",
            json={
                "id_unidade": cenario.outra_unidade["id"],
                "id_servico": cenario.servico["id"],
                "data_hora": _quando(),
            },
        ),
    ):
        assert resposta.status_code == 404
    assert cenario.admin.get(f"/ocis/{oci['id']}").json()["status"] == "aberta"


def test_sem_unidade_nao_alcanca_nada(logar: Logar, cenario: Cenario) -> None:  # noqa: F811
    oci = _abrir(cenario)
    api = logar("Navegador").api
    assert api.post("/ocis/lista", json={}).json() == {"itens": [], "proximo": None}
    assert api.get(f"/ocis/{oci['id']}").status_code == 404
    assert api.post("/ocis", json=_corpo(cenario)).status_code == 403
    assert api.get("/ocis/opcoes").json()["unidades_abertura"] == []


def test_so_abre_na_propria_unidade(
    logar: Logar,  # noqa: F811
    cenario: Cenario,
    fabrica_sessao: Fabrica,
    settings_integracao: Settings,
) -> None:
    api = _na_unidade(
        logar("Navegador"), cenario.unidade["id"], fabrica_sessao, settings_integracao
    )
    resp = api.post("/ocis", json=_corpo(cenario, id_unidade=cenario.outra_unidade["id"]))
    assert resp.status_code == 403
    assert resp.json() == {"detail": "Acesso negado."}
    opcoes = api.get("/ocis/opcoes").json()
    assert {u["id"] for u in opcoes["unidades_abertura"]} == {cenario.unidade["id"]}
    assert cenario.outra_unidade["id"] in {u["id"] for u in opcoes["unidades"]}
    _abrir(cenario, api)


def test_encaminhar_abre_o_acesso_a_outra_unidade_e_cada_uma_marca_a_sua_etapa(
    logar: Logar,  # noqa: F811
    cenario: Cenario,
    fabrica_sessao: Fabrica,
    settings_integracao: Settings,
) -> None:
    origem = _na_unidade(
        logar("Navegador"), cenario.unidade["id"], fabrica_sessao, settings_integracao
    )
    destino = _na_unidade(
        logar("Navegador"), cenario.outra_unidade["id"], fabrica_sessao, settings_integracao
    )
    oci = _abrir(cenario, origem)
    url = f"/ocis/{oci['id']}"
    assert destino.get(url).status_code == 404

    corpo = origem.post(
        f"{url}/navegacoes",
        json={
            "id_unidade": cenario.outra_unidade["id"],
            "id_servico": cenario.servico["id"],
            "data_hora": _quando(5),
        },
    )
    assert corpo.status_code == 201
    etapas = {e["id_unidade"]: e for e in corpo.json()["navegacoes"]}
    assert etapas[cenario.unidade["id"]]["pode_marcar"] is True
    assert etapas[cenario.outra_unidade["id"]]["pode_marcar"] is False

    assert destino.get(url).status_code == 200
    etapa_origem = etapas[cenario.unidade["id"]]["id"]
    etapa_destino = etapas[cenario.outra_unidade["id"]]["id"]
    negado = destino.patch(f"{url}/navegacoes/{etapa_origem}", json={"status": "realizado"})
    assert negado.status_code == 403
    certo = destino.patch(f"{url}/navegacoes/{etapa_destino}", json={"status": "realizado"})
    assert certo.status_code == 200
    assert {e["status"] for e in certo.json()["navegacoes"]} == {"agendado", "realizado"}


def test_mudanca_de_unidade_vale_na_proxima_requisicao(
    logar: Logar,  # noqa: F811
    cenario: Cenario,
    fabrica_sessao: Fabrica,
    settings_integracao: Settings,
) -> None:
    oci = _abrir(cenario)
    logado = logar("Gestor do Cuidado")
    api = _na_unidade(logado, cenario.unidade["id"], fabrica_sessao, settings_integracao)
    assert api.get(f"/ocis/{oci['id']}").status_code == 200
    _na_unidade(logado, cenario.outra_unidade["id"], fabrica_sessao, settings_integracao)
    assert api.get(f"/ocis/{oci['id']}").status_code == 404


def test_gestor_ve_tudo_sem_estar_na_unidade(logar: Logar, cenario: Cenario) -> None:  # noqa: F811
    oci = _abrir(cenario)
    assert logar("Gestor").api.get(f"/ocis/{oci['id']}").status_code == 200


# --- Abertura ----------------------------------------------------------------------------


def test_abertura_grava_prazo_e_primeira_etapa(cenario: Cenario) -> None:
    corpo = _abrir(cenario)
    assert corpo["status"] == "aberta" and corpo["atrasada"] is False
    assert corpo["tipo_oci"] == cenario.tipo["tipo_oci"]
    assert corpo["cid"]["cid"] == cenario.cid["cid"]
    assert corpo["paciente_nome"] == "Paciente da OCI"
    assert corpo["cpf_mascarado"] == f"***.{cenario.cpf[3:6]}.{cenario.cpf[6:9]}-**"
    assert cenario.cpf not in str(corpo) and formatar_cpf(cenario.cpf) not in str(corpo)
    prazo = datetime.fromisoformat(corpo["prazo_em"])
    assert (prazo - datetime.now(UTC)).days in (29, 30)  # prazo de 30 dias do tipo
    assert [e["status"] for e in corpo["navegacoes"]] == ["agendado"]
    assert corpo["navegacoes"][0]["unidade"] == cenario.unidade["nome"]


def test_mudar_o_prazo_do_tipo_nao_altera_oci_aberta(cenario: Cenario) -> None:
    oci = _abrir(cenario)
    assert (
        cenario.admin.patch(
            f"/tipos-oci/{cenario.tipo['id']}", json={"prazo_diagnostico": 365}
        ).status_code
        == 200
    )
    assert cenario.admin.get(f"/ocis/{oci['id']}").json()["prazo_em"] == oci["prazo_em"]


def test_uma_oci_aberta_por_paciente_e_tipo(cenario: Cenario) -> None:
    oci = _abrir(cenario)
    resp = cenario.admin.post("/ocis", json=_corpo(cenario))
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Este paciente já tem uma OCI aberta deste tipo."}
    assert cenario.admin.post(f"/ocis/{oci['id']}/cancelar").status_code == 200
    _abrir(cenario)


def _invalidos(c: Cenario) -> dict[str, dict[str, object]]:
    return {
        "paciente": {"cpf": gerar_cpf()},
        "tipo": {"id_tipo_oci": 2_000_000},
        "cid": {"cid": "0" * 64},
        "unidade": {"id_unidade": 2_000_000},
        "servico": {"id_servico": 2_000_000},
    }


@pytest.mark.parametrize(
    ("campo", "mensagem"),
    [
        ("paciente", "Paciente não encontrado ou inativo."),
        ("tipo", "Tipo de unidade inválido."),
        ("cid", "CID inválido."),
        ("unidade", "Unidade inválida."),
        ("servico", "Serviço inválido."),
    ],
)
def test_referencia_inexistente_e_recusada(cenario: Cenario, campo: str, mensagem: str) -> None:
    resp = cenario.admin.post("/ocis", json=_corpo(cenario, **_invalidos(cenario)[campo]))
    assert resp.status_code == 422
    assert resp.json() == {"detail": mensagem}


def test_cid_de_outro_tipo_e_servico_nao_oferecido_sao_recusados(cenario: Cenario) -> None:
    admin = cenario.admin
    outro_cid = admin.post("/cids", json=_cid()).json()
    assert admin.post("/ocis", json=_corpo(cenario, cid=outro_cid["id"])).status_code == 422
    outro_servico = admin.post("/servicos", json=_servico()).json()
    resp = admin.post("/ocis", json=_corpo(cenario, id_servico=outro_servico["id"]))
    assert resp.status_code == 422


def test_paciente_inativo_nao_abre_oci(cenario: Cenario, fabrica_sessao: Fabrica) -> None:
    corpo = {"cpf": cenario.cpf}
    paciente = cenario.admin.post("/pacientes/busca", json=corpo).json()
    assert cenario.admin.delete(f"/pacientes/{paciente['id']}").status_code == 204
    assert cenario.admin.post("/ocis", json=_corpo(cenario)).status_code == 422


@pytest.mark.parametrize(
    "extra",
    [
        {"cpf": "111.111.111-11"},
        {"cid": "' OR 1=1 --"},
        {"id_unidade": 0},
        {"data_hora": "amanhã"},
        {"data_hora": "2026-11-01T10:00:00"},  # sem fuso
        {"data_hora": "2090-01-01T10:00:00Z"},
        {"status": "concluida"},
        {"prazo_em": "2026-11-01T10:00:00Z"},
    ],
)
def test_entrada_invalida(cenario: Cenario, extra: dict[str, object]) -> None:
    resp = cenario.admin.post("/ocis", json=_corpo(cenario, **extra))
    assert resp.status_code == 422
    assert "OR 1=1" not in resp.text and "111.111.111-11" not in resp.text


# --- Navegação ---------------------------------------------------------------------------


def test_etapa_muda_uma_vez_e_pode_ser_reagendada(cenario: Cenario) -> None:
    oci = _abrir(cenario)
    etapa = oci["navegacoes"][0]["id"]
    url = f"/ocis/{oci['id']}/navegacoes/{etapa}"
    nova = _quando(9)
    corpo = cenario.admin.patch(url, json={"data_hora": nova}).json()
    assert datetime.fromisoformat(corpo["navegacoes"][0]["data_hora"]) == datetime.fromisoformat(
        nova
    )
    corpo = cenario.admin.patch(url, json={"status": "faltou"}).json()
    assert corpo["navegacoes"][0]["status"] == "faltou"
    assert corpo["navegacoes"][0]["pode_marcar"] is False
    resp = cenario.admin.patch(url, json={"status": "realizado"})
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Esta etapa já foi encerrada: registre uma nova."}


@pytest.mark.parametrize("corpo", [{}, {"status": "agendado"}, {"status": "inventado"}])
def test_alteracao_de_etapa_invalida(cenario: Cenario, corpo: dict[str, object]) -> None:
    oci = _abrir(cenario)
    url = f"/ocis/{oci['id']}/navegacoes/{oci['navegacoes'][0]['id']}"
    assert cenario.admin.patch(url, json=corpo).status_code == 422


def test_etapa_de_outra_oci_nao_e_alcancada(cenario: Cenario) -> None:
    a = _abrir(cenario)
    b = _abrir(cenario, cpf=_novo_paciente(cenario.admin))
    url = f"/ocis/{a['id']}/navegacoes/{b['navegacoes'][0]['id']}"
    assert cenario.admin.patch(url, json={"status": "realizado"}).status_code == 404


def test_encaminhamento_exige_servico_oferecido_pela_unidade(cenario: Cenario) -> None:
    oci = _abrir(cenario)
    outro = cenario.admin.post("/servicos", json=_servico()).json()
    resp = cenario.admin.post(
        f"/ocis/{oci['id']}/navegacoes",
        json={
            "id_unidade": cenario.unidade["id"],
            "id_servico": outro["id"],
            "data_hora": _quando(),
        },
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "Serviço inválido."}


# --- Encerramento ------------------------------------------------------------------------


def test_conclusao_cifra_o_resultado_e_encerra(cenario: Cenario, fabrica_sessao: Fabrica) -> None:
    oci = _abrir(cenario)
    url = f"/ocis/{oci['id']}"
    resp = cenario.admin.post(
        f"{url}/concluir", json={"resultado": TEXTO_CLINICO, "resultado_cid": cenario.cid["id"]}
    )
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["status"] == "concluida" and corpo["resultado"] == TEXTO_CLINICO
    assert corpo["resultado_cid"]["cid"] == cenario.cid["cid"]
    assert corpo["atrasada"] is False

    with fabrica_sessao() as db:
        registro = db.scalars(select(Oci).where(Oci.id_publico == uuid.UUID(oci["id"]))).one()
        assert registro.resultado_cripto is not None and registro.dek_cripto is not None
        assert TEXTO_CLINICO.encode() not in registro.resultado_cripto

    for resposta in (
        cenario.admin.post(f"{url}/concluir", json={"resultado": "De novo"}),
        cenario.admin.post(f"{url}/cancelar"),
        cenario.admin.patch(url, json={"cid": cenario.cid["id"]}),
        cenario.admin.post(
            f"{url}/navegacoes",
            json={
                "id_unidade": cenario.unidade["id"],
                "id_servico": cenario.servico["id"],
                "data_hora": _quando(),
            },
        ),
        cenario.admin.patch(
            f"{url}/navegacoes/{oci['navegacoes'][0]['id']}", json={"status": "realizado"}
        ),
    ):
        assert resposta.status_code == 409
        assert resposta.json() == {"detail": "Esta OCI já foi encerrada."}


@pytest.mark.parametrize(
    "corpo",
    [{}, {"resultado": "x"}, {"resultado": "a\x00b"}, {"resultado": "ok ok", "resultado_cid": "1"}],
)
def test_conclusao_invalida(cenario: Cenario, corpo: dict[str, object]) -> None:
    oci = _abrir(cenario)
    assert cenario.admin.post(f"/ocis/{oci['id']}/concluir", json=corpo).status_code == 422


def test_conclusao_com_cid_inexistente(cenario: Cenario) -> None:
    oci = _abrir(cenario)
    resp = cenario.admin.post(
        f"/ocis/{oci['id']}/concluir", json={"resultado": "Texto", "resultado_cid": "0" * 64}
    )
    assert resp.status_code == 422
    assert cenario.admin.get(f"/ocis/{oci['id']}").json()["status"] == "aberta"


def test_trocar_cid_so_entre_os_do_tipo(cenario: Cenario) -> None:
    oci = _abrir(cenario)
    url = f"/ocis/{oci['id']}"
    outro = cenario.admin.post("/cids", json=_cid()).json()
    assert cenario.admin.patch(url, json={"cid": outro["id"]}).status_code == 422
    cenario.admin.patch(
        f"/tipos-oci/{cenario.tipo['id']}", json={"cids": [cenario.cid["id"], outro["id"]]}
    )
    corpo = cenario.admin.patch(url, json={"cid": outro["id"]}).json()
    assert corpo["cid"]["cid"] == outro["cid"]


# --- Lista -------------------------------------------------------------------------------


def test_filtros_da_lista(cenario: Cenario) -> None:
    admin = cenario.admin
    aberta = _abrir(cenario)
    outro_cpf = _novo_paciente(admin)
    cancelada = _abrir(cenario, cpf=outro_cpf, id_unidade=cenario.outra_unidade["id"])
    admin.post(f"/ocis/{cancelada['id']}/cancelar")

    def ids(**corpo: object) -> set[str]:
        return {i["id"] for i in admin.post("/ocis/lista", json=corpo).json()["itens"]}

    tipo = cenario.tipo["id"]
    assert ids(id_tipo_oci=tipo) == {aberta["id"], cancelada["id"]}
    assert ids(id_tipo_oci=tipo, status="cancelada") == {cancelada["id"]}
    assert ids(id_tipo_oci=tipo, id_unidade=cenario.unidade["id"]) == {aberta["id"]}
    assert ids(cpf=formatar_cpf(outro_cpf)) == {cancelada["id"]}
    assert ids(cpf=gerar_cpf()) == set()


def test_atrasada_na_lista_e_no_filtro(cenario: Cenario, monkeypatch: pytest.MonkeyPatch) -> None:
    oci = _abrir(cenario)
    tipo = cenario.tipo["id"]
    corpo = {"id_tipo_oci": tipo, "atrasadas": True}
    assert cenario.admin.post("/ocis/lista", json=corpo).json()["itens"] == []
    daqui_a_dois_meses = datetime.now(UTC) + timedelta(days=60)
    monkeypatch.setattr("app.api.ocis.agora", lambda: daqui_a_dois_meses)
    itens = cenario.admin.post("/ocis/lista", json=corpo).json()["itens"]
    assert [i["id"] for i in itens] == [oci["id"]] and itens[0]["atrasada"] is True
    assert cenario.admin.get(f"/ocis/{oci['id']}").json()["atrasada"] is True


def test_lista_percorre_as_paginas_sem_repetir(cenario: Cenario) -> None:
    admin = cenario.admin
    criadas = {_abrir(cenario, cpf=_novo_paciente(admin))["id"] for _ in range(22)}
    vistas: list[str] = []
    corpo: dict[str, object] = {"id_tipo_oci": cenario.tipo["id"]}
    while True:
        pagina = admin.post("/ocis/lista", json=corpo).json()
        assert len(pagina["itens"]) <= 20
        vistas += [i["id"] for i in pagina["itens"]]
        if pagina["proximo"] is None:
            break
        corpo["depois"] = pagina["proximo"]
    assert len(vistas) == len(set(vistas)) and set(vistas) == criadas


def test_lista_com_cursor_desconhecido(cenario: Cenario) -> None:
    resp = cenario.admin.post("/ocis/lista", json={"depois": str(uuid.uuid4())})
    assert resp.json() == {"itens": [], "proximo": None}


@pytest.mark.parametrize(
    "corpo",
    [{"status": "x"}, {"id_tipo_oci": 0}, {"cpf": "123"}, {"atrasadas": "talvez"}, {"limite": 9}],
)
def test_lista_recusa_entrada_invalida(cenario: Cenario, corpo: dict[str, object]) -> None:
    assert cenario.admin.post("/ocis/lista", json=corpo).status_code == 422


def test_paciente_ilegivel_nao_derruba_a_lista(
    cenario: Cenario, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    oci = _abrir(cenario)
    chave = hash_busca(settings_integracao.chave_hmac, FinalidadeHash.CPF, cenario.cpf)
    with fabrica_sessao() as db, db.begin():
        paciente = db.get(Paciente, chave)
        assert paciente is not None
        paciente.nome_cripto = b"adulterado" * 8
    resp = cenario.admin.post("/ocis/lista", json={"id_tipo_oci": cenario.tipo["id"]})
    assert resp.status_code == 200
    item = resp.json()["itens"][0]
    assert item["id"] == oci["id"] and item["paciente_nome"] is None
    assert item["cpf_mascarado"] is None


# --- Opções ------------------------------------------------------------------------------


def test_opcoes_trazem_so_o_que_esta_ativo(cenario: Cenario, fabrica_sessao: Fabrica) -> None:
    admin = cenario.admin
    outro = admin.post("/cids", json=_cid()).json()
    admin.patch(f"/tipos-oci/{cenario.tipo['id']}", json={"cids": [cenario.cid["id"], outro["id"]]})
    # CID em uso não inativa pela API: simula um que saiu de uso depois do vínculo.
    with fabrica_sessao() as db, db.begin():
        registro = db.get(Cid, bytes.fromhex(outro["id"]))
        assert registro is not None
        registro.status = "inativo"
    url = f"/ocis/opcoes/tipos/{cenario.tipo['id']}/cids"
    assert [c["id"] for c in admin.get(url).json()["cids"]] == [cenario.cid["id"]]
    url = f"/ocis/opcoes/unidades/{cenario.unidade['id']}/servicos"
    assert admin.get(url).json()["servicos"] == [
        {"id": cenario.servico["id"], "nome": cenario.servico["nome"]}
    ]
    opcoes = admin.get("/ocis/opcoes").json()
    assert {"id": cenario.tipo["id"], "nome": cenario.tipo["tipo_oci"]} in opcoes["tipos"]


# --- Cadastros em uso --------------------------------------------------------------------


def test_cadastros_em_uso_nao_podem_ser_inativados(cenario: Cenario) -> None:
    admin = cenario.admin
    oci = _abrir(cenario)
    urls = {
        f"/tipos-oci/{cenario.tipo['id']}": "OCIs abertas deste tipo",
        f"/unidades/{cenario.unidade['id']}": "etapas agendadas nesta unidade",
    }
    for url, mensagem in urls.items():
        resp = admin.delete(url)
        assert resp.status_code == 409
        assert mensagem in resp.json()["detail"]
    paciente = admin.post("/pacientes/busca", json={"cpf": cenario.cpf}).json()
    resp = admin.delete(f"/pacientes/{paciente['id']}")
    assert resp.status_code == 409
    assert "OCI aberta" in resp.json()["detail"]

    admin.post(f"/ocis/{oci['id']}/cancelar")
    assert admin.delete(f"/tipos-oci/{cenario.tipo['id']}").status_code == 204
    assert admin.delete(f"/pacientes/{paciente['id']}").status_code == 204


def test_cid_e_servico_em_uso_por_oci_mesmo_fora_dos_vinculos(cenario: Cenario) -> None:
    admin = cenario.admin
    oci = _abrir(cenario)
    admin.patch(f"/tipos-oci/{cenario.tipo['id']}", json={"cids": []})
    resp = admin.delete(f"/cids/{cenario.cid['id']}")
    assert resp.status_code == 409 and "OCIs abertas com este CID" in resp.json()["detail"]
    for unidade in (cenario.unidade, cenario.outra_unidade):
        admin.patch(f"/unidades/{unidade['id']}", json={"servicos": []})
    resp = admin.delete(f"/servicos/{cenario.servico['id']}")
    assert resp.status_code == 409 and "etapas agendadas com este serviço" in resp.json()["detail"]
    admin.post(f"/ocis/{oci['id']}/cancelar")
    assert admin.delete(f"/cids/{cenario.cid['id']}").status_code == 204
    assert admin.delete(f"/servicos/{cenario.servico['id']}").status_code == 204


# --- Auditoria e banco -------------------------------------------------------------------


def test_eventos_com_autor_paciente_e_oci_e_sem_dado_clinico(
    cenario: Cenario, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    admin = cenario.admin
    oci = _abrir(cenario)
    url = f"/ocis/{oci['id']}"
    admin.get(url)
    admin.post(
        f"{url}/navegacoes",
        json={
            "id_unidade": cenario.outra_unidade["id"],
            "id_servico": cenario.servico["id"],
            "data_hora": _quando(),
        },
    )
    admin.patch(f"{url}/navegacoes/{oci['navegacoes'][0]['id']}", json={"status": "realizado"})
    admin.post(f"{url}/concluir", json={"resultado": TEXTO_CLINICO})

    with fabrica_sessao() as db:
        registro = db.scalars(select(Oci).where(Oci.id_publico == uuid.UUID(oci["id"]))).one()
        eventos = list(
            db.scalars(select(Log).where(Log.id_oci == registro.id_oci).order_by(Log.seq_cadeia))
        )
    assert [e.acao for e in eventos] == [
        "oci_created",
        "sensitive_data_access",
        "navigation_created",
        "navigation_updated",
        "oci_concluded",
    ]
    chave = hash_busca(settings_integracao.chave_hmac, FinalidadeHash.CPF, cenario.cpf)
    assert all(e.cpf_paciente_hash == chave and e.cpf_usuario_hash is not None for e in eventos)
    texto = " ".join(str(e.resumo_acessado) for e in eventos)
    assert TEXTO_CLINICO not in texto and cenario.cid["cid"] not in texto
    assert cenario.cid["descricao"] not in texto and cenario.cpf not in texto


def test_lista_auditada_sem_o_cpf_filtrado(cenario: Cenario, fabrica_sessao: Fabrica) -> None:
    oci = _abrir(cenario)
    cenario.admin.post("/ocis/lista", json={"cpf": cenario.cpf})
    resumo = _ultimo(fabrica_sessao, "sensitive_data_access").resumo_acessado
    assert resumo["recurso"] == "oci" and resumo["origem"] == "lista"
    assert resumo["ocis"] == [oci["id"]] and len(resumo["paciente"]) == 12
    assert cenario.cpf not in str(resumo)


def test_cadeia_do_log_continua_integra_com_id_oci(
    cenario: Cenario,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings_integracao: Settings,
) -> None:
    from scripts import tarefas

    _abrir(cenario)
    monkeypatch.setattr(tarefas, "get_settings", lambda: settings_integracao)
    tarefas.main(["verificar-log"])
    assert "Cadeia íntegra" in capsys.readouterr().out


def test_consulta_do_log_mostra_a_oci(cenario: Cenario) -> None:
    oci = _abrir(cenario)
    item = cenario.admin.post("/logs/consulta", json={"acao": "oci_created"}).json()["itens"][0]
    assert item["id_oci"] is not None and item["paciente_cpf"] == formatar_cpf(cenario.cpf)
    assert oci["id"] not in str(item["resumo"])


@pytest.mark.parametrize(
    "comando",
    [
        sql.SQL("DELETE FROM app.oci"),
        sql.SQL("DELETE FROM app.oci_navegacao"),
        sql.SQL("UPDATE app.oci SET prazo_em = now()"),
        sql.SQL("UPDATE app.oci SET cpf_paciente_hash = cpf_paciente_hash"),
        sql.SQL("UPDATE app.oci_navegacao SET id_oci = id_oci"),
        sql.SQL("UPDATE app.oci_navegacao SET id_unidade = id_unidade"),
    ],
)
def test_app_user_nao_apaga_nem_altera_o_que_e_fixo(app_conn: Conn, comando: sql.SQL) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute(comando)
    app_conn.rollback()
