"""RF-09/10/11 / THREAT_MODEL E1, T2, R1: unidades, serviços e CID (ADR-0019)."""

import itertools
import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.crypto import FinalidadeHash, hash_busca
from app.models import Cid, Log

from .conftest import ALEMBIC_INI, BancoTeste, banco_temporario, gerar_cpf
from .test_pacientes import Logar, logar  # noqa: F401

Fabrica = sessionmaker[Session]
Conn = psycopg.Connection[tuple[object, ...]]
TIPO_POSTO = 1  # os 4 tipos iniciais da migration 0012, nesta ordem
TIPO_HOSPITAL = 3
PODEM_LER = {"Administrador", "Gestor", "Gestor do Cuidado", "Navegador"}
PERFIS = [*sorted(PODEM_LER), "Auditor", None]


def _sufixo() -> str:
    return uuid.uuid4().hex[:10]


def _tipo(**extra: object) -> dict[str, object]:
    return {"nome": f"Tipo {_sufixo()}", "descricao": "Tipo de teste", **extra}


def _unidade(**extra: object) -> dict[str, object]:
    return {
        "nome": f"UBS {_sufixo()}",
        "id_tipo_unidade": TIPO_POSTO,
        "endereco": "Av. Norte, 100 - Recife",
        "telefone": "(81) 3355-0000",
        **extra,
    }


def _servico(**extra: object) -> dict[str, object]:
    return {"nome": f"Consulta {_sufixo()}", "descricao": "Consulta especializada", **extra}


def _tipo_oci(**extra: object) -> dict[str, object]:
    return {"tipo_oci": f"OCI {_sufixo()}", "prazo_diagnostico": 30, **extra}


_PROXIMO_CID = itertools.count()
_BASE36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _cid(**extra: object) -> dict[str, object]:
    # Sequencial, não aleatório: dois testes nunca geram o mesmo código na mesma rodada.
    resto, numero = divmod(next(_PROXIMO_CID), 100)
    alto, baixo = divmod(resto, 36)
    return {
        "cid": f"Z{numero:02d}.{_BASE36[alto]}{_BASE36[baixo]}",
        "descricao": "Teste",
        **extra,
    }


NOVOS = {
    "tipos-unidade": _tipo,
    "unidades": _unidade,
    "servicos": _servico,
    "cids": _cid,
    "tipos-oci": _tipo_oci,
}


@pytest.fixture
def admin(logar: Logar) -> TestClient:  # noqa: F811
    return logar("Administrador").api


def _ultimo(fabrica: Fabrica, acao: str) -> Log:
    with fabrica() as db:
        return db.scalars(
            select(Log).where(Log.acao == acao).order_by(Log.seq_cadeia.desc()).limit(1)
        ).one()


# --- Autorização -------------------------------------------------------------------------


@pytest.mark.parametrize("perfil", PERFIS)
@pytest.mark.parametrize("rota", NOVOS)
def test_matriz_de_permissoes(
    logar: Logar,  # noqa: F811
    admin: TestClient,
    perfil: str | None,
    rota: str,
) -> None:
    criado = admin.post(f"/{rota}", json=NOVOS[rota]()).json()
    api = logar(perfil).api
    url = f"/{rota}/{criado['id']}"
    leitura = 200 if perfil in PODEM_LER else 403
    escrita_criar = 201 if perfil == "Administrador" else 403
    escrita = 200 if perfil == "Administrador" else 403
    remover = 204 if perfil == "Administrador" else 403
    assert api.post(f"/{rota}/lista", json={}).status_code == leitura
    assert api.post(f"/{rota}", json=NOVOS[rota]()).status_code == escrita_criar
    alteracao: dict[str, object] = {"descricao": "Outra"}
    if rota == "unidades":
        alteracao = {"endereco": "Rua Sul, 1"}
    if rota == "tipos-oci":
        alteracao = {"prazo_diagnostico": 60}
    assert api.patch(url, json=alteracao).status_code == escrita
    assert api.delete(url).status_code == remover
    assert api.post(f"{url}/reativar").status_code == remover


def test_opcoes_de_unidade_seguem_a_leitura(logar: Logar) -> None:  # noqa: F811
    assert logar("Navegador").api.get("/unidades/opcoes").status_code == 200
    assert logar("Auditor").api.get("/unidades/opcoes").status_code == 403


def test_escrita_exige_token_csrf(admin: TestClient) -> None:
    del admin.headers["X-CSRF-Token"]
    assert admin.post("/servicos", json=_servico()).status_code == 403


# --- Unidades ----------------------------------------------------------------------------


def test_unidade_normaliza_telefone_e_aparece_nas_opcoes(admin: TestClient) -> None:
    corpo = admin.post("/unidades", json=_unidade()).json()
    assert corpo["telefone"] == "8133550000" and corpo["status"] == "ativo"
    opcoes = admin.get("/unidades/opcoes").json()["opcoes"]
    assert {"id": corpo["id"], "nome": corpo["nome"]} in opcoes

    assert admin.delete(f"/unidades/{corpo['id']}").status_code == 204
    opcoes = admin.get("/unidades/opcoes").json()["opcoes"]
    assert corpo["id"] not in {o["id"] for o in opcoes}


@pytest.mark.parametrize(
    "extra",
    [
        {"tipo_unidade": "Shopping"},
        {"id_tipo_unidade": 0},
        {"id_tipo_unidade": "Hospital"},
        {"id_tipo_unidade": 99_999_999_999},
        {"telefone": "123"},
        {"telefone": "abc8133550000"},
        {"nome": "x"},
        {"nome": "Nome\x00nulo"},
        {"endereco": ""},
        {"id_unidade": 5},
        {"status": "inativo"},
    ],
)
def test_unidade_invalida(admin: TestClient, extra: dict[str, object]) -> None:
    assert admin.post("/unidades", json=_unidade(**extra)).status_code == 422


def test_telefone_pode_ser_removido_e_obrigatorios_nao(admin: TestClient) -> None:
    corpo = admin.post("/unidades", json=_unidade()).json()
    url = f"/unidades/{corpo['id']}"
    assert admin.patch(url, json={"telefone": None}).json()["telefone"] is None
    assert admin.patch(url, json={"nome": None}).status_code == 422
    assert admin.patch(url, json={}).status_code == 422


# --- Tipos de unidade --------------------------------------------------------------------


def test_tipos_iniciais_e_unidade_mostra_id_e_nome_do_tipo(admin: TestClient) -> None:
    opcoes = admin.get("/tipos-unidade/opcoes").json()["opcoes"]
    nomes = {o["nome"]: o["id"] for o in opcoes}
    assert {"Posto de Saúde", "Clínica", "Hospital", "Laboratório"} <= nomes.keys()
    assert nomes["Hospital"] == TIPO_HOSPITAL
    corpo = admin.post("/unidades", json=_unidade(id_tipo_unidade=TIPO_HOSPITAL)).json()
    assert corpo["id_tipo_unidade"] == TIPO_HOSPITAL and corpo["tipo_unidade"] == "Hospital"


def test_tipo_novo_pode_ser_usado_e_renomeado(admin: TestClient) -> None:
    tipo = admin.post("/tipos-unidade", json=_tipo()).json()
    assert {"id": tipo["id"], "nome": tipo["nome"]} in admin.get("/tipos-unidade/opcoes").json()[
        "opcoes"
    ]
    unidade = admin.post("/unidades", json=_unidade(id_tipo_unidade=tipo["id"])).json()
    assert unidade["tipo_unidade"] == tipo["nome"]
    novo_nome = f"Renomeado {_sufixo()}"
    admin.patch(f"/tipos-unidade/{tipo['id']}", json={"nome": novo_nome})
    achada = admin.post("/unidades/lista", json={"busca": novo_nome}).json()["itens"]
    assert [u["id"] for u in achada] == [unidade["id"]]
    assert achada[0]["tipo_unidade"] == novo_nome


def test_tipo_inexistente_ou_inativo_e_recusado(admin: TestClient) -> None:
    resp = admin.post("/unidades", json=_unidade(id_tipo_unidade=2_000_000))
    assert resp.status_code == 422
    assert resp.json() == {"detail": "Tipo de unidade inválido."}
    tipo = admin.post("/tipos-unidade", json=_tipo()).json()
    assert admin.delete(f"/tipos-unidade/{tipo['id']}").status_code == 204
    assert admin.post("/unidades", json=_unidade(id_tipo_unidade=tipo["id"])).status_code == 422
    assert tipo["id"] not in {o["id"] for o in admin.get("/tipos-unidade/opcoes").json()["opcoes"]}

    unidade = admin.post("/unidades", json=_unidade()).json()
    url = f"/unidades/{unidade['id']}"
    assert admin.patch(url, json={"id_tipo_unidade": tipo["id"]}).status_code == 422
    assert admin.patch(url, json={"id_tipo_unidade": 2_000_000}).status_code == 422


def test_troca_de_tipo_da_unidade(admin: TestClient) -> None:
    unidade = admin.post("/unidades", json=_unidade()).json()
    corpo = admin.patch(
        f"/unidades/{unidade['id']}", json={"id_tipo_unidade": TIPO_HOSPITAL}
    ).json()
    assert corpo["id_tipo_unidade"] == TIPO_HOSPITAL and corpo["tipo_unidade"] == "Hospital"


def test_tipo_em_uso_nao_inativa_e_unidade_com_tipo_inativo_continua_editavel(
    admin: TestClient,
) -> None:
    tipo = admin.post("/tipos-unidade", json=_tipo()).json()
    unidade = admin.post("/unidades", json=_unidade(id_tipo_unidade=tipo["id"])).json()
    url_tipo = f"/tipos-unidade/{tipo['id']}"
    url = f"/unidades/{unidade['id']}"

    resp = admin.delete(url_tipo)
    assert resp.status_code == 409
    assert "unidades ativas deste tipo" in resp.json()["detail"]

    # Com a unidade inativa, o tipo pode sair de uso; a unidade continua editável.
    assert admin.delete(url).status_code == 204
    assert admin.delete(url_tipo).status_code == 204
    assert admin.post(f"{url}/reativar").status_code == 204
    corpo = admin.patch(url, json={"endereco": "Rua Nova, 2", "id_tipo_unidade": tipo["id"]})
    assert corpo.status_code == 200
    assert corpo.json()["tipo_unidade"] == tipo["nome"]


# --- Serviços da unidade -----------------------------------------------------------------


def _novo_servico(api: TestClient) -> dict[str, Any]:
    corpo: dict[str, Any] = api.post("/servicos", json=_servico()).json()
    return corpo


def _ids(unidade: dict[str, Any]) -> set[int]:
    return {s["id"] for s in unidade["servicos"]}


def test_unidade_nasce_com_servicos_e_os_mostra_em_ordem(admin: TestClient) -> None:
    b = admin.post("/servicos", json=_servico(nome=f"Bbb {_sufixo()}")).json()
    a = admin.post("/servicos", json=_servico(nome=f"Aaa {_sufixo()}")).json()
    unidade = admin.post("/unidades", json=_unidade(servicos=[b["id"], a["id"], a["id"]])).json()
    assert unidade["servicos"] == [
        {"id": a["id"], "nome": a["nome"]},
        {"id": b["id"], "nome": b["nome"]},
    ]
    achada = admin.post("/unidades/lista", json={"busca": unidade["nome"]}).json()["itens"][0]
    assert achada["servicos"] == unidade["servicos"]


def test_unidade_sem_servicos_por_padrao(admin: TestClient) -> None:
    assert admin.post("/unidades", json=_unidade()).json()["servicos"] == []


def test_envio_define_o_conjunto_e_sem_o_campo_nada_muda(
    admin: TestClient, fabrica_sessao: Fabrica
) -> None:
    a, b, c = (_novo_servico(admin) for _ in range(3))
    unidade = admin.post("/unidades", json=_unidade(servicos=[a["id"], b["id"]])).json()
    url = f"/unidades/{unidade['id']}"

    corpo = admin.patch(url, json={"servicos": [b["id"], c["id"]]}).json()
    assert _ids(corpo) == {b["id"], c["id"]}
    evento = _ultimo(fabrica_sessao, "catalog_updated")
    assert evento.resumo_acessado["servicos_adicionados"] == [c["id"]]
    assert evento.resumo_acessado["servicos_removidos"] == [a["id"]]

    corpo = admin.patch(url, json={"endereco": "Rua Sul, 5"}).json()
    assert _ids(corpo) == {b["id"], c["id"]} and corpo["endereco"] == "Rua Sul, 5"

    assert _ids(admin.patch(url, json={"servicos": []}).json()) == set()


def test_mesmos_servicos_nao_geram_evento(admin: TestClient, fabrica_sessao: Fabrica) -> None:
    servico = _novo_servico(admin)
    unidade = admin.post("/unidades", json=_unidade(servicos=[servico["id"]])).json()
    admin.patch(f"/unidades/{unidade['id']}", json={"endereco": "Rua Marca, 1"})
    antes = _ultimo(fabrica_sessao, "catalog_updated").seq_cadeia
    resp = admin.patch(f"/unidades/{unidade['id']}", json={"servicos": [servico["id"]]})
    assert resp.status_code == 200 and _ids(resp.json()) == {servico["id"]}
    assert _ultimo(fabrica_sessao, "catalog_updated").seq_cadeia == antes


def test_criacao_registra_servicos_no_log(admin: TestClient, fabrica_sessao: Fabrica) -> None:
    servico = _novo_servico(admin)
    admin.post("/unidades", json=_unidade(servicos=[servico["id"]]))
    evento = _ultimo(fabrica_sessao, "catalog_created")
    assert evento.resumo_acessado["servicos_adicionados"] == [servico["id"]]


def test_servico_inexistente_ou_inativo_e_recusado_sem_gravar_nada(admin: TestClient) -> None:
    dados = _unidade(servicos=[2_000_000])
    resp = admin.post("/unidades", json=dados)
    assert resp.status_code == 422
    assert resp.json() == {"detail": "Serviço inválido."}
    assert admin.post("/unidades/lista", json={"busca": dados["nome"]}).json()["itens"] == []

    inativo = _novo_servico(admin)
    assert admin.delete(f"/servicos/{inativo['id']}").status_code == 204
    assert admin.post("/unidades", json=_unidade(servicos=[inativo["id"]])).status_code == 422

    # Na edição, a falha nos serviços desfaz também os demais campos.
    unidade = admin.post("/unidades", json=_unidade()).json()
    url = f"/unidades/{unidade['id']}"
    resp = admin.patch(url, json={"endereco": "Nao Deve Gravar", "servicos": [inativo["id"]]})
    assert resp.status_code == 422
    achada = admin.post("/unidades/lista", json={"busca": unidade["nome"]}).json()["itens"][0]
    assert achada["endereco"] == unidade["endereco"]


def test_servico_em_uso_nao_inativa_e_inativo_ja_vinculado_nao_trava_edicao(
    admin: TestClient,
) -> None:
    servico = _novo_servico(admin)
    unidade = admin.post("/unidades", json=_unidade(servicos=[servico["id"]])).json()
    url_servico = f"/servicos/{servico['id']}"
    url = f"/unidades/{unidade['id']}"

    resp = admin.delete(url_servico)
    assert resp.status_code == 409
    assert "unidades ativas com este serviço" in resp.json()["detail"]

    assert admin.delete(url).status_code == 204
    assert admin.delete(url_servico).status_code == 204
    assert admin.post(f"{url}/reativar").status_code == 204
    resp = admin.patch(url, json={"endereco": "Rua Nova, 9", "servicos": [servico["id"]]})
    assert resp.status_code == 200 and _ids(resp.json()) == {servico["id"]}
    opcoes = admin.get("/servicos/opcoes").json()["opcoes"]
    assert servico["id"] not in {o["id"] for o in opcoes}


def test_busca_de_unidade_acha_pelo_servico(admin: TestClient) -> None:
    servico = _novo_servico(admin)
    unidade = admin.post("/unidades", json=_unidade(servicos=[servico["id"]])).json()
    itens = admin.post("/unidades/lista", json={"busca": servico["nome"]}).json()["itens"]
    assert [u["id"] for u in itens] == [unidade["id"]]


@pytest.mark.parametrize(
    "servicos", [[0], ["x"], "1", [99_999_999_999], list(range(1, 1002)), None]
)
def test_lista_de_servicos_invalida(admin: TestClient, servicos: object) -> None:
    assert admin.post("/unidades", json=_unidade(servicos=servicos)).status_code == 422
    unidade = admin.post("/unidades", json=_unidade()).json()
    resp = admin.patch(f"/unidades/{unidade['id']}", json={"servicos": servicos})
    assert resp.status_code == 422


def test_opcoes_de_servico_seguem_a_leitura(logar: Logar) -> None:  # noqa: F811
    assert logar("Navegador").api.get("/servicos/opcoes").status_code == 200
    assert logar("Auditor").api.get("/servicos/opcoes").status_code == 403


def test_navegador_nao_altera_servicos_da_unidade(
    logar: Logar,  # noqa: F811
    admin: TestClient,
) -> None:
    servico = _novo_servico(admin)
    unidade = admin.post("/unidades", json=_unidade()).json()
    resp = logar("Navegador").api.patch(
        f"/unidades/{unidade['id']}", json={"servicos": [servico["id"]]}
    )
    assert resp.status_code == 403


# --- Tipos de OCI e seus CIDs ------------------------------------------------------------


def _novo_cid(api: TestClient, **extra: object) -> dict[str, Any]:
    corpo: dict[str, Any] = api.post("/cids", json=_cid(**extra)).json()
    return corpo


def _codigos(tipo: dict[str, Any]) -> list[str]:
    return [c["cid"] for c in tipo["cids"]]


def test_tipo_oci_nasce_com_cids_em_ordem_e_aparece_na_lista(admin: TestClient) -> None:
    b, a = _novo_cid(admin), _novo_cid(admin)
    criado = admin.post("/tipos-oci", json=_tipo_oci(cids=[b["id"], a["id"], a["id"]]))
    assert criado.status_code == 201
    corpo = criado.json()
    assert corpo["prazo_diagnostico"] == 30 and corpo["status"] == "ativo"
    assert _codigos(corpo) == sorted([a["cid"], b["cid"]])
    achado = admin.post("/tipos-oci/lista", json={"busca": corpo["tipo_oci"]}).json()["itens"][0]
    assert achado == corpo


def test_tipo_oci_sem_cids_por_padrao_e_edicao_parcial(admin: TestClient) -> None:
    corpo = admin.post("/tipos-oci", json=_tipo_oci()).json()
    assert corpo["cids"] == []
    alterado = admin.patch(f"/tipos-oci/{corpo['id']}", json={"prazo_diagnostico": 90}).json()
    assert alterado["prazo_diagnostico"] == 90 and alterado["tipo_oci"] == corpo["tipo_oci"]


@pytest.mark.parametrize(
    "extra",
    [
        {"prazo_diagnostico": 0},
        {"prazo_diagnostico": 3651},
        {"prazo_diagnostico": "30 dias"},
        {"prazo_diagnostico": None},
        {"tipo_oci": "x"},
        {"tipo_oci": "Nome\x00nulo"},
        {"cids": ["abc"]},
        {"cids": ["' OR 1=1 --"]},
        {"cids": ["A" * 64]},
        {"status": "inativo"},
    ],
)
def test_tipo_oci_invalido(admin: TestClient, extra: dict[str, object]) -> None:
    resp = admin.post("/tipos-oci", json=_tipo_oci(**extra))
    assert resp.status_code == 422
    assert "OR 1=1" not in resp.text


def test_nome_de_tipo_oci_duplicado(admin: TestClient) -> None:
    dados = _tipo_oci()
    assert admin.post("/tipos-oci", json=dados).status_code == 201
    resp = admin.post("/tipos-oci", json={**dados, "tipo_oci": str(dados["tipo_oci"]).upper()})
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Já existe um cadastro com esses dados."}


def test_envio_de_cids_define_o_conjunto_e_vai_para_o_log(
    admin: TestClient, fabrica_sessao: Fabrica
) -> None:
    a, b, c = (_novo_cid(admin) for _ in range(3))
    tipo = admin.post("/tipos-oci", json=_tipo_oci(cids=[a["id"], b["id"]])).json()
    criado = _ultimo(fabrica_sessao, "catalog_created")
    assert criado.resumo_acessado["recurso"] == "tipo_oci"
    assert criado.resumo_acessado["cids_adicionados"] == sorted([a["cid"], b["cid"]])

    url = f"/tipos-oci/{tipo['id']}"
    corpo = admin.patch(url, json={"cids": [b["id"], c["id"]]}).json()
    assert _codigos(corpo) == sorted([b["cid"], c["cid"]])
    evento = _ultimo(fabrica_sessao, "catalog_updated")
    assert evento.resumo_acessado["cids_adicionados"] == [c["cid"]]
    assert evento.resumo_acessado["cids_removidos"] == [a["cid"]]

    corpo = admin.patch(url, json={"prazo_diagnostico": 45}).json()
    assert _codigos(corpo) == sorted([b["cid"], c["cid"]])  # sem o campo, nada muda
    antes = _ultimo(fabrica_sessao, "catalog_updated").seq_cadeia
    assert admin.patch(url, json={"cids": [b["id"], c["id"]]}).status_code == 200
    assert _ultimo(fabrica_sessao, "catalog_updated").seq_cadeia == antes  # sem mudança, sem evento
    assert admin.patch(url, json={"cids": []}).json()["cids"] == []


def test_cid_inexistente_ou_inativo_e_recusado_sem_gravar_nada(admin: TestClient) -> None:
    dados = _tipo_oci(cids=["0" * 64])
    resp = admin.post("/tipos-oci", json=dados)
    assert resp.status_code == 422
    assert resp.json() == {"detail": "CID inválido."}
    assert admin.post("/tipos-oci/lista", json={"busca": dados["tipo_oci"]}).json()["itens"] == []

    inativo = _novo_cid(admin)
    assert admin.delete(f"/cids/{inativo['id']}").status_code == 204
    assert admin.post("/tipos-oci", json=_tipo_oci(cids=[inativo["id"]])).status_code == 422

    tipo = admin.post("/tipos-oci", json=_tipo_oci()).json()
    resp = admin.patch(
        f"/tipos-oci/{tipo['id']}", json={"prazo_diagnostico": 99, "cids": [inativo["id"]]}
    )
    assert resp.status_code == 422
    achado = admin.post("/tipos-oci/lista", json={"busca": tipo["tipo_oci"]}).json()["itens"][0]
    assert achado["prazo_diagnostico"] == 30  # a falha desfaz o resto da edição


def test_cid_em_uso_nao_inativa_e_inativo_ja_vinculado_nao_trava_edicao(
    admin: TestClient,
) -> None:
    cid = _novo_cid(admin)
    tipo = admin.post("/tipos-oci", json=_tipo_oci(cids=[cid["id"]])).json()
    url_cid = f"/cids/{cid['id']}"
    url = f"/tipos-oci/{tipo['id']}"

    resp = admin.delete(url_cid)
    assert resp.status_code == 409
    assert "tipos de OCI ativos com este CID" in resp.json()["detail"]

    # Tipo inativo não bloqueia o CID; ao reativar, o vínculo continua e a edição passa.
    assert admin.delete(url).status_code == 204
    assert admin.delete(url_cid).status_code == 204
    assert admin.post(f"{url}/reativar").status_code == 204
    resp = admin.patch(url, json={"prazo_diagnostico": 60, "cids": [cid["id"]]})
    assert resp.status_code == 200
    assert resp.json()["cids"][0]["status"] == "inativo"


def test_opcoes_de_cid_buscam_so_ativos_e_limitam_o_resultado(admin: TestClient) -> None:
    marca = f"Marca{_sufixo()}"
    ativo = _novo_cid(admin, descricao=f"{marca} ativo")
    inativo = _novo_cid(admin, descricao=f"{marca} inativo")
    admin.delete(f"/cids/{inativo['id']}")
    opcoes = admin.post("/cids/opcoes", json={"busca": marca}).json()["opcoes"]
    assert [o["id"] for o in opcoes] == [ativo["id"]]
    assert (
        admin.post("/cids/opcoes", json={"busca": ativo["cid"]}).json()["opcoes"][0]["cid"]
        == (ativo["cid"])
    )

    for _ in range(21):
        _novo_cid(admin, descricao=f"{marca} lote")
    assert len(admin.post("/cids/opcoes", json={"busca": marca}).json()["opcoes"]) == 20


@pytest.mark.parametrize("corpo", [{}, {"busca": "a"}, {"busca": "x" * 101}, {"busca": "a\x00b"}])
def test_opcoes_de_cid_com_entrada_invalida(admin: TestClient, corpo: dict[str, object]) -> None:
    assert admin.post("/cids/opcoes", json=corpo).status_code == 422


def test_opcoes_de_cid_seguem_a_leitura(logar: Logar) -> None:  # noqa: F811
    assert logar("Navegador").api.post("/cids/opcoes", json={"busca": "Teste"}).status_code == 200
    assert logar("Auditor").api.post("/cids/opcoes", json={"busca": "Teste"}).status_code == 403


# --- Duplicados --------------------------------------------------------------------------


@pytest.mark.parametrize("rota", ["tipos-unidade", "unidades", "servicos"])
def test_nome_duplicado_recusado_sem_diferenciar_maiusculas(admin: TestClient, rota: str) -> None:
    dados = NOVOS[rota]()
    assert admin.post(f"/{rota}", json=dados).status_code == 201
    resp = admin.post(f"/{rota}", json={**dados, "nome": str(dados["nome"]).upper()})
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Já existe um cadastro com esses dados."}


def test_renomear_para_nome_existente_e_recusado(admin: TestClient) -> None:
    a = admin.post("/servicos", json=_servico()).json()
    b = admin.post("/servicos", json=_servico()).json()
    resp = admin.patch(f"/servicos/{b['id']}", json={"nome": a["nome"]})
    assert resp.status_code == 409
    assert (
        admin.post("/servicos/lista", json={"busca": b["nome"]}).json()["itens"][0]["id"] == b["id"]
    )


# --- CID ---------------------------------------------------------------------------------


def test_cid_normaliza_codigo_e_usa_hash_como_chave(
    admin: TestClient, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    dados = _cid()
    codigo = str(dados["cid"])
    corpo = admin.post("/cids", json={**dados, "cid": f" {codigo.lower()} "}).json()
    assert corpo["cid"] == codigo
    esperado = hash_busca(settings_integracao.chave_hmac, FinalidadeHash.CID, codigo)
    assert corpo["id"] == esperado.hex()
    with fabrica_sessao() as db:
        assert db.get(Cid, esperado) is not None
    assert admin.post("/cids", json=dados).status_code == 409


@pytest.mark.parametrize("codigo", ["", "C5", "50.9", "C50.", "C50.999", "' OR 1=1 --"])
def test_cid_invalido(admin: TestClient, codigo: str) -> None:
    resp = admin.post("/cids", json={"cid": codigo, "descricao": "Teste"})
    assert resp.status_code == 422
    assert "OR 1=1" not in resp.text


def test_codigo_do_cid_e_imutavel(admin: TestClient) -> None:
    corpo = admin.post("/cids", json=_cid()).json()
    url = f"/cids/{corpo['id']}"
    assert admin.patch(url, json={"cid": "A00.1"}).status_code == 422
    assert admin.patch(url, json={"descricao": "Nova"}).json()["cid"] == corpo["cid"]


@pytest.mark.parametrize("identificador", ["abc", "G" * 64, "A" * 64])
def test_identificador_de_cid_invalido(admin: TestClient, identificador: str) -> None:
    assert admin.delete(f"/cids/{identificador}").status_code == 422


# --- Lista e busca -----------------------------------------------------------------------


def test_lista_paginada_e_ordenada(admin: TestClient) -> None:
    marca = _sufixo()
    for indice in range(23):
        admin.post("/servicos", json=_servico(nome=f"{marca} {indice:02d}"))
    primeira = admin.post("/servicos/lista", json={"busca": marca}).json()
    assert len(primeira["itens"]) == 20 and primeira["tem_mais"] is True
    nomes = [i["nome"] for i in primeira["itens"]]
    assert nomes == sorted(nomes)
    segunda = admin.post("/servicos/lista", json={"busca": marca, "pagina": 2}).json()
    assert len(segunda["itens"]) == 3 and segunda["tem_mais"] is False


@pytest.mark.parametrize("busca", ["%", "_", "' OR 1=1 --", "\\"])
def test_busca_trata_curingas_e_sql_como_texto(admin: TestClient, busca: str) -> None:
    admin.post("/servicos", json=_servico())
    resp = admin.post("/servicos/lista", json={"busca": busca})
    assert resp.status_code == 200
    assert all(busca.lower() in str(i).lower() for i in resp.json()["itens"])


@pytest.mark.parametrize(
    "corpo",
    [{"pagina": 0}, {"pagina": "x"}, {"busca": "a" * 101}, {"busca": "a\x00"}, {"limite": 9}],
)
def test_lista_recusa_entrada_invalida(admin: TestClient, corpo: dict[str, object]) -> None:
    assert admin.post("/unidades/lista", json=corpo).status_code == 422


@pytest.mark.parametrize("rota", ["tipos-unidade", "unidades", "servicos", "tipos-oci"])
def test_inexistente_devolve_404(admin: TestClient, rota: str) -> None:
    url = f"/{rota}/2000000000"
    corpo: dict[str, object] = {"nome": "Outro"}
    if rota == "tipos-oci":
        corpo = {"tipo_oci": "Outro"}
    assert admin.patch(url, json=corpo).status_code == 404
    assert admin.delete(url).status_code == 404
    assert admin.post(f"{url}/reativar").status_code == 404


@pytest.mark.parametrize("identificador", ["0", "-1", "99999999999", "1%20OR%201=1"])
def test_identificador_inteiro_invalido(admin: TestClient, identificador: str) -> None:
    assert admin.delete(f"/unidades/{identificador}").status_code == 422


# --- Auditoria e banco -------------------------------------------------------------------


def test_escritas_auditadas_e_sem_mudanca_nao_audita(
    admin: TestClient, fabrica_sessao: Fabrica
) -> None:
    corpo = admin.post("/servicos", json=_servico()).json()
    criado = _ultimo(fabrica_sessao, "catalog_created")
    assert criado.resumo_acessado == {"recurso": "servico_saude", "id": corpo["id"]}
    assert criado.cpf_usuario_hash is not None

    url = f"/servicos/{corpo['id']}"
    admin.patch(url, json={"descricao": "Outra"})
    alterado = _ultimo(fabrica_sessao, "catalog_updated")
    assert alterado.resumo_acessado["campos"] == ["descricao"]

    assert admin.delete(url).status_code == 204
    inativado = _ultimo(fabrica_sessao, "catalog_deactivated").seq_cadeia
    assert admin.delete(url).status_code == 204  # já inativo: sem novo evento
    assert _ultimo(fabrica_sessao, "catalog_deactivated").seq_cadeia == inativado
    assert admin.post(f"{url}/reativar").status_code == 204
    assert _ultimo(fabrica_sessao, "catalog_reactivated").resumo_acessado["id"] == corpo["id"]


@pytest.mark.parametrize(
    "tabela", ["tipo_unidade", "unidade_saude", "servico_saude", "cid", "tipo_oci"]
)
def test_app_user_nao_apaga_cadastros(app_conn: Conn, tabela: str) -> None:
    comando = sql.SQL("DELETE FROM app.{}").format(sql.Identifier(tabela))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute(comando)
    app_conn.rollback()


def test_usuario_nao_aponta_para_unidade_inexistente(
    fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    from sqlalchemy.exc import IntegrityError

    from app.services import usuario as usuario_service
    from app.services.auditoria import ContextoRequisicao
    from app.services.usuario import ErroCadastro, NovoUsuario

    cpf = gerar_cpf()
    dados = NovoUsuario(
        cpf=cpf,
        nome="Ana",
        email=f"f{cpf}@recife.pe.gov.br",
        senha="Saúde#Recife2026",
        id_unidade=2_000_000,
    )
    with fabrica_sessao() as db, db.begin(), pytest.raises((ErroCadastro, IntegrityError)):
        usuario_service.cadastrar(db, settings_integracao, dados, ContextoRequisicao())


def test_app_user_inclui_e_remove_vinculos_mas_nao_altera(app_conn: Conn) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute(
            "UPDATE app.unidade_saude_servico_saude SET fk_servico_saude_id_servico = 1"
        )
    app_conn.rollback()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute("UPDATE app.tipo_oci_cid SET fk_tipo_oci_tipo_oci_id = 1")
    app_conn.rollback()


# --- Migration: códigos já digitados ------------------------------------------------------


@pytest.fixture
def banco_em_0010() -> Iterator[BancoTeste]:
    with banco_temporario("0010") as banco:
        yield banco


def test_migration_preserva_codigo_de_unidade_ja_digitado(
    banco_em_0010: BancoTeste, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from alembic import command
    from alembic.config import Config

    from app.core.db_url import MIGRATOR_DB_ROLE, build_database_url, tls_do_ambiente

    banco = banco_em_0010
    migrator = os.environ["MIGRATOR_DB_PASSWORD"]
    with banco.connect(MIGRATOR_DB_ROLE, migrator) as conn:
        conn.execute("SET search_path TO app")
        conn.execute(
            """
            INSERT INTO usuario (cpf_hash, email_hash, cpf_cripto, nome_cripto, email_cripto,
                                 dek_cripto, kek_versao, senha_hash, id_unidade)
            VALUES (%s, %s, 'x', 'x', 'x', 'x', 1, 'x', 42)
            """,
            (b"a" * 32, b"b" * 32),
        )
        conn.commit()
    url = build_database_url(
        user=MIGRATOR_DB_ROLE,
        password=migrator,
        database=banco.name,
        host=banco.host,
        port=banco.port,
        tls=tls_do_ambiente(),
    )
    monkeypatch.setenv("MIGRATION_DATABASE_URL", url.render_as_string(hide_password=False))
    command.upgrade(Config(str(ALEMBIC_INI)), "head")

    with banco.connect(MIGRATOR_DB_ROLE, migrator) as conn:
        nome = conn.execute("SELECT nome FROM app.unidade_saude WHERE id_unidade = 42").fetchone()
        assert nome == ("Unidade 42 (revisar cadastro)",)
        # A migration 0012 liga a unidade antiga ao tipo equivalente.
        tipo = conn.execute(
            """
            SELECT t.nome FROM app.unidade_saude u JOIN app.tipo_unidade t USING (id_tipo_unidade)
             WHERE u.id_unidade = 42
            """
        ).fetchone()
        assert tipo == ("Posto de Saúde",)
        # A sequência continua depois do código preservado: novas unidades não colidem.
        novo = conn.execute(
            """
            INSERT INTO app.unidade_saude (id_tipo_unidade, nome, endereco)
            VALUES (3, 'Nova', 'Rua A') RETURNING id_unidade
            """
        ).fetchone()
        assert novo == (43,)
        conn.rollback()
