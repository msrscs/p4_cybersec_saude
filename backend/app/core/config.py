"""Configuração da aplicação, lida exclusivamente de variáveis de ambiente."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

from app.core.db_url import APP_DB_ROLE, build_database_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", frozen=True)

    environment: Literal["dev", "test", "prod"] = "dev"
    postgres_db: str
    app_db_password: SecretStr
    db_host: str = "localhost"
    db_port: int = 5433

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
