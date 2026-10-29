from collections.abc import Iterator

import pytest

from app.core import config


@pytest.fixture(autouse=True)
def _env_ficticio(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # Valores fictícios: os testes unitários não acessam banco.
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("POSTGRES_DB", "test")
    monkeypatch.setenv("APP_DB_PASSWORD", "senha-ficticia-de-teste")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()
