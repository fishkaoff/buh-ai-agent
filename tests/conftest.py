"""Общие фикстуры всех тестов."""

from pathlib import Path

import pytest

from buh_ai_agent.core.settings import get_settings


@pytest.fixture(autouse=True)
def isolated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Изолирует SQLite-хранилище тестов во временной директории.

    Приложения в тестах не пишут в рабочую базу data/agent.db; кэш
    настроек сбрасывается, чтобы путь из переменной окружения прочитался.
    """
    monkeypatch.setenv("STORAGE_SQLITE_PATH", str(tmp_path / "agent.db"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
