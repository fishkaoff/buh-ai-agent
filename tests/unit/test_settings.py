"""Юнит-тесты настроек приложения."""

from buh_ai_agent.core.settings import get_settings


def test_settings_defaults() -> None:
    """Настройки по умолчанию корректны."""
    settings = get_settings()
    assert settings.app_name == "buh-ai-agent"
    assert settings.app_env == "local"
    assert settings.debug is False
