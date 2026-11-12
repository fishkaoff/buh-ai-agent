"""Юнит-тесты системного промпта агента (Skills, базы 1С)."""

from buh_ai_agent.agent.prompt import build_system_prompt


class _EmptyRegistry:
    """Заглушка реестра без Skills (совместима с SkillRegistry)."""

    @staticmethod
    def list_skills() -> list:
        """Список Skills пуст."""
        return []


def test_prompt_without_databases_block() -> None:
    """Без реестра баз блок о базах не добавляется."""
    prompt = build_system_prompt(_EmptyRegistry())  # type: ignore[arg-type]
    assert "база 1С" not in prompt
    assert "Доступные Skills" in prompt


def test_prompt_single_database() -> None:
    """Одна база: указана явно, аргумент database объявлен необязательным."""
    prompt = build_system_prompt(
        _EmptyRegistry(),  # type: ignore[arg-type]
        databases=[{"name": "ai_agent", "label": "Тестовая база"}],
    )
    assert "База 1С: ai_agent — Тестовая база" in prompt
    assert "указывать не нужно" in prompt


def test_prompt_multiple_databases_require_clarification() -> None:
    """Несколько баз: список и правило уточнять базу у пользователя."""
    prompt = build_system_prompt(
        _EmptyRegistry(),  # type: ignore[arg-type]
        databases=[
            {"name": "osnovnaya", "label": "Основная база"},
            {"name": "filial", "label": "Филиал"},
        ],
    )
    assert "- osnovnaya — Основная база" in prompt
    assert "- filial — Филиал" in prompt
    assert "уточняющий вопрос" in prompt
    assert "database" in prompt


def test_prompt_databases_without_label() -> None:
    """База без label выводится только именем (без тире)."""
    prompt = build_system_prompt(
        _EmptyRegistry(),  # type: ignore[arg-type]
        databases=[{"name": "osnovnaya", "label": ""}],
    )
    assert "База 1С: osnovnaya (единственная" in prompt
    assert "osnovnaya —" not in prompt
