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
    assert "senha-secreta" not in repr(settings)
    assert "senha-secreta" not in str(settings.model_dump())
    assert "senha-secreta" not in str(settings.database_url)  # SQLAlchemy mascara com ***


def test_url_usa_role_da_aplicacao() -> None:
    url = Settings(app_db_password="x", postgres_db="cs", db_host="db", db_port=5432).database_url
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
