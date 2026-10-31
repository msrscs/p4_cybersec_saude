"""RF-12 / ADR-0026: agenda, vagas, marcação e remarcação."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.models import Log

from .test_cadastros import _cid, _servico, _tipo_oci, _unidade
from .test_ocis import (
    Cenario,
    _abrir,
    _agendas,
    _corpo,
    _na_unidade,
    _novo_paciente,
    _quando,
    cenario,  # noqa: F401
)
from .test_pacientes import Logar, logar  # noqa: F401

Fabrica = sessionmaker[Session]
FUSO = timezone(timedelta(hours=-3))


def _agenda(c: Cenario, **extra: object) -> dict[str, object]:
    return {
        "id_unidade": c.unidade["id"],
        "id_servico": c.servico["id"],
        "dia_semana": 0,
        "hora_inicio": "08:00",
        "hora_fim": "12:00",
        "duracao_minutos": 30,
        "vagas_por_horario": 2,
        **extra,
    }


def _alvo_novo(c: Cenario, vagas: int = 1) -> tuple[int, int]:
    """Unidade e serviço novos, com agenda em todos os dias, das 8h às 10h."""
    servico = c.admin.post("/servicos", json=_servico(cids=[c.cid["id"]])).json()
    unidade = c.admin.post("/unidades", json=_unidade(servicos=[servico["id"]])).json()
    for dia in range(7):
        corpo = _agenda(
            c,
            id_unidade=unidade["id"],
            id_servico=servico["id"],
            dia_semana=dia,
            hora_fim="10:00",
            vagas_por_horario=vagas,
        )
        assert c.admin.post("/agendas", json=corpo).status_code == 201
    return unidade["id"], servico["id"]


def _url_dias(id_unidade: int, id_servico: int) -> str:
    return f"/ocis/opcoes/unidades/{id_unidade}/servicos/{id_servico}/dias"


def _dia(dias: int = 1) -> str:
    return (datetime.now(FUSO) + timedelta(days=dias)).date().isoformat()


def _horarios(c: Cenario, id_unidade: int, id_servico: int, dia: str) -> dict[str, int]:
    url = f"{_url_dias(id_unidade, id_servico)}/{dia}/horarios"
    return {h["hora"]: h["vagas"] for h in c.admin.get(url).json()["horarios"]}


# --- Cadastro da agenda -------------------------------------------------------------------


def test_agenda_mostra_nomes_e_horarios(cenario: Cenario) -> None:  # noqa: F811
    unidade, servico = _alvo_novo(cenario)
    itens = cenario.admin.post(
        "/agendas/lista",
        json={"busca": cenario.admin.get("/servicos/opcoes").json()["opcoes"][0]["nome"]},
    )
    assert itens.status_code == 200
    corpo = cenario.admin.post("/agendas/lista", json={"pagina": 1}).json()
    assert corpo["itens"][0]["hora_inicio"] == "08:00"
    assert {"unidade", "servico", "dia_semana", "status"} <= corpo["itens"][0].keys()
    assert unidade and servico


@pytest.mark.parametrize(
    ("perfil", "ler", "escrever"),
    [
        ("Administrador", 200, 201),
        ("Navegador", 200, 403),
        ("Gestor", 200, 403),
        ("Auditor", 403, 403),
        (None, 403, 403),
    ],
)
def test_permissoes_da_agenda(
    logar: Logar,  # noqa: F811
    cenario: Cenario,  # noqa: F811
    perfil: str | None,
    ler: int,
    escrever: int,
) -> None:
    api = logar(perfil).api
    assert api.post("/agendas/lista", json={}).status_code == ler
    outra = cenario.admin.post("/unidades", json=_unidade(servicos=[cenario.servico["id"]])).json()
    resp = api.post("/agendas", json=_agenda(cenario, id_unidade=outra["id"]))
    assert resp.status_code == escrever


@pytest.mark.parametrize(
    "extra",
    [
        {"dia_semana": 7},
        {"dia_semana": -1},
        {"hora_inicio": "25:00"},
        {"hora_inicio": "10:00", "hora_fim": "09:00"},
        {"hora_inicio": "10:00", "hora_fim": "10:00"},
        {"hora_inicio": "08:00-03:00"},
        {"duracao_minutos": 4},
        {"duracao_minutos": 481},
        {"vagas_por_horario": 0},
        {"vagas_por_horario": 101},
        {"status": "inativo"},
    ],
)
def test_agenda_invalida(cenario: Cenario, extra: dict[str, object]) -> None:  # noqa: F811
    outra = cenario.admin.post("/unidades", json=_unidade(servicos=[cenario.servico["id"]])).json()
    corpo = _agenda(cenario, id_unidade=outra["id"], **extra)
    assert cenario.admin.post("/agendas", json=corpo).status_code == 422


def test_atendimento_precisa_caber_e_servico_precisa_ser_da_unidade(
    cenario: Cenario,  # noqa: F811
) -> None:
    admin = cenario.admin
    outra = admin.post("/unidades", json=_unidade(servicos=[cenario.servico["id"]])).json()
    corpo = _agenda(cenario, id_unidade=outra["id"], hora_fim="08:20")
    assert admin.post("/agendas", json=corpo).status_code == 422

    outro = admin.post("/servicos", json=_servico()).json()
    resp = admin.post("/agendas", json=_agenda(cenario, id_servico=outro["id"]))
    assert resp.status_code == 422 and resp.json() == {"detail": "Serviço inválido."}
    resp = admin.post("/agendas", json=_agenda(cenario, id_unidade=2_000_000))
    assert resp.status_code == 422 and resp.json() == {"detail": "Unidade inválida."}


def test_agenda_sobreposta_e_recusada_e_ajustavel(cenario: Cenario) -> None:  # noqa: F811
    admin = cenario.admin
    outra = admin.post("/unidades", json=_unidade(servicos=[cenario.servico["id"]])).json()
    base = {"id_unidade": outra["id"]}
    primeira = admin.post("/agendas", json=_agenda(cenario, **base)).json()
    resp = admin.post(
        "/agendas", json=_agenda(cenario, **base, hora_inicio="11:00", hora_fim="13:00")
    )
    assert resp.status_code == 409
    assert "Já existe agenda" in resp.json()["detail"]
    segunda = admin.post(
        "/agendas", json=_agenda(cenario, **base, hora_inicio="12:00", hora_fim="13:00")
    )
    assert segunda.status_code == 201  # encosta, sem sobrepor

    url = f"/agendas/{segunda.json()['id']}"
    assert admin.patch(url, json={"hora_inicio": "11:30"}).status_code == 409
    assert admin.patch(url, json={"hora_inicio": "13:30"}).status_code == 422
    assert admin.patch(url, json={"vagas_por_horario": 5}).json()["vagas_por_horario"] == 5
    assert admin.patch(f"/agendas/{primeira['id']}", json={}).status_code == 422
    assert admin.patch("/agendas/2000000", json={"vagas_por_horario": 5}).status_code == 404


def test_agenda_inativa_nao_conta_como_sobreposicao(cenario: Cenario) -> None:  # noqa: F811
    admin = cenario.admin
    outra = admin.post("/unidades", json=_unidade(servicos=[cenario.servico["id"]])).json()
    corpo = _agenda(cenario, id_unidade=outra["id"])
    primeira = admin.post("/agendas", json=corpo).json()
    assert admin.delete(f"/agendas/{primeira['id']}").status_code == 204
    assert admin.post("/agendas", json=corpo).status_code == 201


# --- CIDs do serviço ----------------------------------------------------------------------


def test_cids_do_servico_definem_o_conjunto_e_vao_para_o_log(
    cenario: Cenario,  # noqa: F811
    fabrica_sessao: Fabrica,
) -> None:
    admin = cenario.admin
    a = admin.post("/cids", json=_cid()).json()
    b = admin.post("/cids", json=_cid()).json()
    servico = admin.post("/servicos", json=_servico(cids=[a["id"]])).json()
    assert [c["cid"] for c in servico["cids"]] == [a["cid"]]
    url = f"/servicos/{servico['id']}"
    corpo = admin.patch(url, json={"cids": [b["id"]]}).json()
    assert [c["cid"] for c in corpo["cids"]] == [b["cid"]]
    with fabrica_sessao() as db:
        evento = db.scalars(
            select(Log)
            .where(Log.acao == "catalog_updated")
            .order_by(Log.seq_cadeia.desc())
            .limit(1)
        ).one()
    assert evento.resumo_acessado["cids_adicionados"] == [b["cid"]]
    assert evento.resumo_acessado["cids_removidos"] == [a["cid"]]
    assert admin.patch(url, json={"descricao": "Outra"}).json()["cids"][0]["cid"] == b["cid"]
    antes = admin.patch(url, json={"cids": [b["id"]]})
    assert antes.status_code == 200
    assert admin.patch(url, json={"cids": ["0" * 64]}).status_code == 422
    assert admin.post("/servicos", json=_servico(cids=["0" * 64])).status_code == 422


def test_cid_em_servico_ativo_nao_inativa(cenario: Cenario) -> None:  # noqa: F811
    admin = cenario.admin
    cid = admin.post("/cids", json=_cid()).json()
    servico = admin.post("/servicos", json=_servico(cids=[cid["id"]])).json()
    resp = admin.delete(f"/cids/{cid['id']}")
    assert resp.status_code == 409 and "serviços ativos com este CID" in resp.json()["detail"]
    admin.patch(f"/servicos/{servico['id']}", json={"cids": []})
    assert admin.delete(f"/cids/{cid['id']}").status_code == 204


# --- Unidades que atendem -----------------------------------------------------------------


def _ids_que_atendem(c: Cenario, cid: str) -> set[int]:
    corpo = c.admin.get(f"/ocis/opcoes/cids/{cid}/unidades").json()
    return {u["id"] for u in corpo["unidades"]}


def test_so_atende_quem_oferece_servico_do_cid_com_agenda(cenario: Cenario) -> None:  # noqa: F811
    admin = cenario.admin
    cid = cenario.cid["id"]
    assert _ids_que_atendem(cenario, cid) == {cenario.unidade["id"], cenario.outra_unidade["id"]}

    # Oferece o serviço, mas sem agenda.
    sem_agenda = admin.post("/unidades", json=_unidade(servicos=[cenario.servico["id"]])).json()
    assert sem_agenda["id"] not in _ids_que_atendem(cenario, cid)

    # Tem agenda de um serviço que não é deste CID.
    outro = admin.post("/servicos", json=_servico()).json()
    unidade = admin.post("/unidades", json=_unidade(servicos=[outro["id"]])).json()
    _agendas(admin, unidade["id"], outro["id"])
    assert unidade["id"] not in _ids_que_atendem(cenario, cid)

    corpo = admin.get(f"/ocis/opcoes/cids/{cid}/unidades").json()
    assert corpo["unidades"][0]["servicos"] == [
        {"id": cenario.servico["id"], "nome": cenario.servico["nome"]}
    ]


def test_unidade_ou_servico_inativo_deixa_de_atender(cenario: Cenario) -> None:  # noqa: F811
    admin = cenario.admin
    assert admin.delete(f"/unidades/{cenario.outra_unidade['id']}").status_code == 204
    assert _ids_que_atendem(cenario, cenario.cid["id"]) == {cenario.unidade["id"]}


@pytest.mark.parametrize("cid", ["abc", "' OR 1=1 --", "Z" * 64])
def test_cid_invalido_nas_unidades(cenario: Cenario, cid: str) -> None:  # noqa: F811
    assert cenario.admin.get(f"/ocis/opcoes/cids/{cid}/unidades").status_code == 422


# --- Dias e horários ----------------------------------------------------------------------


def test_dias_e_horarios_vem_da_agenda_e_so_mostram_o_que_tem_vaga(
    cenario: Cenario,  # noqa: F811
) -> None:
    unidade, servico = _alvo_novo(cenario)
    dias = cenario.admin.get(_url_dias(unidade, servico)).json()["dias"]
    amanha = next(d for d in dias if d["data"] == _dia())
    assert amanha["vagas"] == 4  # 8h às 10h, de 30 em 30 min, 1 vaga em cada
    assert len(dias) >= 60

    horas = _horarios(cenario, unidade, servico, _dia())
    assert horas == {"08:00": 1, "08:30": 1, "09:00": 1, "09:30": 1}

    # Ocupar um horário tira esse horário e desconta do dia.
    _abrir(cenario, id_unidade=unidade, id_servico=servico, data_hora=_quando(hora=8))
    assert "08:00" not in _horarios(cenario, unidade, servico, _dia())
    dias = cenario.admin.get(_url_dias(unidade, servico)).json()["dias"]
    assert next(d for d in dias if d["data"] == _dia())["vagas"] == 3


def test_dia_sem_agenda_nao_aparece(cenario: Cenario) -> None:  # noqa: F811
    servico = cenario.admin.post("/servicos", json=_servico(cids=[cenario.cid["id"]])).json()
    unidade = cenario.admin.post("/unidades", json=_unidade(servicos=[servico["id"]])).json()
    amanha = (datetime.now(FUSO) + timedelta(days=1)).date()
    corpo = _agenda(
        cenario,
        id_unidade=unidade["id"],
        id_servico=servico["id"],
        dia_semana=amanha.weekday(),
    )
    assert cenario.admin.post("/agendas", json=corpo).status_code == 201
    dias = cenario.admin.get(_url_dias(unidade["id"], servico["id"])).json()["dias"]
    assert {datetime.fromisoformat(d["data"]).weekday() for d in dias} == {amanha.weekday()}
    assert _horarios(cenario, unidade["id"], servico["id"], _dia(2)) == {}


def test_horario_passado_nao_aparece(
    cenario: Cenario,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unidade, servico = _alvo_novo(cenario)
    amanha = (datetime.now(FUSO) + timedelta(days=1)).date()
    agora = datetime(amanha.year, amanha.month, amanha.day, 9, 15, tzinfo=FUSO)
    monkeypatch.setattr("app.api.ocis.agora", lambda: agora)
    assert _horarios(cenario, unidade, servico, _dia()) == {"09:30": 1}
    url = f"{_url_dias(unidade, servico)}/{(amanha - timedelta(days=1)).isoformat()}/horarios"
    assert cenario.admin.get(url).json() == {"horarios": []}  # antes de hoje


def test_fora_do_horizonte_nao_aparece(cenario: Cenario) -> None:  # noqa: F811
    unidade, servico = _alvo_novo(cenario)
    assert _horarios(cenario, unidade, servico, _dia(61)) == {}


@pytest.mark.parametrize("dia", ["ontem", "2026-13-40", "1 OR 1=1"])
def test_dia_invalido(cenario: Cenario, dia: str) -> None:  # noqa: F811
    url = f"{_url_dias(cenario.unidade['id'], cenario.servico['id'])}/{dia}/horarios"
    assert cenario.admin.get(url).status_code == 422


def test_vagas_nao_dependem_de_sessao_de_outro_perfil(logar: Logar, cenario: Cenario) -> None:  # noqa: F811
    url = _url_dias(cenario.unidade["id"], cenario.servico["id"])
    assert logar("Gestor do Cuidado").api.get(url).status_code == 200
    assert logar("Auditor").api.get(url).status_code == 403


# --- Marcação -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "data_hora",
    [
        lambda: _quando(hora=7),  # antes da agenda
        lambda: _quando(hora=10),  # termina às 10h: o último começa 9h30
        lambda: _quando().replace("09:00:00", "09:10:00"),  # fora do intervalo
    ],
)
def test_horario_fora_da_agenda_e_recusado(cenario: Cenario, data_hora: Any) -> None:  # noqa: F811
    unidade, servico = _alvo_novo(cenario)
    resp = cenario.admin.post(
        "/ocis",
        json=_corpo(cenario, id_unidade=unidade, id_servico=servico, data_hora=data_hora()),
    )
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Este horário não está mais disponível: escolha outro."}


def test_horario_passado_nao_marca(cenario: Cenario) -> None:  # noqa: F811
    resp = cenario.admin.post("/ocis", json=_corpo(cenario, data_hora=_quando(dias=-1)))
    assert resp.status_code == 409


def test_mesmo_instante_em_outro_fuso_e_o_mesmo_horario(cenario: Cenario) -> None:  # noqa: F811
    unidade, servico = _alvo_novo(cenario)
    em_utc = datetime.fromisoformat(_quando(hora=8)).astimezone(UTC).isoformat()
    _abrir(cenario, id_unidade=unidade, id_servico=servico, data_hora=em_utc)
    assert "08:00" not in _horarios(cenario, unidade, servico, _dia())


def test_servico_fora_do_cid_e_recusado_mesmo_com_agenda(cenario: Cenario) -> None:  # noqa: F811
    admin = cenario.admin
    outro = admin.post("/servicos", json=_servico()).json()
    admin.patch(
        f"/unidades/{cenario.unidade['id']}",
        json={"servicos": [cenario.servico["id"], outro["id"]]},
    )
    _agendas(admin, cenario.unidade["id"], outro["id"])
    resp = admin.post("/ocis", json=_corpo(cenario, id_servico=outro["id"]))
    assert resp.status_code == 422
    assert resp.json() == {"detail": "Serviço inválido."}


def test_lotado_nao_marca_e_encaminhamento_tambem_confere(cenario: Cenario) -> None:  # noqa: F811
    unidade, servico = _alvo_novo(cenario)
    alvo: dict[str, Any] = {
        "id_unidade": unidade,
        "id_servico": servico,
        "data_hora": _quando(hora=8),
    }
    primeira = _abrir(cenario, **alvo)
    outro = _novo_paciente(cenario.admin)
    assert cenario.admin.post("/ocis", json=_corpo(cenario, cpf=outro, **alvo)).status_code == 409
    resp = cenario.admin.post(f"/ocis/{primeira['id']}/navegacoes", json=alvo)
    assert resp.status_code == 409


def test_ultimas_vagas_sob_concorrencia_real_nunca_passam_do_limite(
    app_teste: FastAPI,
    cenario: Cenario,  # noqa: F811
) -> None:
    unidade, servico = _alvo_novo(cenario, vagas=2)
    corpos = [
        _corpo(
            cenario,
            cpf=_novo_paciente(cenario.admin),
            id_unidade=unidade,
            id_servico=servico,
            data_hora=_quando(hora=8),
        )
        for _ in range(8)
    ]

    def marcar(corpo: dict[str, object]) -> int:
        with TestClient(
            app_teste,
            base_url="https://testserver",
            cookies=dict(cenario.admin.cookies),
            headers={"X-CSRF-Token": cenario.admin.headers["X-CSRF-Token"]},
        ) as api:
            return int(api.post("/ocis", json=corpo).status_code)

    with ThreadPoolExecutor(max_workers=8) as grupo:
        respostas = list(grupo.map(marcar, corpos))
    assert sorted(respostas) == [201, 201, 409, 409, 409, 409, 409, 409]
    assert "08:00" not in _horarios(cenario, unidade, servico, _dia())


# --- O que libera e o que ocupa a vaga ----------------------------------------------------


def test_cancelar_etapa_libera_e_falta_ocupa(cenario: Cenario) -> None:  # noqa: F811
    unidade, servico = _alvo_novo(cenario)
    a = _abrir(cenario, id_unidade=unidade, id_servico=servico, data_hora=_quando(hora=8))
    url = f"/ocis/{a['id']}/navegacoes/{a['navegacoes'][0]['id']}"
    cenario.admin.patch(url, json={"status": "cancelado"})
    assert "08:00" in _horarios(cenario, unidade, servico, _dia())

    b = _abrir(
        cenario,
        cpf=_novo_paciente(cenario.admin),
        id_unidade=unidade,
        id_servico=servico,
        data_hora=_quando(hora=8),
    )
    url = f"/ocis/{b['id']}/navegacoes/{b['navegacoes'][0]['id']}"
    cenario.admin.patch(url, json={"status": "faltou"})
    assert "08:00" not in _horarios(cenario, unidade, servico, _dia())


@pytest.mark.parametrize(
    ("acao", "corpo", "evento"),
    [("cancelar", None, "oci_canceled"), ("concluir", {"resultado": "Ok"}, "oci_concluded")],
)
def test_encerrar_oci_cancela_as_pendentes_e_libera_a_vaga(
    cenario: Cenario,  # noqa: F811
    fabrica_sessao: Fabrica,
    acao: str,
    corpo: dict[str, str] | None,
    evento: str,
) -> None:
    unidade, servico = _alvo_novo(cenario)
    oci = _abrir(cenario, id_unidade=unidade, id_servico=servico, data_hora=_quando(hora=8))
    resp = cenario.admin.post(f"/ocis/{oci['id']}/{acao}", json=corpo)
    assert resp.json()["navegacoes"][0]["status"] == "cancelado"
    assert "08:00" in _horarios(cenario, unidade, servico, _dia())
    with fabrica_sessao() as db:
        registro = db.scalars(
            select(Log).where(Log.acao == evento).order_by(Log.seq_cadeia.desc()).limit(1)
        ).one()
    assert registro.resumo_acessado == {"etapas_canceladas": 1}


def test_agenda_inativa_nao_oferece_mas_mantem_o_marcado(cenario: Cenario) -> None:  # noqa: F811
    admin = cenario.admin
    unidade, servico = _alvo_novo(cenario)
    oci = _abrir(cenario, id_unidade=unidade, id_servico=servico, data_hora=_quando(hora=8))
    pagina, tem_mais = 1, True
    while tem_mais:  # a lista é paginada, e o banco de teste guarda agendas de outros testes
        corpo = admin.post("/agendas/lista", json={"pagina": pagina}).json()
        for agenda in corpo["itens"]:
            if agenda["id_unidade"] == unidade:
                assert admin.delete(f"/agendas/{agenda['id']}").status_code == 204
        pagina, tem_mais = pagina + 1, corpo["tem_mais"]
    assert admin.get(_url_dias(unidade, servico)).json() == {"dias": []}
    assert admin.get(f"/ocis/{oci['id']}").json()["navegacoes"][0]["status"] == "agendado"


# --- Remarcação ---------------------------------------------------------------------------


def _remarcar(c: Cenario, oci: dict[str, Any], **destino: object) -> Any:
    etapa = oci["navegacoes"][0]["id"]
    corpo = {
        "id_unidade": c.unidade["id"],
        "id_servico": c.servico["id"],
        "data_hora": _quando(2),
        **destino,
    }
    return c.admin.post(f"/ocis/{oci['id']}/navegacoes/{etapa}/remarcar", json=corpo)


def test_remarcar_guarda_o_historico_e_troca_a_vaga(
    cenario: Cenario,  # noqa: F811
    fabrica_sessao: Fabrica,
) -> None:
    unidade, servico = _alvo_novo(cenario)
    oci = _abrir(cenario, id_unidade=unidade, id_servico=servico, data_hora=_quando(hora=8))
    resp = _remarcar(
        cenario, oci, id_unidade=unidade, id_servico=servico, data_hora=_quando(hora=9)
    )
    assert resp.status_code == 200
    etapas = resp.json()["navegacoes"]
    assert [e["status"] for e in etapas] == ["remarcado", "agendado"]
    assert [e["pode_marcar"] for e in etapas] == [False, True]
    horas = _horarios(cenario, unidade, servico, _dia())
    assert "08:00" in horas and "09:00" not in horas

    with fabrica_sessao() as db:
        evento = db.scalars(
            select(Log)
            .where(Log.acao == "navigation_rescheduled")
            .order_by(Log.seq_cadeia.desc())
            .limit(1)
        ).one()
    assert evento.id_oci is not None and evento.cpf_paciente_hash is not None
    assert evento.resumo_acessado["id_unidade"] == unidade


def test_remarcar_para_outra_unidade_da_acesso_a_ela(
    logar: Logar,  # noqa: F811
    cenario: Cenario,  # noqa: F811
    fabrica_sessao: Fabrica,
    settings_integracao: Settings,
) -> None:
    oci = _abrir(cenario)
    destino = _na_unidade(
        logar("Navegador"), cenario.outra_unidade["id"], fabrica_sessao, settings_integracao
    )
    assert destino.get(f"/ocis/{oci['id']}").status_code == 404
    assert _remarcar(cenario, oci, id_unidade=cenario.outra_unidade["id"]).status_code == 200
    assert destino.get(f"/ocis/{oci['id']}").status_code == 200


def test_remarcar_sem_vaga_nao_altera_nada(cenario: Cenario) -> None:  # noqa: F811
    unidade, servico = _alvo_novo(cenario)
    ocupada = _abrir(
        cenario,
        cpf=_novo_paciente(cenario.admin),
        id_unidade=unidade,
        id_servico=servico,
        data_hora=_quando(hora=9),
    )
    oci = _abrir(cenario, id_unidade=unidade, id_servico=servico, data_hora=_quando(hora=8))
    resp = _remarcar(
        cenario, oci, id_unidade=unidade, id_servico=servico, data_hora=_quando(hora=9)
    )
    assert resp.status_code == 409
    corpo = cenario.admin.get(f"/ocis/{oci['id']}").json()
    assert [e["status"] for e in corpo["navegacoes"]] == ["agendado"]
    assert ocupada["id"] != oci["id"]


def test_etapa_encerrada_nao_remarca(cenario: Cenario) -> None:  # noqa: F811
    oci = _abrir(cenario)
    etapa = oci["navegacoes"][0]["id"]
    cenario.admin.patch(f"/ocis/{oci['id']}/navegacoes/{etapa}", json={"status": "realizado"})
    resp = _remarcar(cenario, oci)
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Esta etapa já foi encerrada: registre uma nova."}


def test_remarcar_etapa_de_outra_unidade_e_negado_e_de_oci_alheia_e_404(
    logar: Logar,  # noqa: F811
    cenario: Cenario,  # noqa: F811
    fabrica_sessao: Fabrica,
    settings_integracao: Settings,
) -> None:
    oci = _abrir(cenario)
    etapa = oci["navegacoes"][0]["id"]
    corpo = {
        "id_unidade": cenario.outra_unidade["id"],
        "id_servico": cenario.servico["id"],
        "data_hora": _quando(2),
    }
    resp = cenario.admin.post(f"/ocis/{oci['id']}/navegacoes", json=corpo)
    assert resp.status_code == 201
    destino = _na_unidade(
        logar("Navegador"), cenario.outra_unidade["id"], fabrica_sessao, settings_integracao
    )
    url = f"/ocis/{oci['id']}/navegacoes/{etapa}/remarcar"
    assert destino.post(url, json=corpo).status_code == 403
    assert logar("Gestor").api.post(url, json=corpo).status_code == 403

    fora = _na_unidade(
        logar("Navegador"),
        cenario.admin.post("/unidades", json=_unidade()).json()["id"],
        fabrica_sessao,
        settings_integracao,
    )
    assert fora.post(url, json=corpo).status_code == 404


def test_remarcar_servico_fora_do_cid_e_entrada_invalida(cenario: Cenario) -> None:  # noqa: F811
    oci = _abrir(cenario)
    outro = cenario.admin.post("/servicos", json=_servico()).json()
    assert _remarcar(cenario, oci, id_servico=outro["id"]).status_code == 422
    assert _remarcar(cenario, oci, id_unidade=0).status_code == 422
    assert _remarcar(cenario, oci, data_hora="amanhã").status_code == 422
    etapa = oci["navegacoes"][0]["id"]
    url = f"/ocis/{oci['id']}/navegacoes/2000000/remarcar"
    corpo = {
        "id_unidade": cenario.unidade["id"],
        "id_servico": cenario.servico["id"],
        "data_hora": _quando(2),
    }
    assert cenario.admin.post(url, json=corpo).status_code == 404
    assert etapa


def test_tipo_de_oci_sem_relacao_com_a_agenda_nao_atrapalha(cenario: Cenario) -> None:  # noqa: F811
    tipo = cenario.admin.post("/tipos-oci", json=_tipo_oci(cids=[cenario.cid["id"]])).json()
    oci = _abrir(cenario, id_tipo_oci=tipo["id"])
    assert oci["tipo_oci"] == tipo["tipo_oci"]
