"""Настройки приложения через pydantic-settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Базовые настройки HTTP-сервера приложения."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "buh-ai-agent"
    app_env: str = "local"
    debug: bool = False


@lru_cache
def get_settings() -> Settings:
    """Возвращает кэшированный singleton настроек."""
    return Settings()
