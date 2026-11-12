"""Настройки приложения через pydantic-settings."""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Базовые настройки HTTP-сервера, приложения и интеграций.

    Секреты (ключи, пароли, токены) хранятся как SecretStr, чтобы случайно
    не попасть в логи и repr.
    """

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
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = ""
    llm_temperature: float = 0.2
    llm_timeout: float = 60.0

    # 1С OData: путь к общему файлу конфигурации и переменные-переопределения
    # (те же имена env, что использует config/onec/odata-client.js).
    onec_config_path: Path = Field(
        default=Path("config/onec-config.json"),
        validation_alias=AliasChoices("ONEC_CONFIG", "ONEC_CONFIG_PATH"),
    )
    onec_database: str = ""
    odata_base_url: str = ""
    odata_username: str = ""
    odata_password: SecretStr = SecretStr("")
    onec_timeout: float = 30.0
    onec_max_retries: int = 1

    # Агент
    agent_max_iterations: int = 24
    # Лимит истории диалога: сколько последних сообщений (включая
    # результаты Tools) передаётся LLM в контексте.
    agent_history_messages: int = 10

    # SQLite-хранилище (история диалогов, операции). Данные переживают
    # перезапуск приложения.
    storage_sqlite_path: Path = Path("data/agent.db")

    # HTTP
    max_body_bytes: int = 1_048_576

    # Telegram: токен бота; без токена интеграция не стартует.
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_poll_timeout: float = 30.0

    # ЭДО: провайдер («fake» — тестовый адаптер; пусто — выгрузка отключена).
    edo_provider: str = ""


@lru_cache
def get_settings() -> Settings:
    """Возвращает кэшированный singleton настроек."""
    return Settings()
