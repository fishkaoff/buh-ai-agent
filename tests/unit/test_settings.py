"""Юнит-тесты настроек приложения."""

from pathlib import Path

import pytest

from buh_ai_agent.core.settings import Settings, get_settings


def test_settings_defaults() -> None:
    """Настройки по умолчанию корректны."""
    settings = get_settings()
    assert settings.app_name == "buh-ai-agent"
    assert settings.app_env == "local"
    assert settings.debug is False

    assert settings.skills_dir == Path("skills")

    assert settings.llm_temperature == 0.2
    assert settings.llm_timeout == 60.0


def test_settings_skills_dir_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """SKILLS_DIR читается из переменной окружения."""
    monkeypatch.setenv("SKILLS_DIR", "custom/skills")
    settings = Settings(_env_file=None)
    assert settings.skills_dir == Path("custom/skills")
