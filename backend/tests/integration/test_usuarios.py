"""RF-01 / THREAT_MODEL E1, T4, R1: gestão de usuários pelo Administrador (ADR-0017)."""

import uuid
from urllib.parse import parse_qs, urlparse

import pyotp
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core import senha as senha_mod
from app.core.config import Settings
from app.core.cpf import formatar_cpf
from app.core.crypto import FinalidadeHash, hash_busca
from app.models import Log, Sessao, Usuario
from app.repositories import rbac as rbac_repo

from .conftest import gerar_cpf
from .test_pacientes import Logado, Logar, logar  # noqa: F401

Fabrica = sessionmaker[Session]
PERFIS = ["Gestor", "Gestor do Cuidado", "Navegador", "Auditor", None]


def _novo(**extra: object) -> dict[str, object]:
    cpf = gerar_cpf()
    return {
        "cpf": formatar_cpf(cpf),
        "nome": "Joana Prado",
        "email": f"j{cpf}@recife.pe.gov.br",
        **extra,
    }


def _criar(api: TestClient, **extra: object) -> dict[str, object]:
    resp = api.post("/usuarios", json=_novo(**extra))
    assert resp.status_code == 201, resp.text
    corpo: dict[str, object] = resp.json()
    return corpo


def _unidade(api: TestClient) -> int:
    resp = api.post(
        "/unidades",
        json={
            "nome": f"Unidade {uuid.uuid4().hex}",
            "id_tipo_unidade": 1,  # tipo inicial da migration 0012
            "endereco": "Rua das Flores, 10",
        },
    )
    assert resp.status_code == 201, resp.text
    return int(resp.json()["id"])


def _id(criado: dict[str, object]) -> str:
    usuario = criado["usuario"]
    assert isinstance(usuario, dict)
    return str(usuario["id"])


def _ultimo(fabrica: Fabrica, acao: str) -> Log:
    with fabrica() as db:
        return db.scalars(
            select(Log).where(Log.acao == acao).order_by(Log.seq_cadeia.desc()).limit(1)
        ).one()


@pytest.fixture
def admin(logar: Logar) -> Logado:  # noqa: F811
    return logar("Administrador")


# --- Autorização -------------------------------------------------------------------------


@pytest.mark.parametrize("perfil", PERFIS)
def test_so_administrador_gerencia_usuarios(
    logar: Logar,  # noqa: F811
    admin: Logado,
    perfil: str | None,
) -> None:
    alvo = _id(_criar(admin.api))
    api = logar(perfil).api
    url = f"/usuarios/{alvo}"
    assert api.post("/usuarios/lista", json={}).status_code == 403
    assert api.get("/usuarios/grupos").status_code == 403
    assert api.get(url).status_code == 403
    assert api.post("/usuarios", json=_novo()).status_code == 403
    assert api.patch(url, json={"nome": "Outro Nome"}).status_code == 403
    assert api.delete(url).status_code == 403
    assert api.post(f"{url}/reativar").status_code == 403
    assert api.post(f"{url}/resetar").status_code == 403
    assert api.post(f"{url}/grupos", json={"grupos": ["Administrador"]}).status_code == 403


def test_sem_sessao_e_sem_csrf(app_teste: FastAPI, admin: Logado) -> None:
    with TestClient(app_teste, base_url="https://testserver") as anonimo:
        assert anonimo.post("/usuarios/lista", json={}).status_code == 401
    del admin.api.headers["X-CSRF-Token"]
    assert admin.api.post("/usuarios", json=_novo()).status_code == 403


# --- Cadastro e primeiro acesso ----------------------------------------------------------


def test_cadastro_gera_senha_temporaria_valida_e_obriga_troca(
    app_teste: FastAPI, admin: Logado, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    dados = _novo(grupos=["Navegador"], id_unidade=_unidade(admin.api))
    resp = admin.api.post("/usuarios", json=dados)
    assert resp.status_code == 201
    assert resp.headers["cache-control"] == "no-store"
    corpo = resp.json()
    usuario = corpo["usuario"]
    assert usuario["cpf"] == dados["cpf"] and usuario["nome"] == "Joana Prado"
    assert usuario["grupos"] == ["Navegador"] and usuario["id_unidade"] == dados["id_unidade"]
    assert usuario["unidade_nome"] is not None
    assert usuario["troca_senha_obrigatoria"] is True and usuario["mfa_ativo"] is False
    assert usuario["proprio"] is False
    temporaria = corpo["senha_temporaria"]
    assert senha_mod.problemas_politica(temporaria) == []

    cpf = str(dados["cpf"])
    with TestClient(app_teste, base_url="https://testserver") as novo:
        assert novo.post("/auth/login", json={"cpf": cpf, "senha": temporaria}).status_code == 200
        uri = novo.post("/auth/mfa/cadastro").json()["otpauth_uri"]
        segredo = parse_qs(urlparse(uri).query)["secret"][0]
        codigo = pyotp.TOTP(segredo).now()
        assert novo.post("/auth/mfa/ativar", json={"codigo": codigo}).status_code == 200
        assert novo.get("/auth/sessao").json()["troca_senha_obrigatoria"] is True
        # Até trocar a senha, não acessa nada que exija sessão liberada.
        assert novo.post("/pacientes/busca", json={"cpf": cpf}).status_code == 403


def test_senha_temporaria_e_dados_nao_vao_para_o_log(
    admin: Logado, fabrica_sessao: Fabrica
) -> None:
    dados = _novo(nome="Severina Sigilosa")
    corpo = admin.api.post("/usuarios", json=dados).json()
    with fabrica_sessao() as db:
        recentes = db.scalars(select(Log).order_by(Log.seq_cadeia.desc()).limit(5)).all()
    texto = " ".join(str(e.resumo_acessado) for e in recentes)
    assert corpo["senha_temporaria"] not in texto
    assert "Severina" not in texto and str(dados["cpf"]) not in texto
    assert str(dados["email"]) not in texto


def test_cadastro_registra_quem_fez_e_sobre_quem(
    admin: Logado, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    dados = _novo(grupos=["Gestor"])
    admin.api.post("/usuarios", json=dados)
    chave = settings_integracao.chave_hmac
    autor = hash_busca(chave, FinalidadeHash.CPF, admin.cpf)
    alvo = hash_busca(chave, FinalidadeHash.CPF, str(dados["cpf"])).hex()[:12]
    for acao in ("user_created", "role_change"):
        evento = _ultimo(fabrica_sessao, acao)
        assert evento.cpf_usuario_hash == autor
        assert evento.resumo_acessado["usuario_alvo"] == alvo


@pytest.mark.parametrize("campo", ["cpf", "email"])
def test_duplicado_recusado_com_erro_generico(admin: Logado, campo: str) -> None:
    primeiro = _novo()
    assert admin.api.post("/usuarios", json=primeiro).status_code == 201
    segundo = _novo(**{campo: primeiro[campo]})
    resp = admin.api.post("/usuarios", json=segundo)
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Não foi possível cadastrar o usuário."}


@pytest.mark.parametrize(
    "extra",
    [
        {"cpf": "111.111.111-11"},
        {"email": "nao-e-email"},
        {"senha": "Definida#PeloAdmin1"},  # admin não define senha
        {"id_unidade": 0},
        {"status": "inativo"},
    ],
)
def test_entrada_invalida(admin: Logado, extra: dict[str, object]) -> None:
    resp = admin.api.post("/usuarios", json=_novo(**extra))
    assert resp.status_code == 422
    assert "111.111.111-11" not in resp.text and "Definida" not in resp.text


def test_grupo_inexistente_nao_cria_o_usuario(admin: Logado, fabrica_sessao: Fabrica) -> None:
    dados = _novo(grupos=["Inventado"])
    resp = admin.api.post("/usuarios", json=dados)
    assert resp.status_code == 422
    assert resp.json() == {"detail": "Grupo inválido."}


# --- Lista e consulta --------------------------------------------------------------------


def test_lista_tem_cpf_mascarado_e_nada_de_email(admin: Logado) -> None:
    dados = _novo(grupos=["Auditor"])
    criado = admin.api.post("/usuarios", json=dados).json()
    resp = admin.api.post("/usuarios/lista", json={})
    item = resp.json()["itens"][0]
    cpf = str(dados["cpf"])
    assert item == {
        "id": criado["usuario"]["id"],
        "cpf_mascarado": f"***.{cpf[4:7]}.{cpf[8:11]}-**",
        "nome": "Joana Prado",
        "status": "ativo",
        "grupos": ["Auditor"],
    }
    assert cpf not in resp.text and str(dados["email"]) not in resp.text


def test_lista_percorre_as_paginas_sem_repetir(admin: Logado) -> None:
    criados = {_id(_criar(admin.api)) for _ in range(22)}
    vistos: list[str] = []
    depois = None
    while True:
        corpo = admin.api.post("/usuarios/lista", json={"depois": depois}).json()
        assert len(corpo["itens"]) <= 20
        vistos += [i["id"] for i in corpo["itens"]]
        depois = corpo["proximo"]
        if depois is None:
            break
    assert len(vistos) == len(set(vistos)) and criados <= set(vistos)


def test_cadastro_adulterado_nao_derruba_a_lista(admin: Logado, fabrica_sessao: Fabrica) -> None:
    bom = _id(_criar(admin.api))
    ruim = _id(_criar(admin.api))
    with fabrica_sessao() as db, db.begin():
        registro = db.scalars(select(Usuario).where(Usuario.id_publico == uuid.UUID(ruim))).one()
        registro.nome_cripto = b"adulterado" * 8
    resp = admin.api.post("/usuarios/lista", json={})
    assert resp.status_code == 200
    itens = {i["id"]: i for i in resp.json()["itens"]}
    assert itens[ruim]["nome"] is None and itens[ruim]["cpf_mascarado"] is None
    assert itens[bom]["nome"] == "Joana Prado"
    evento = _ultimo(fabrica_sessao, "sensitive_data_access")
    assert evento.resumo_acessado["ilegiveis"] == [ruim]
    detalhe = admin.api.get(f"/usuarios/{ruim}")
    assert detalhe.status_code == 409
    assert detalhe.json() == {"detail": "Não foi possível ler este cadastro."}


def test_lista_com_cursor_desconhecido(admin: Logado) -> None:
    resp = admin.api.post("/usuarios/lista", json={"depois": str(uuid.uuid4())})
    assert resp.json() == {"itens": [], "proximo": None}


def test_consulta_devolve_dados_e_e_auditada(admin: Logado, fabrica_sessao: Fabrica) -> None:
    dados = _novo()
    alvo = _id(admin.api.post("/usuarios", json=dados).json())
    corpo = admin.api.get(f"/usuarios/{alvo}").json()
    assert corpo["cpf"] == dados["cpf"] and corpo["email"] == dados["email"]
    assert "senha" not in str(corpo).lower().replace("troca_senha_obrigatoria", "")
    evento = _ultimo(fabrica_sessao, "sensitive_data_access")
    assert evento.resumo_acessado["recurso"] == "usuario"
    assert evento.resumo_acessado["origem"] == "consulta"


@pytest.mark.parametrize("id_invalido", ["1", "1%20OR%201=1", "../pacientes"])
def test_identificador_manipulado_e_recusado(admin: Logado, id_invalido: str) -> None:
    assert admin.api.get(f"/usuarios/{id_invalido}").status_code in (404, 405, 422)


def test_inexistente_devolve_404(admin: Logado) -> None:
    url = f"/usuarios/{uuid.uuid4()}"
    assert admin.api.get(url).status_code == 404
    assert admin.api.patch(url, json={"nome": "Outro Nome"}).status_code == 404
    assert admin.api.delete(url).status_code == 404
    assert admin.api.post(f"{url}/reativar").status_code == 404
    assert admin.api.post(f"{url}/resetar").status_code == 404
    assert admin.api.post(f"{url}/grupos", json={"grupos": []}).status_code == 404


def test_grupos_disponiveis(admin: Logado) -> None:
    grupos = admin.api.get("/usuarios/grupos").json()["grupos"]
    assert {"Administrador", "Gestor", "Gestor do Cuidado", "Navegador", "Auditor"} <= set(grupos)


# --- Edição ------------------------------------------------------------------------------


def test_edicao_parcial_e_login_pelo_cpf_continua(
    admin: Logado, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    id_unidade = _unidade(admin.api)
    dados = _novo(id_unidade=id_unidade)
    alvo = _id(admin.api.post("/usuarios", json=dados).json())
    url = f"/usuarios/{alvo}"
    corpo = admin.api.patch(url, json={"nome": "Joana Lima"}).json()
    assert corpo["nome"] == "Joana Lima" and corpo["email"] == dados["email"]
    assert corpo["id_unidade"] == id_unidade
    novo_email = f"novo{gerar_cpf()}@recife.pe.gov.br"
    corpo = admin.api.patch(url, json={"email": novo_email.upper(), "id_unidade": None}).json()
    assert corpo["email"] == novo_email and corpo["id_unidade"] is None
    evento = _ultimo(fabrica_sessao, "user_updated")
    assert evento.resumo_acessado["campos"] == ["email", "id_unidade"]
    assert novo_email not in str(evento.resumo_acessado)
    with fabrica_sessao() as db:
        registro = db.scalars(select(Usuario).where(Usuario.id_publico == uuid.UUID(alvo))).one()
        chave = settings_integracao.chave_hmac
        assert registro.email_hash == hash_busca(chave, FinalidadeHash.EMAIL, novo_email)
        assert novo_email.encode() not in registro.email_cripto


def test_email_de_outra_pessoa_e_recusado(admin: Logado) -> None:
    outro = _novo()
    admin.api.post("/usuarios", json=outro)
    alvo = _id(_criar(admin.api))
    resp = admin.api.patch(f"/usuarios/{alvo}", json={"email": outro["email"]})
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Não foi possível salvar os dados."}


@pytest.mark.parametrize(
    "corpo", [{}, {"cpf": "12345678909"}, {"nome": None}, {"email": None}, {"status": "ativo"}]
)
def test_edicao_invalida(admin: Logado, corpo: dict[str, object]) -> None:
    alvo = _id(_criar(admin.api))
    assert admin.api.patch(f"/usuarios/{alvo}", json=corpo).status_code == 422


# --- Inativar, reativar e resetar --------------------------------------------------------


def test_inativar_encerra_sessoes_e_impede_login(
    logar: Logar,  # noqa: F811
    admin: Logado,
    fabrica_sessao: Fabrica,
    settings_integracao: Settings,
) -> None:
    alvo = logar("Navegador")
    assert alvo.api.get("/auth/sessao").status_code == 200
    with fabrica_sessao() as db:
        registro = db.get(
            Usuario, hash_busca(settings_integracao.chave_hmac, FinalidadeHash.CPF, alvo.cpf)
        )
        assert registro is not None
        id_alvo = registro.id_publico
    assert admin.api.delete(f"/usuarios/{id_alvo}").status_code == 204
    assert alvo.api.get("/auth/sessao").status_code == 401
    evento = _ultimo(fabrica_sessao, "user_deactivated")
    assert evento.resumo_acessado["sessoes_encerradas"] == 1
    assert admin.api.get(f"/usuarios/{id_alvo}").json()["status"] == "inativo"

    assert admin.api.post(f"/usuarios/{id_alvo}/reativar").status_code == 204
    assert admin.api.get(f"/usuarios/{id_alvo}").json()["status"] == "ativo"
    assert _ultimo(fabrica_sessao, "user_reactivated").cpf_usuario_hash is not None


def test_resetar_gera_nova_senha_e_zera_mfa(
    admin: Logado, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    dados = _novo()
    criado = admin.api.post("/usuarios", json=dados).json()
    alvo = criado["usuario"]["id"]
    resp = admin.api.post(f"/usuarios/{alvo}/resetar")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    nova = resp.json()["senha_temporaria"]
    assert nova != criado["senha_temporaria"]
    corpo = admin.api.get(f"/usuarios/{alvo}").json()
    assert corpo["troca_senha_obrigatoria"] is True and corpo["mfa_ativo"] is False
    evento = _ultimo(fabrica_sessao, "access_reset")
    chave = settings_integracao.chave_hmac
    assert evento.cpf_usuario_hash == hash_busca(chave, FinalidadeHash.CPF, admin.cpf)
    assert nova not in str(evento.resumo_acessado)


# --- Proteções contra perder o acesso ----------------------------------------------------


def _meu_id(admin: Logado, fabrica: Fabrica, settings: Settings) -> str:
    with fabrica() as db:
        registro = db.get(Usuario, hash_busca(settings.chave_hmac, FinalidadeHash.CPF, admin.cpf))
        assert registro is not None
        return str(registro.id_publico)


def test_nao_altera_a_propria_conta(
    admin: Logado, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    meu = _meu_id(admin, fabrica_sessao, settings_integracao)
    assert admin.api.get(f"/usuarios/{meu}").json()["proprio"] is True
    for resp in (
        admin.api.delete(f"/usuarios/{meu}"),
        admin.api.post(f"/usuarios/{meu}/reativar"),
        admin.api.post(f"/usuarios/{meu}/resetar"),
        admin.api.post(f"/usuarios/{meu}/grupos", json={"grupos": []}),
    ):
        assert resp.status_code == 409
    assert admin.api.get("/auth/sessao").json()["permissoes"]  # continua administrador


def test_resta_ao_menos_um_administrador(
    admin: Logado,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alvo = _id(_criar(admin.api, grupos=["Administrador"]))
    # O banco de teste tem outros administradores: simula que este seria o último.
    monkeypatch.setattr(rbac_repo, "outros_ativos_no_grupo", lambda *_a: 0)
    assert admin.api.delete(f"/usuarios/{alvo}").status_code == 409
    resp = admin.api.post(f"/usuarios/{alvo}/grupos", json={"grupos": []})
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Deve restar ao menos um administrador ativo."}
    monkeypatch.undo()
    assert admin.api.get(f"/usuarios/{alvo}").json()["grupos"] == ["Administrador"]
    assert admin.api.delete(f"/usuarios/{alvo}").status_code == 204


def test_contagem_de_administradores_ignora_inativos_e_o_proprio(
    admin: Logado, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    alvo = _id(_criar(admin.api, grupos=["Administrador"]))
    meu_hash = hash_busca(settings_integracao.chave_hmac, FinalidadeHash.CPF, admin.cpf)

    def outros() -> int:
        with fabrica_sessao() as db:
            return rbac_repo.outros_ativos_no_grupo(db, meu_hash, "Administrador")

    antes = outros()
    assert admin.api.delete(f"/usuarios/{alvo}").status_code == 204
    assert outros() == antes - 1


# --- Unidade -----------------------------------------------------------------------------


def test_unidade_precisa_existir_e_estar_ativa(admin: Logado) -> None:
    assert admin.api.post("/usuarios", json=_novo(id_unidade=2_000_000)).status_code == 422
    unidade = _unidade(admin.api)
    assert admin.api.delete(f"/unidades/{unidade}").status_code == 204
    resp = admin.api.post("/usuarios", json=_novo(id_unidade=unidade))
    assert resp.status_code == 422
    assert resp.json() == {"detail": "Unidade inválida."}
    alvo = _id(_criar(admin.api))
    assert admin.api.patch(f"/usuarios/{alvo}", json={"id_unidade": unidade}).status_code == 422


def test_troca_de_unidade_e_usuario_em_unidade_inativa(admin: Logado) -> None:
    a, b = _unidade(admin.api), _unidade(admin.api)
    alvo = _id(_criar(admin.api, id_unidade=a))
    url = f"/usuarios/{alvo}"
    corpo = admin.api.patch(url, json={"id_unidade": b}).json()
    assert corpo["id_unidade"] == b

    # Com usuário ativo a unidade não pode ser inativada; depois de movê-lo, pode.
    resp = admin.api.delete(f"/unidades/{b}")
    assert resp.status_code == 409
    assert "usuários ativos" in resp.json()["detail"]
    assert admin.api.delete(url).status_code == 204
    assert admin.api.delete(f"/unidades/{b}").status_code == 204
    assert admin.api.post(f"{url}/reativar").status_code == 204

    # Usuário preso a unidade inativa: mantém o valor ao editar outros campos.
    corpo = admin.api.patch(url, json={"nome": "Nome Novo", "id_unidade": b}).json()
    assert corpo["nome"] == "Nome Novo" and corpo["id_unidade"] == b


# --- Grupos ------------------------------------------------------------------------------


def test_definir_grupos_aplica_a_diferenca_e_vale_na_proxima_requisicao(
    logar: Logar,  # noqa: F811
    admin: Logado,
    fabrica_sessao: Fabrica,
    settings_integracao: Settings,
) -> None:
    alvo = logar("Navegador")
    with fabrica_sessao() as db:
        registro = db.get(
            Usuario, hash_busca(settings_integracao.chave_hmac, FinalidadeHash.CPF, alvo.cpf)
        )
        assert registro is not None
        url = f"/usuarios/{registro.id_publico}/grupos"
    assert "paciente:ler" in alvo.api.get("/auth/sessao").json()["permissoes"]
    corpo = admin.api.post(url, json={"grupos": ["Auditor"]}).json()
    assert corpo["grupos"] == ["Auditor"]
    permissoes = alvo.api.get("/auth/sessao").json()["permissoes"]
    assert permissoes == ["log:ler"]
    evento = _ultimo(fabrica_sessao, "role_change")
    assert evento.resumo_acessado["operacao"] == "remover"
    assert evento.resumo_acessado["grupo"] == "Navegador"


def test_sem_mudanca_de_grupo_nao_audita(admin: Logado, fabrica_sessao: Fabrica) -> None:
    alvo = _id(_criar(admin.api, grupos=["Gestor"]))
    antes = _ultimo(fabrica_sessao, "role_change").seq_cadeia
    resp = admin.api.post(f"/usuarios/{alvo}/grupos", json={"grupos": ["Gestor"]})
    assert resp.status_code == 200
    assert _ultimo(fabrica_sessao, "role_change").seq_cadeia == antes


def test_grupo_invalido_ao_definir(admin: Logado) -> None:
    alvo = _id(_criar(admin.api))
    resp = admin.api.post(f"/usuarios/{alvo}/grupos", json={"grupos": ["Inventado"]})
    assert resp.status_code == 422
    assert resp.json() == {"detail": "Grupo inválido."}


def test_sessao_do_usuario_inativado_some_do_banco(
    logar: Logar,  # noqa: F811
    admin: Logado,
    fabrica_sessao: Fabrica,
    settings_integracao: Settings,
) -> None:
    alvo = logar("Navegador")
    cpf_hash = hash_busca(settings_integracao.chave_hmac, FinalidadeHash.CPF, alvo.cpf)
    with fabrica_sessao() as db:
        registro = db.get(Usuario, cpf_hash)
        assert registro is not None
        id_alvo = registro.id_publico
    admin.api.delete(f"/usuarios/{id_alvo}")
    with fabrica_sessao() as db:
        assert db.scalars(select(Sessao).where(Sessao.cpf_hash == cpf_hash)).first() is None
