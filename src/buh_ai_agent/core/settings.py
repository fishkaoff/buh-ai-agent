"""Настройки приложения через pydantic-settings."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
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
    # Skills приложения: плейбуки для агента (инструкции под Tools приложения).
    # Скиллы для внешних агентов (OpenCode и т.п.) живут отдельно в .opencode/skills/.
    skills_dir: Path = Path("skills")

    # LLM
    llm_base_url: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = ""
    llm_temperature: float = 0.2
    llm_timeout: float = 60.0

    # 1С OData: подключение приложения к базе 1С (только env, без файлов).
    # Секреты хранятся в .env (gitignored). Конфиг агентского стека
    # (скиллы, config/onec-config.json) приложением не используется.
    onec_base_url: str = ""
    onec_username: str = ""
    onec_password: SecretStr = SecretStr("")
    onec_database: str = ""
    # Несколько баз 1С: JSON-массив в одну строку, элемент — объект базы:
    # [{"name": "osnovnaya", "label": "Основная база (ИП Агентов)",
    #   "base_url": "http://…/odata/standard.odata/", "username": "…",
    #   "password": "…", "organization_name": "…", "organization_inn": "…"}].
    # Если задан — используется он, а одиночные ONEC_BASE_URL/USERNAME/
    # PASSWORD/DATABASE игнорируются. organization_* базы не обязательны:
    # пустые значения берутся из общих ONEC_ORGANIZATION_*.
    onec_databases: str = ""
    # HTTP-сервис печати (расширение 1С): корневой URL сервиса, например
    # http://192.168.3.2/InfoBase2/hs/print. Используется для скачивания
    # официальных печатных форм (PDF). Пусто — сервис не используется
    # (fallback для всех баз; у базы можно задать свой print_service_url).
    onec_print_service_url: str = ""
    onec_timeout: float = 30.0
    onec_max_retries: int = 1

    # 1С: дефолты документов (когда пользователь не указал свои значения).
    onec_organization_name: str = ""
    onec_organization_inn: str = ""
    onec_currency_code: str = "643"
    onec_vat_rate: str = "НДС20"
    onec_sum_includes_vat: bool = True
    onec_unit_of_measure: str = "шт"

    # 1С: правила безопасности записи (настройки-напоминания для агента;
    # финальное решение о проведении всегда за человеком).
    onec_allow_write: bool = True
    onec_allow_post: bool = False
    onec_allow_unpost: bool = False
    onec_allow_mark_for_deletion: bool = False

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
