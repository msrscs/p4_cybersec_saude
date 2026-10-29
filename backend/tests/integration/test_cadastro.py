"""RF-01 / THREAT_MODEL I1: cadastro grava dados pessoais só cifrados."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.crypto import DekCifrada, abrir_dek, decifrar_campo
from app.models import Log, Usuario
from app.services import usuario as usuario_service
from app.services.auditoria import ContextoRequisicao
from app.services.usuario import ErroCadastro, NovoUsuario

from .conftest import gerar_cpf

SENHA = "Saúde#Recife2026"


def _novo(cpf: str | None = None, email: str | None = None) -> NovoUsuario:
    cpf = cpf or gerar_cpf()
    return NovoUsuario(
        cpf=cpf, nome="Maria da Conceição", email=email or f"u{cpf}@recife.pe.gov.br", senha=SENHA
    )


def _cadastrar(fabrica: sessionmaker[Session], settings: Settings, dados: NovoUsuario) -> bytes:
    with fabrica() as db, db.begin():
        return usuario_service.cadastrar(db, settings, dados, ContextoRequisicao())


def test_dados_pessoais_gravados_so_cifrados(
    fabrica_sessao: sessionmaker[Session], settings_integracao: Settings
) -> None:
    dados = _novo()
    cpf_hash = _cadastrar(fabrica_sessao, settings_integracao, dados)

    with fabrica_sessao() as db:
        usuario = db.get_one(Usuario, cpf_hash)
        linha_bruta = b"".join(
            v if isinstance(v, bytes) else str(v).encode()
            for v in (
                usuario.cpf_hash,
                usuario.email_hash,
                usuario.cpf_cripto,
                usuario.nome_cripto,
                usuario.email_cripto,
                usuario.dek_cripto,
                usuario.senha_hash,
            )
        )
    for claro in (dados.cpf, "Maria", dados.email, SENHA):
        assert claro.encode() not in linha_bruta
    assert usuario.senha_hash.startswith("$2b$04$")

    dek = abrir_dek(settings_integracao.keyring, DekCifrada(usuario.dek_cripto, usuario.kek_versao))

    def decifrar(blob: bytes, coluna: str) -> str:
        return decifrar_campo(dek, blob, tabela="usuario", coluna=coluna, id_registro=cpf_hash)

    assert decifrar(usuario.cpf_cripto, "cpf_cripto") == dados.cpf
    assert decifrar(usuario.nome_cripto, "nome_cripto") == dados.nome
    assert decifrar(usuario.email_cripto, "email_cripto") == dados.email


@pytest.mark.parametrize("duplicar", ["cpf", "email"])
def test_cpf_ou_email_duplicado_recusado_com_erro_generico(
    fabrica_sessao: sessionmaker[Session], settings_integracao: Settings, duplicar: str
) -> None:
    original = _novo()
    _cadastrar(fabrica_sessao, settings_integracao, original)
    copia = (
        _novo(cpf=original.cpf)
        if duplicar == "cpf"
        else _novo(email=original.email.upper())  # e-mail normalizado antes do hash
    )
    with pytest.raises(ErroCadastro) as exc:
        _cadastrar(fabrica_sessao, settings_integracao, copia)
    assert str(exc.value) == "Não foi possível cadastrar o usuário."


def test_senha_fora_da_politica_recusada(
    fabrica_sessao: sessionmaker[Session], settings_integracao: Settings
) -> None:
    fraca = NovoUsuario(cpf=gerar_cpf(), nome="Fulano", email="f@x.gov.br", senha="fraca")
    with pytest.raises(ValueError, match="senha deve"):
        _cadastrar(fabrica_sessao, settings_integracao, fraca)


def test_cadastro_auditado_sem_dado_pessoal(
    fabrica_sessao: sessionmaker[Session], settings_integracao: Settings
) -> None:
    dados = _novo()
    cpf_hash = _cadastrar(fabrica_sessao, settings_integracao, dados)
    with fabrica_sessao() as db:
        eventos = db.scalars(select(Log).where(Log.cpf_usuario_hash == cpf_hash)).all()
    assert [e.acao for e in eventos] == ["user_created"]
    assert dados.cpf not in str(eventos[0].resumo_acessado)


# --- Script de cadastro pelo terminal ----------------------------------------------------


def _rodar_script(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, argv: list[str], senhas: list[str]
) -> None:
    from scripts import criar_usuario

    respostas = iter(senhas)
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(respostas))
    monkeypatch.setattr(criar_usuario, "get_settings", lambda: settings)
    criar_usuario.main(argv)


def test_script_cadastra_usuario(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings_integracao: Settings,
    fabrica_sessao: sessionmaker[Session],
) -> None:
    cpf = gerar_cpf()
    argv = ["--cpf", cpf, "--nome", "Joana", "--email", f"j{cpf}@recife.pe.gov.br"]
    _rodar_script(monkeypatch, settings_integracao, argv, [SENHA, SENHA])
    saida = capsys.readouterr()
    assert "Usuário cadastrado." in saida.out
    assert SENHA not in saida.out + saida.err

    with pytest.raises(SystemExit, match="Não foi possível"):
        _rodar_script(monkeypatch, settings_integracao, argv, [SENHA, SENHA])


def test_script_recusa_confirmacao_diferente(
    monkeypatch: pytest.MonkeyPatch, settings_integracao: Settings
) -> None:
    argv = ["--cpf", gerar_cpf(), "--nome", "Joana", "--email", "j@x.gov.br"]
    with pytest.raises(SystemExit, match="não conferem"):
        _rodar_script(monkeypatch, settings_integracao, argv, [SENHA, SENHA + "x"])


@pytest.mark.parametrize(
    ("cpf", "esperado"), [("111.111.111-11", "CPF inválido"), (None, "A senha deve")]
)
def test_script_mostra_erros_sem_ecoar_entrada(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings_integracao: Settings,
    cpf: str | None,
    esperado: str,
) -> None:
    argv = ["--cpf", cpf or gerar_cpf(), "--nome", "Joana", "--email", "j@x.gov.br"]
    with pytest.raises(SystemExit):
        _rodar_script(monkeypatch, settings_integracao, argv, ["fraca123", "fraca123"])
    erro = capsys.readouterr().err
    assert esperado in erro
    assert "fraca123" not in erro


def test_corrida_de_cadastro_duplicado_vira_erro_generico(
    monkeypatch: pytest.MonkeyPatch,
    fabrica_sessao: sessionmaker[Session],
    settings_integracao: Settings,
) -> None:
    # Simula dois cadastros simultâneos: a checagem prévia passa, a UNIQUE do banco barra.
    original = _novo()
    _cadastrar(fabrica_sessao, settings_integracao, original)
    monkeypatch.setattr("app.repositories.usuario.existe", lambda *_a, **_k: False)
    with pytest.raises(ErroCadastro):
        _cadastrar(fabrica_sessao, settings_integracao, _novo(cpf=original.cpf))
