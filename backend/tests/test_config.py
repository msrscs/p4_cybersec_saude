import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app


def test_database_url_obrigatoria(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings()


def test_database_url_nao_aparece_em_repr() -> None:
    settings = Settings(database_url="postgresql://u:senha-secreta@h/db")
    assert "senha-secreta" not in repr(settings)
    assert "senha-secreta" not in str(settings.model_dump())


def test_docs_desabilitados_em_producao(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config

    monkeypatch.setenv("ENVIRONMENT", "prod")
    config.get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
    finally:
        config.get_settings.cache_clear()
