"""Configuração da aplicação, lida exclusivamente de variáveis de ambiente."""

from functools import cached_property, lru_cache
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

from app.core.crypto import Keyring, carregar_keyring, decodificar_chave
from app.core.db_url import APP_DB_ROLE, build_database_url
from app.core.senha import ROUNDS_MINIMO_PRODUCAO


class Settings(BaseSettings):
    # hide_input_in_errors: erros de validação não podem ecoar segredos (input_value).
    model_config = SettingsConfigDict(
        env_file=None, extra="ignore", frozen=True, hide_input_in_errors=True
    )

    environment: Literal["dev", "test", "prod"] = "dev"
    postgres_db: str
    app_db_password: SecretStr
    db_host: str = "localhost"
    db_port: int = 5433

    # Chaves de criptografia (ADR-0004). Nunca ficam no banco.
    kek_keyring: SecretStr
    kek_ativa: int
    hmac_key: SecretStr

    # Custo do bcrypt (ADR-0003). Abaixo de 12 só é aceito em ENVIRONMENT=test.
    bcrypt_rounds: int = 12

    @model_validator(mode="after")
    def _validar_chaves(self) -> Self:
        # Falha na inicialização se alguma chave for inválida; mensagens sem material de chave.
        _ = self.keyring
        _ = self.chave_hmac
        return self

    @model_validator(mode="after")
    def _validar_bcrypt(self) -> Self:
        minimo = 4 if self.environment == "test" else ROUNDS_MINIMO_PRODUCAO
        if not minimo <= self.bcrypt_rounds <= 16:
            raise ValueError(f"BCRYPT_ROUNDS deve estar entre {minimo} e 16.")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "prod"

    @property
    def database_url(self) -> URL:
        return build_database_url(
            user=APP_DB_ROLE,
            password=self.app_db_password.get_secret_value(),
            database=self.postgres_db,
            host=self.db_host,
            port=self.db_port,
        )

    @cached_property
    def keyring(self) -> Keyring:
        return carregar_keyring(self.kek_keyring.get_secret_value(), self.kek_ativa)

    @cached_property
    def chave_hmac(self) -> bytes:
        return decodificar_chave(self.hmac_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
