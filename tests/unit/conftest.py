"""Общие фикстуры юнит-тестов."""

from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture()
def write_skill() -> Callable[..., Path]:
    """Фабрика тестовых Skill-директорий во временных директориях.

    Returns:
        Функцию, создающую директорию Skill с файлом SKILL.md и
        возвращающую путь к ней.
    """

    def factory(
        root: Path,
        name: str,
        description: str = "Тестовое описание",
        body: str = "Тестовые инструкции.",
        frontmatter: str | None = None,
    ) -> Path:
        """Создаёт директорию Skill с файлом SKILL.md.

        Args:
            root: Корневая директория Skills.
            name: Имя Skill (используется и как имя директории).
            description: Значение description для frontmatter.
            body: Текст инструкций после frontmatter.
            frontmatter: Готовый текст frontmatter; если не задан,
                собирается из name и description.
        """
        skill_dir = root / name
        skill_dir.mkdir(parents=True)
        if frontmatter is None:
            frontmatter = f"name: {name}\ndescription: {description}"
        (skill_dir / "SKILL.md").write_text(
            f"---\n{frontmatter}\n---\n\n{body}\n",
            encoding="utf-8",
        )
        return skill_dir

    return factory
