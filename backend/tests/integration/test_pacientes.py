"""RF-03 / THREAT_MODEL E1, E2, T4, I1, R1: pacientes com RBAC, cifragem e auditoria."""

import uuid
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from datetime import UTC, date, datetime, timedelta
from typing import Any, NamedTuple
from urllib.parse import parse_qs, urlparse

import psycopg
import pyotp
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core import totp
from app.core.config import Settings
from app.core.cpf import formatar_cpf
from app.core.crypto import (
    DekCifrada,
    ErroCriptografia,
    FinalidadeHash,
    abrir_dek,
    decifrar_campo,
    hash_busca,
)
from app.models import Log, Paciente
from app.repositories import rbac as rbac_repo
from app.services import autorizacao
from app.services import usuario as usuario_service
from app.services.auditoria import ContextoRequisicao
from app.services.usuario import NovoUsuario

from .conftest import com_csrf, gerar_cpf

SENHA = "Saúde#Recife2026"
Fabrica = sessionmaker[Session]
Conn = psycopg.Connection[tuple[object, ...]]


class Logado(NamedTuple):
    api: TestClient
    cpf: str


Logar = Callable[[str | None], Logado]
PERFIS = ["Administrador", "Gestor", "Gestor do Cuidado", "Navegador", "Auditor", None]


@pytest.fixture
def logar(
    app_teste: FastAPI, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> Iterator[Logar]:
    """Cria um usuário no grupo indicado (None = sem grupo) e devolve um cliente já logado."""
    with ExitStack() as pilha:

        def _logar(grupo: str | None) -> Logado:
            cpf = gerar_cpf()
            dados = NovoUsuario(cpf=cpf, nome="Ana", email=f"a{cpf}@recife.pe.gov.br", senha=SENHA)
            with fabrica_sessao() as db, db.begin():
                usuario_service.cadastrar(db, settings_integracao, dados, ContextoRequisicao())
                if grupo:
                    autorizacao.alterar_grupo(
                        db,
                        settings_integracao,
                        cpf=cpf,
                        grupo=grupo,
                        remover=False,
                        ctx=ContextoRequisicao(),
                    )
            api = pilha.enter_context(TestClient(app_teste, base_url="https://testserver"))
            assert api.post("/auth/login", json={"cpf": cpf, "senha": SENHA}).status_code == 200
            uri = api.post("/auth/mfa/cadastro").json()["otpauth_uri"]
            segredo = parse_qs(urlparse(uri).query)["secret"][0]
            codigo = pyotp.TOTP(segredo).at(totp.passo(datetime.now(UTC)) * 30)
            assert api.post("/auth/mfa/ativar", json={"codigo": codigo}).status_code == 200
            return Logado(com_csrf(api), cpf)

        yield _logar


def _novo(cpf: str | None = None, **extra: Any) -> dict[str, object]:
    return {
        "cpf": formatar_cpf(cpf or gerar_cpf()),
        "nome": "José da Silva",
        "data_nascimento": "1980-05-17",
        "email": "Jose.Silva@Exemplo.com.br",
        **extra,
    }


@pytest.fixture
def admin(logar: Logar) -> TestClient:
    return logar("Administrador").api


@pytest.fixture
def paciente(admin: TestClient) -> dict[str, object]:
    resp = admin.post("/pacientes", json=_novo())
    assert resp.status_code == 201, resp.text
    corpo: dict[str, object] = resp.json()
    return corpo


def _eventos(fabrica: Fabrica, acao: str) -> list[Log]:
    with fabrica() as db:
        return list(db.scalars(select(Log).where(Log.acao == acao).order_by(Log.seq_cadeia)))


# --- CRUD --------------------------------------------------------------------------------


def test_cadastro_e_consulta(admin: TestClient) -> None:
    dados = _novo()
    resp = admin.post("/pacientes", json=dados)
    assert resp.status_code == 201
    assert resp.headers["cache-control"] == "no-store"
    corpo = resp.json()
    assert corpo["cpf"] == dados["cpf"]
    assert corpo["email"] == "jose.silva@exemplo.com.br"  # normalizado
    assert corpo["status"] == "ativo"
    uuid.UUID(corpo["id"])

    consulta = admin.get(f"/pacientes/{corpo['id']}")
    assert consulta.status_code == 200
    assert consulta.json() == corpo

    busca = admin.post("/pacientes/busca", json={"cpf": str(dados["cpf"]).replace(".", "")})
    assert busca.status_code == 200
    assert busca.json()["id"] == corpo["id"]


def test_cadastro_sem_email(admin: TestClient) -> None:
    dados = _novo()
    del dados["email"]
    resp = admin.post("/pacientes", json=dados)
    assert resp.status_code == 201
    assert resp.json()["email"] is None


def test_cpf_duplicado_recusado_com_erro_generico(admin: TestClient) -> None:
    dados = _novo()
    assert admin.post("/pacientes", json=dados).status_code == 201
    resp = admin.post("/pacientes", json={**dados, "nome": "Outro Nome"})
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Não foi possível cadastrar o paciente."}


def test_alteracao_parcial_e_remocao_de_email(
    admin: TestClient, paciente: dict[str, object]
) -> None:
    url = f"/pacientes/{paciente['id']}"
    resp = admin.patch(url, json={"nome": "José S. Filho"})
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["nome"] == "José S. Filho"
    assert corpo["data_nascimento"] == paciente["data_nascimento"]
    assert corpo["email"] == paciente["email"]
    assert corpo["atualizado_em"] > str(paciente["atualizado_em"])

    resp = admin.patch(url, json={"email": None, "data_nascimento": "1981-01-02"})
    assert resp.json()["email"] is None
    assert resp.json()["data_nascimento"] == "1981-01-02"


@pytest.mark.parametrize(
    "corpo",
    [
        {},
        {"nome": None},
        {"data_nascimento": None},
        {"cpf": "529.982.247-25"},  # CPF é imutável: campo não aceito
        {"status": "inativo"},
    ],
)
def test_alteracao_invalida(admin: TestClient, paciente: dict[str, object], corpo: object) -> None:
    resp = admin.patch(f"/pacientes/{paciente['id']}", json=corpo)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Dados inválidos."


def test_inativar_reativar(admin: TestClient, paciente: dict[str, object]) -> None:
    url = f"/pacientes/{paciente['id']}"
    assert admin.delete(url).status_code == 204
    assert admin.get(url).json()["status"] == "inativo"
    assert admin.delete(url).status_code == 204  # idempotente
    assert admin.patch(url, json={"nome": "Novo Nome"}).status_code == 409
    assert admin.post(f"{url}/reativar").status_code == 204
    assert admin.get(url).json()["status"] == "ativo"


def test_inexistente_devolve_404(admin: TestClient) -> None:
    url = f"/pacientes/{uuid.uuid4()}"
    assert admin.get(url).status_code == 404
    assert admin.patch(url, json={"nome": "Fulano"}).status_code == 404
    assert admin.delete(url).status_code == 404
    assert admin.post(f"{url}/reativar").status_code == 404
    assert admin.post("/pacientes/busca", json={"cpf": gerar_cpf()}).status_code == 404


@pytest.mark.parametrize(
    "id_invalido", ["1", "../usuario", "00000000-0000-0000-0000-00000000000g", "%27%20OR%201=1"]
)
def test_identificador_manipulado_e_recusado(admin: TestClient, id_invalido: str) -> None:
    # T4: só UUID é aceito; nada vira SQL ou caminho.
    assert admin.get(f"/pacientes/{id_invalido}").status_code in (404, 422)


# --- Validação ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("cpf", "111.111.111-11"),
        ("cpf", "123.456.789-00"),
        ("nome", "J"),
        ("nome", "x" * 151),
        ("nome", "José\x00Silva"),
        ("data_nascimento", (date.today() + timedelta(days=2)).isoformat()),
        ("data_nascimento", "1850-01-01"),
        ("data_nascimento", "17/05/1980"),
        ("data_nascimento", 327_456_000),
        ("email", "nao-e-email"),
        ("extra", "campo desconhecido"),
    ],
)
def test_entrada_invalida_nao_ecoa_valor(admin: TestClient, campo: str, valor: Any) -> None:
    resp = admin.post("/pacientes", json=_novo(**{campo: valor}))
    assert resp.status_code == 422
    assert resp.json()["campos"] == [campo]
    assert str(valor) not in resp.text


# --- Autorização (E1) --------------------------------------------------------------------

ESPERADO = {
    # perfil: (ler, criar, editar, inativar)
    "Administrador": (True, True, True, True),
    "Gestor": (True, True, True, False),
    "Gestor do Cuidado": (True, True, True, False),
    "Navegador": (True, True, True, False),
    "Auditor": (False, False, False, False),
    None: (False, False, False, False),
}
# Só acesso global: os demais têm visão restrita pela SPEC, sem recorte por unidade ainda.
PODEM_LISTAR = {"Administrador", "Gestor"}


@pytest.mark.parametrize("perfil", PERFIS)
def test_permissoes_por_perfil(
    logar: Logar, paciente: dict[str, object], perfil: str | None
) -> None:
    api = logar(perfil).api
    ler, criar, editar, inativar = ESPERADO[perfil]
    url = f"/pacientes/{paciente['id']}"

    def confere(resp_status: int, permitido: bool, ok: int) -> None:
        assert resp_status == (ok if permitido else 403)

    confere(api.get(url).status_code, ler, 200)
    confere(api.post("/pacientes/busca", json={"cpf": paciente["cpf"]}).status_code, ler, 200)
    confere(api.post("/pacientes", json=_novo()).status_code, criar, 201)
    confere(api.patch(url, json={"nome": "Nome Alterado"}).status_code, editar, 200)
    confere(api.delete(url).status_code, inativar, 204)
    confere(api.post(f"{url}/reativar").status_code, inativar, 204)

    listar = perfil in PODEM_LISTAR
    confere(api.post("/pacientes/lista", json={}).status_code, listar, 200)

    permissoes = api.get("/auth/sessao").json()["permissoes"]
    nomes = ("paciente:ler", "paciente:criar", "paciente:editar", "paciente:inativar")
    esperadas = [n for n, ok in zip(nomes, ESPERADO[perfil], strict=True) if ok]
    extras = ["paciente:listar"] if listar else []
    extras += ["log:ler"] if perfil in ("Administrador", "Auditor") else []
    assert permissoes == sorted([*esperadas, *extras])


# --- Lista de pacientes (ADR-0014) ---------------------------------------------------------


def test_lista_so_tem_dados_resumidos_e_cpf_mascarado(admin: TestClient) -> None:
    dados = _novo(nome="Lúcia Listada")
    criado = admin.post("/pacientes", json=dados).json()
    resp = admin.post("/pacientes/lista", json={})
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    item = resp.json()["itens"][0]  # o mais recente vem primeiro
    cpf = str(dados["cpf"])
    assert item == {
        "id": criado["id"],
        "cpf_mascarado": f"***.{cpf[4:7]}.{cpf[8:11]}-**",
        "nome": "Lúcia Listada",
        "status": "ativo",
    }
    assert cpf not in resp.text and cpf.replace(".", "").replace("-", "") not in resp.text
    assert "1980-05-17" not in resp.text and "exemplo.com.br" not in resp.text


def test_lista_percorre_todas_as_paginas_sem_repetir(admin: TestClient) -> None:
    criados = {admin.post("/pacientes", json=_novo()).json()["id"] for _ in range(25)}
    vistos: list[str] = []
    depois = None
    while True:
        corpo = admin.post("/pacientes/lista", json={"depois": depois}).json()
        assert len(corpo["itens"]) <= 20
        vistos += [i["id"] for i in corpo["itens"]]
        depois = corpo["proximo"]
        if depois is None:
            break
    assert len(vistos) == len(set(vistos))
    assert criados <= set(vistos)


def test_lista_mostra_inativos(admin: TestClient, paciente: dict[str, object]) -> None:
    assert admin.delete(f"/pacientes/{paciente['id']}").status_code == 204
    itens = admin.post("/pacientes/lista", json={}).json()["itens"]
    assert next(i for i in itens if i["id"] == paciente["id"])["status"] == "inativo"


@pytest.mark.parametrize(
    "corpo",
    [{"depois": "1 OR 1=1"}, {"depois": 1}, {"limite": 100000}, {"status": "ativo"}, []],
)
def test_lista_recusa_entrada_invalida(admin: TestClient, corpo: object) -> None:
    assert admin.post("/pacientes/lista", json=corpo).status_code == 422


def test_lista_com_cursor_desconhecido_nao_devolve_dados(admin: TestClient) -> None:
    resp = admin.post("/pacientes/lista", json={"depois": str(uuid.uuid4())})
    assert resp.status_code == 200
    assert resp.json() == {"itens": [], "proximo": None}


def test_lista_exige_token_csrf(admin: TestClient) -> None:
    del admin.headers["X-CSRF-Token"]
    assert admin.post("/pacientes/lista", json={}).status_code == 403


def test_lista_auditada_sem_dado_pessoal(admin: TestClient, fabrica_sessao: Fabrica) -> None:
    dados = _novo(nome="Severina Listada")
    criado = admin.post("/pacientes", json=dados).json()
    admin.post("/pacientes/lista", json={})
    with fabrica_sessao() as db:
        evento = db.scalars(
            select(Log)
            .where(Log.acao == "sensitive_data_access", Log.cpf_paciente_hash.is_(None))
            .order_by(Log.seq_cadeia.desc())
            .limit(1)
        ).one()
    resumo = evento.resumo_acessado
    assert evento.cpf_usuario_hash is not None
    assert resumo["recurso"] == "paciente" and resumo["origem"] == "lista"
    assert criado["id"] in resumo["pacientes"]
    texto = str(resumo)
    assert "Severina" not in texto and str(dados["cpf"]) not in texto


def test_negado_responde_generico_e_e_auditado(
    logar: Logar, paciente: dict[str, object], fabrica_sessao: Fabrica
) -> None:
    auditor = logar("Auditor").api
    resp = auditor.get(f"/pacientes/{paciente['id']}")
    assert resp.status_code == 403
    assert resp.json() == {"detail": "Acesso negado."}
    negado = _eventos(fabrica_sessao, "access_denied")[-1]
    assert negado.resumo_acessado == {"permissao": "paciente:ler"}
    assert negado.cpf_paciente_hash is None  # nada do paciente vaza na negativa


def test_sem_sessao_devolve_401(app_teste: FastAPI, paciente: dict[str, object]) -> None:
    with TestClient(app_teste, base_url="https://testserver") as anonimo:
        assert anonimo.get(f"/pacientes/{paciente['id']}").status_code == 401
        assert anonimo.post("/pacientes", json=_novo()).status_code == 401


def test_mudanca_de_grupo_vale_na_proxima_requisicao(
    logar: Logar,
    paciente: dict[str, object],
    fabrica_sessao: Fabrica,
    settings_integracao: Settings,
) -> None:
    api, cpf = logar("Navegador")
    url = f"/pacientes/{paciente['id']}"
    assert api.get(url).status_code == 200
    with fabrica_sessao() as db, db.begin():
        assert autorizacao.alterar_grupo(
            db,
            settings_integracao,
            cpf=cpf,
            grupo="Navegador",
            remover=True,
            ctx=ContextoRequisicao(),
        )
    assert api.get(url).status_code == 403
    evento = _eventos(fabrica_sessao, "role_change")[-1]
    assert evento.resumo_acessado == {"grupo": "Navegador", "operacao": "remover"}


def test_papel_inativo_nao_concede_permissao(
    logar: Logar, settings_integracao: Settings, sessao_superusuario: Session
) -> None:
    # Desativar o papel corta o acesso: a consulta só considera papel/grupo/permissão ativos.
    cpf = logar("Navegador").cpf
    cpf_hash = hash_busca(settings_integracao.chave_hmac, FinalidadeHash.CPF, cpf)
    db = sessao_superusuario
    assert rbac_repo.permissoes(db, cpf_hash)
    db.execute(text("UPDATE app.papel SET status = 'inativo' WHERE papel = 'Navegador'"))
    assert rbac_repo.permissoes(db, cpf_hash) == frozenset()


# --- Dados cifrados no banco (I1) e auditoria (R1) ---------------------------------------


def test_banco_guarda_so_dados_cifrados(
    admin: TestClient, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    dados = _novo(nome="Maria Aparecida Teste")
    corpo = admin.post("/pacientes", json=dados).json()
    with fabrica_sessao() as db:
        p = db.scalars(select(Paciente).where(Paciente.id_publico == uuid.UUID(corpo["id"]))).one()
    bruto = b"".join(
        (p.cpf_hash, p.cpf_cripto, p.nome_cripto, p.data_nascimento_cripto, p.email_cripto or b"")
    )
    cpf_digitos = str(dados["cpf"]).replace(".", "").replace("-", "")
    for claro in (cpf_digitos, "Maria", "1980-05-17", "exemplo.com.br"):
        assert claro.encode() not in bruto

    # AAD: o valor cifrado de um paciente não decifra como se fosse de outro registro/coluna.
    dek = abrir_dek(settings_integracao.keyring, DekCifrada(p.dek_cripto, p.kek_versao))
    with pytest.raises(ErroCriptografia):
        decifrar_campo(
            dek, p.nome_cripto, tabela="paciente", coluna="nome_cripto", id_registro=b"x" * 32
        )
    with pytest.raises(ErroCriptografia):
        decifrar_campo(
            dek, p.nome_cripto, tabela="paciente", coluna="email_cripto", id_registro=p.cpf_hash
        )


def test_app_user_nao_apaga_nem_altera_cpf(app_conn: Conn, paciente: dict[str, object]) -> None:
    for comando in (
        "DELETE FROM app.paciente WHERE id_publico = %s",
        "UPDATE app.paciente SET cpf_cripto = '\\x00' WHERE id_publico = %s",
        "UPDATE app.paciente SET dek_cripto = '\\x00' WHERE id_publico = %s",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app_conn.execute(comando, (paciente["id"],))
    for comando in (
        "UPDATE app.papel SET status = 'ativo'",
        "INSERT INTO app.grupo (grupo) VALUES ('x')",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app_conn.execute(comando)


def test_acessos_auditados_sem_dado_pessoal(
    admin: TestClient, fabrica_sessao: Fabrica, settings_integracao: Settings
) -> None:
    dados = _novo(nome="Severina Auditada")
    corpo = admin.post("/pacientes", json=dados).json()
    url = f"/pacientes/{corpo['id']}"
    admin.get(url)
    admin.post("/pacientes/busca", json={"cpf": dados["cpf"]})
    admin.patch(url, json={"nome": "Severina Alterada"})
    admin.delete(url)
    admin.post(f"{url}/reativar")

    with fabrica_sessao() as db:
        p = db.scalars(select(Paciente).where(Paciente.id_publico == uuid.UUID(corpo["id"]))).one()
        eventos = list(
            db.scalars(
                select(Log).where(Log.cpf_paciente_hash == p.cpf_hash).order_by(Log.seq_cadeia)
            )
        )
    acoes = [(e.acao, e.resumo_acessado) for e in eventos]
    assert acoes == [
        ("patient_created", {}),
        ("sensitive_data_access", {"recurso": "paciente", "origem": "consulta"}),
        ("patient_search", {"encontrado": True}),
        ("sensitive_data_access", {"recurso": "paciente", "origem": "busca"}),
        ("patient_updated", {"campos": ["nome"]}),
        ("patient_deactivated", {}),
        ("patient_reactivated", {}),
    ]
    assert all(e.cpf_usuario_hash is not None for e in eventos)
    texto = " ".join(str(e.resumo_acessado) for e in eventos)
    cpf_digitos = str(dados["cpf"]).replace(".", "").replace("-", "")
    for claro in ("Severina", cpf_digitos, "1980", "exemplo"):
        assert claro not in texto


# --- Script de atribuição de grupo -------------------------------------------------------


def _rodar_script(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, argv: list[str], resposta: str
) -> None:
    from scripts import atribuir_grupo

    monkeypatch.setattr("builtins.input", lambda _prompt: resposta)
    monkeypatch.setattr(atribuir_grupo, "get_settings", lambda: settings)
    atribuir_grupo.main(argv)


def test_script_atribui_e_remove_grupo(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings_integracao: Settings,
    logar: Logar,
) -> None:
    api, cpf = logar(None)
    argv = ["--cpf", cpf, "--grupo", "Gestor"]
    _rodar_script(monkeypatch, settings_integracao, argv, "CONFIRMAR")
    assert "incluído" in capsys.readouterr().out
    assert "paciente:ler" in api.get("/auth/sessao").json()["permissoes"]

    _rodar_script(monkeypatch, settings_integracao, argv, "CONFIRMAR")
    assert "Nada mudou" in capsys.readouterr().out

    _rodar_script(monkeypatch, settings_integracao, [*argv, "--remover"], "CONFIRMAR")
    assert "removido" in capsys.readouterr().out
    assert api.get("/auth/sessao").json()["permissoes"] == []


@pytest.mark.parametrize(
    ("argv", "resposta", "esperado"),
    [
        (["--cpf", "111.111.111-11", "--grupo", "Gestor"], "CONFIRMAR", "CPF inválido"),
        (["--cpf", "529.982.247-25", "--grupo", "Gestor"], "nao", "Cancelado"),
        (["--cpf", "529.982.247-25", "--grupo", "Gestor"], "CONFIRMAR", "Usuário não encontrado"),
    ],
)
def test_script_recusa_entradas_invalidas(
    monkeypatch: pytest.MonkeyPatch,
    settings_integracao: Settings,
    argv: list[str],
    resposta: str,
    esperado: str,
) -> None:
    with pytest.raises(SystemExit, match=esperado):
        _rodar_script(monkeypatch, settings_integracao, argv, resposta)


def test_script_lista_grupos_quando_grupo_inexiste(
    monkeypatch: pytest.MonkeyPatch, settings_integracao: Settings, logar: Logar
) -> None:
    cpf = logar(None).cpf
    with pytest.raises(SystemExit, match="Grupos: Administrador, Gestor"):
        _rodar_script(
            monkeypatch, settings_integracao, ["--cpf", cpf, "--grupo", "Root"], "CONFIRMAR"
        )


def test_corrida_de_cadastro_duplicado_vira_erro_generico(
    admin: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A checagem prévia passa nos dois cadastros simultâneos; a PK do banco barra o segundo.
    dados = _novo()
    assert admin.post("/pacientes", json=dados).status_code == 201
    monkeypatch.setattr("app.repositories.paciente.existe", lambda *_a, **_k: False)
    resp = admin.post("/pacientes", json=dados)
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Não foi possível cadastrar o paciente."}
