"""RF-09/10/11 / THREAT_MODEL E1, T2, R1: unidades, serviços e CID (ADR-0019)."""

import uuid
from collections.abc import Iterator

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
PODEM_LER = {"Administrador", "Gestor", "Gestor do Cuidado", "Navegador"}
PERFIS = [*sorted(PODEM_LER), "Auditor", None]


def _sufixo() -> str:
    return uuid.uuid4().hex[:10]


def _unidade(**extra: object) -> dict[str, object]:
    return {
        "nome": f"UBS {_sufixo()}",
        "tipo_unidade": "Posto de Saúde",
        "endereco": "Av. Norte, 100 - Recife",
        "telefone": "(81) 3355-0000",
        **extra,
    }


def _servico(**extra: object) -> dict[str, object]:
    return {"nome": f"Consulta {_sufixo()}", "descricao": "Consulta especializada", **extra}


_PROXIMO_CID = iter(range(1000))


def _cid(**extra: object) -> dict[str, object]:
    # Prefixo próprio por execução: não colide entre testes nem entre rodadas.
    return {
        "cid": f"Z{next(_PROXIMO_CID) % 100:02d}.{_sufixo()[:2].upper()}",
        "descricao": "Teste",
        **extra,
    }


NOVOS = {"unidades": _unidade, "servicos": _servico, "cids": _cid}


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
    alteracao = {"descricao": "Outra"} if rota != "unidades" else {"endereco": "Rua Sul, 1"}
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


# --- Duplicados --------------------------------------------------------------------------


@pytest.mark.parametrize("rota", ["unidades", "servicos"])
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


@pytest.mark.parametrize("rota", ["unidades", "servicos"])
def test_inexistente_devolve_404(admin: TestClient, rota: str) -> None:
    url = f"/{rota}/2000000000"
    assert admin.patch(url, json={"nome": "Outro"}).status_code == 404
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


@pytest.mark.parametrize("tabela", ["unidade_saude", "servico_saude", "cid"])
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
        # A sequência continua depois do código preservado: novas unidades não colidem.
        novo = conn.execute(
            """
            INSERT INTO app.unidade_saude (tipo_unidade, nome, endereco)
            VALUES ('Hospital', 'Nova', 'Rua A') RETURNING id_unidade
            """
        ).fetchone()
        assert novo == (43,)
        conn.rollback()
