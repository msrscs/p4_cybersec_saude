from collections.abc import Iterator

import pytest

from app.core import config
from app.core.crypto import gerar_chave_b64

# Chaves aleatórias por execução; nunca valores fixos.
KEK_TESTE = gerar_chave_b64()
HMAC_TESTE = gerar_chave_b64()


@pytest.fixture(autouse=True)
def _env_ficticio(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # Valores fictícios: os testes unitários não acessam banco.
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("POSTGRES_DB", "test")
    monkeypatch.setenv("APP_DB_PASSWORD", "senha-ficticia-de-teste")
    monkeypatch.setenv("KEK_KEYRING", f"1:{KEK_TESTE}")
    monkeypatch.setenv("KEK_ATIVA", "1")
    monkeypatch.setenv("HMAC_KEY", HMAC_TESTE)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()
