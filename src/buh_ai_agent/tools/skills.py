"""Инструменты Skills: загрузка полных инструкций по имени.

LLM видит только список Skills (name + description) в системном промпте.
Полный текст SKILL.md загружается лениво — только когда агент вызывает
инструмент `load_skill`.

Навык загружается в диалоге один раз: повторные вызовы возвращают короткую
заглушку (вместо полной инструкции), чтобы не расходовать токены. Полный
текст возвращается только при `force=true` — когда агенту действительно
нужны детали, выпавшие из контекста.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from buh_ai_agent.agent.context import MissingDialogContextError, get_dialog_context
from buh_ai_agent.skills.registry import SkillRegistry
from buh_ai_agent.storage.sqlite import SQLiteStore
from buh_ai_agent.tools.base import tool_error, tool_success


def make_skill_tools(registry: SkillRegistry, store: SQLiteStore) -> list[BaseTool]:
    """Создаёт инструменты для работы со Skills.

    Args:
        registry: Реестр Skills (метаданные + ленивая загрузка инструкций).
        store: SQLite-хранилище (факт загрузки навыка на диалог).

    Returns:
        Список LangChain-инструментов.
    """

    @tool
    async def load_skill(name: str, force: bool = False) -> str:
        """Загружает полную инструкцию Skill по имени (один раз на диалог).

        Аргументы:
            name: Имя Skill из списка доступных (например «onec-counterparties»).
            force: True — перезагрузить полную инструкцию, даже если навык
                уже загружен в этом диалоге (только если деталей действительно
                нет в контексте).

        Возвращает полный текст инструкций Skill (SKILL.md) при первой
        загрузке в диалоге. Повторные вызовы возвращают короткое
        подтверждение — не тратьте ходы на перезагрузку: рабочие Tools
        применяют правила навыков автоматически (валидация сумм, НДС,
        антидубликаты).
        """
        try:
            context = get_dialog_context()
        except MissingDialogContextError as error:
            return tool_error(f"load_skill: {error}")
        try:
            if not force and name in store.get_loaded_skills(context.chat_id):
                return tool_success(
                    {
                        "name": name,
                        "already_loaded": True,
                        "note": (
                            f"Навык {name} уже загружен в этом диалоге. Не перезагружайте: "
                            "выполняйте сценарий; обязательные правила (суммы, НДС, "
                            "антидубликаты) проверяют сами Tools. Полная инструкция — "
                            "только через force=true."
                        ),
                    }
                )
            skill = registry.load_skill(name)
            store.mark_skill_loaded(context.chat_id, name)
            return tool_success({"name": skill.metadata.name, "instructions": skill.instructions})
        except Exception as error:
            return tool_error(f"load_skill: {error}")

    return [load_skill]
