import stat
from pathlib import Path

from app.core.crypto import carregar_keyring, decodificar_chave
from scripts.gerar_chaves import atualizar_env


def _env(caminho: Path) -> dict[str, str]:
    linhas = caminho.read_text().splitlines()
    return dict(linha.split("=", 1) for linha in linhas if "=" in linha)


def test_cria_chaves_validas_e_preserva_resto(tmp_path: Path) -> None:
    arquivo = tmp_path / ".env"
    arquivo.write_text("# comentário\nPOSTGRES_DB=cs\n")
    assert atualizar_env(arquivo, rotacionar=False) == [
        "KEK_KEYRING",
        "KEK_ATIVA",
        "HMAC_KEY",
        "LOG_CHECKPOINT_KEY",
    ]
    env = _env(arquivo)
    assert env["POSTGRES_DB"] == "cs"
    assert "# comentário" in arquivo.read_text()
    carregar_keyring(env["KEK_KEYRING"], int(env["KEK_ATIVA"]))
    decodificar_chave(env["HMAC_KEY"])
    assert decodificar_chave(env["LOG_CHECKPOINT_KEY"]) != decodificar_chave(env["HMAC_KEY"])
    assert stat.S_IMODE(arquivo.stat().st_mode) == 0o600


def test_idempotente(tmp_path: Path) -> None:
    arquivo = tmp_path / ".env"
    atualizar_env(arquivo, rotacionar=False)
    antes = arquivo.read_text()
    assert atualizar_env(arquivo, rotacionar=False) == []
    assert arquivo.read_text() == antes


def test_rotacao_adiciona_versao_e_mantem_antigas_e_hmac(tmp_path: Path) -> None:
    arquivo = tmp_path / ".env"
    atualizar_env(arquivo, rotacionar=False)
    antes = _env(arquivo)
    assert atualizar_env(arquivo, rotacionar=True) == ["KEK_KEYRING", "KEK_ATIVA"]
    depois = _env(arquivo)
    keyring = carregar_keyring(depois["KEK_KEYRING"], int(depois["KEK_ATIVA"]))
    assert keyring.ativa == 2
    assert keyring.chaves[1] == carregar_keyring(antes["KEK_KEYRING"], 1).chaves[1]
    assert depois["HMAC_KEY"] == antes["HMAC_KEY"]
    assert depois["LOG_CHECKPOINT_KEY"] == antes["LOG_CHECKPOINT_KEY"]
