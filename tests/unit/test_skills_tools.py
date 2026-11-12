"""Юнит-тесты инструмента load_skill: загрузка один раз на диалог."""

import json
from pathlib import Path

import pytest

from buh_ai_agent.agent.context import DialogContext, bind_dialog_context
from buh_ai_agent.skills.loader import SkillLoader
from buh_ai_agent.skills.registry import SkillRegistry
from buh_ai_agent.storage.sqlite import SQLiteStore
from buh_ai_agent.tools.skills import make_skill_tools


@pytest.fixture()
def registry(tmp_path: Path) -> SkillRegistry:
    """Реестр с одним тестовым навыком."""
    skill_dir = tmp_path / "onec-test"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: onec-test\ndescription: Тестовый навык\n---\n\nПолные инструкции навыка.\n",
        encoding="utf-8",
    )
    registry = SkillRegistry(SkillLoader(tmp_path))
    registry.register_discovered()
    return registry


@pytest.fixture()
def store() -> SQLiteStore:
    """In-memory SQLite."""
    return SQLiteStore(":memory:")


@pytest.fixture()
def tools(registry: SkillRegistry, store: SQLiteStore) -> list:
    """Инструменты навыков."""
    return make_skill_tools(registry, store)


async def test_first_load_returns_full_instructions(tools: list, store: SQLiteStore) -> None:
    """Первый вызов возвращает полный текст и запоминает навык."""
    with bind_dialog_context(DialogContext(chat_id="chat-1")):
        result = json.loads(await tools[0].ainvoke({"name": "onec-test"}))
    assert result["ok"] is True
    assert result["data"]["instructions"] == "Полные инструкции навыка."
    assert "already_loaded" not in result["data"]
    assert store.get_loaded_skills("chat-1") == ["onec-test"]


async def test_second_load_returns_stub(tools: list) -> None:
    """Повторный вызов возвращает заглушку вместо полной инструкции."""
    with bind_dialog_context(DialogContext(chat_id="chat-1")):
        first = json.loads(await tools[0].ainvoke({"name": "onec-test"}))
        second = json.loads(await tools[0].ainvoke({"name": "onec-test"}))
    assert first["ok"] is True
    assert second["ok"] is True
    assert second["data"]["already_loaded"] is True
    assert "instructions" not in second["data"]
    assert len(second["data"]["note"]) < 400


async def test_force_reloads_full_instructions(tools: list) -> None:
    """force=True перезагружает полную инструкцию."""
    with bind_dialog_context(DialogContext(chat_id="chat-1")):
        await tools[0].ainvoke({"name": "onec-test"})
        forced = json.loads(await tools[0].ainvoke({"name": "onec-test", "force": True}))
    assert forced["ok"] is True
    assert forced["data"]["instructions"] == "Полные инструкции навыка."


async def test_loaded_skills_are_per_chat(tools: list, store: SQLiteStore) -> None:
    """Загрузка навыка в одном диалоге не влияет на другой."""
    with bind_dialog_context(DialogContext(chat_id="chat-1")):
        await tools[0].ainvoke({"name": "onec-test"})
    assert store.get_loaded_skills("chat-2") == []


async def test_load_skill_without_context_fails(tools: list) -> None:
    """Без диалогового контекста инструмент возвращает ошибку."""
    result = json.loads(await tools[0].ainvoke({"name": "onec-test"}))
    assert result["ok"] is False
    assert "контекст" in result["error"]
