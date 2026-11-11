"""Настройки приложения через pydantic-settings."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Базовые настройки HTTP-сервера и приложения."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "buh-ai-agent"
    app_env: str = "local"
    debug: bool = False
    skills_dir: Path = Path(".opencode/skills")

    # LLM
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_temperature: float = 0.2
    llm_timeout: float = 60.0


@lru_cache
def get_settings() -> Settings:
    """Возвращает кэшированный singleton настроек."""
    return Settings()
