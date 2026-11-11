"""Юнит-тесты реестра Skills."""

from pathlib import Path

import pytest

from buh_ai_agent.skills.loader import SkillLoader
from buh_ai_agent.skills.registry import (
    DuplicateSkillError,
    SkillNotFoundError,
    SkillRegistry,
)


def test_register_discovered_lists_all_skills(tmp_path: Path, write_skill) -> None:
    """Реестр регистрирует обнаруженные Skills и перечисляет их по имени."""
    write_skill(tmp_path, "skill-b", "Описание B")
    write_skill(tmp_path, "skill-a", "Описание A")
    registry = SkillRegistry(SkillLoader(tmp_path))

    registered = registry.register_discovered()

    assert [skill.name for skill in registered] == ["skill-a", "skill-b"]


def test_get_metadata_by_name(tmp_path: Path, write_skill) -> None:
    """Реестр возвращает метаданные Skill по имени."""
    write_skill(tmp_path, "skill-a", "Описание A")
    registry = SkillRegistry(SkillLoader(tmp_path))
    registry.register_discovered()

    metadata = registry.get_metadata("skill-a")

    assert metadata.name == "skill-a"
    assert metadata.description == "Описание A"


def test_get_metadata_unknown_name(tmp_path: Path) -> None:
    """Поиск незарегистрированного имени даёт понятную ошибку."""
    registry = SkillRegistry(SkillLoader(tmp_path))

    with pytest.raises(SkillNotFoundError, match="не зарегистрирован"):
        registry.get_metadata("missing")


def test_register_duplicate_raises(tmp_path: Path, write_skill) -> None:
    """Повторная регистрация Skill с тем же именем запрещена."""
    write_skill(tmp_path, "skill-a", "Описание A")
    registry = SkillRegistry(SkillLoader(tmp_path))
    (metadata,) = registry.register_discovered()

    with pytest.raises(DuplicateSkillError, match="уже зарегистрирован"):
        registry.register(metadata)


def test_register_discovered_duplicate_names_raises(tmp_path: Path, write_skill) -> None:
    """Две директории с одинаковым именем в frontmatter не допускаются."""
    write_skill(tmp_path, "dir-one", frontmatter="name: dup\ndescription: A")
    write_skill(tmp_path, "dir-two", frontmatter="name: dup\ndescription: B")
    registry = SkillRegistry(SkillLoader(tmp_path))

    with pytest.raises(DuplicateSkillError, match="dup"):
        registry.register_discovered()


def test_load_skill_via_registry(tmp_path: Path, write_skill) -> None:
    """Реестр загружает полный текст инструкций через загрузчик."""
    write_skill(tmp_path, "skill-a", "Описание A", body="Шаг 1. Проверь ИНН.")
    registry = SkillRegistry(SkillLoader(tmp_path))
    registry.register_discovered()

    skill = registry.load_skill("skill-a")

    assert skill.metadata.name == "skill-a"
    assert skill.instructions == "Шаг 1. Проверь ИНН."


def test_registry_starts_empty(tmp_path: Path) -> None:
    """Пустой реестр не содержит Skills."""
    assert SkillRegistry(SkillLoader(tmp_path)).list_skills() == []
