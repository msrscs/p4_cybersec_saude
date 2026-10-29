import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core import config
from app.core.config import Settings
from app.main import create_app


def test_senha_do_banco_obrigatoria(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_DB_PASSWORD", raising=False)
    with pytest.raises(ValidationError):
        Settings()


def test_senha_nao_aparece_em_repr_nem_na_url_renderizada() -> None:
    settings = Settings(app_db_password="senha-secreta", postgres_db="db")
    assert settings.app_db_password.get_secret_value() == "senha-secreta"
    assert "senha-secreta" not in repr(settings)
    assert "senha-secreta" not in str(settings.model_dump())
    assert "senha-secreta" not in str(settings.database_url)  # SQLAlchemy mascara com ***


def test_url_usa_role_da_aplicacao() -> None:
    settings = Settings(app_db_password="x", postgres_db="cs", db_host="db", db_port=5432)
    url = settings.database_url
    assert (url.username, url.host, url.port, url.database) == ("app_user", "db", 5432, "cs")


def test_docs_desabilitados_em_producao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "prod")
    config.get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
    finally:
        config.get_settings.cache_clear()


def test_chaves_carregadas_e_ocultas() -> None:
    settings = Settings()
    assert settings.keyring.ativa == 1
    assert len(settings.chave_hmac) == 32
    for segredo in (settings.kek_keyring.get_secret_value(), settings.hmac_key.get_secret_value()):
        assert segredo not in repr(settings)
        assert segredo not in str(settings.model_dump())
    assert "chaves" not in repr(settings.keyring)


@pytest.mark.parametrize(
    ("variavel", "valor"),
    [
        ("KEK_KEYRING", "1:curta"),
        ("KEK_KEYRING", "sem-versao"),
        ("KEK_ATIVA", "2"),
        ("HMAC_KEY", "YWJj"),
    ],
)
def test_configuracao_de_chave_invalida_falha_sem_vazar(
    monkeypatch: pytest.MonkeyPatch, variavel: str, valor: str
) -> None:
    import os

    segredos = [os.environ["KEK_KEYRING"].split(":", 1)[1], os.environ["HMAC_KEY"]]
    if variavel != "KEK_ATIVA":  # a versão ativa não é segredo
        segredos.append(valor)
    monkeypatch.setenv(variavel, valor)
    with pytest.raises(ValidationError) as exc:
        Settings()
    for segredo in segredos:
        assert segredo not in str(exc.value)
    assert "senha-ficticia-de-teste" not in str(exc.value)


def test_chave_de_checkpoint_opcional_e_validada(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    from app.core.crypto import gerar_chave_b64

    monkeypatch.delenv("LOG_CHECKPOINT_KEY", raising=False)
    assert Settings().chave_checkpoint is None

    chave = gerar_chave_b64()
    monkeypatch.setenv("LOG_CHECKPOINT_KEY", chave)
    settings = Settings()
    assert settings.chave_checkpoint is not None
    assert len(settings.chave_checkpoint) == 32
    assert chave not in repr(settings)

    monkeypatch.setenv("LOG_CHECKPOINT_KEY", os.environ["HMAC_KEY"])
    with pytest.raises(ValidationError, match="diferente de HMAC_KEY"):
        Settings()

    monkeypatch.setenv("LOG_CHECKPOINT_KEY", "YWJj")
    with pytest.raises(ValidationError) as exc:
        Settings()
    assert "YWJj" not in str(exc.value)
