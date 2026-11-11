"""Юнит-тесты загрузчика Skills."""

import logging
from pathlib import Path

import pytest

from buh_ai_agent.skills.loader import SkillLoader
from buh_ai_agent.skills.models import SkillMetadata


def test_discover_finds_multiple_skills(tmp_path: Path, write_skill) -> None:
    """Обнаруживаются все дочерние директории с SKILL.md, файлы игнорируются."""
    write_skill(tmp_path, "skill-a", "Описание A")
    write_skill(tmp_path, "skill-b", "Описание B")
    (tmp_path / "not-a-dir.txt").write_text("файл, не директория", encoding="utf-8")

    discovered = SkillLoader(tmp_path).discover()

    assert [skill.name for skill in discovered] == ["skill-a", "skill-b"]


def test_discover_reads_frontmatter_and_paths(tmp_path: Path, write_skill) -> None:
    """Из frontmatter читаются name и description, пути указывают на Skill."""
    write_skill(tmp_path, "skill-a", "Описание A")

    (metadata,) = SkillLoader(tmp_path).discover()

    assert metadata.name == "skill-a"
    assert metadata.description == "Описание A"
    assert metadata.skill_dir == (tmp_path / "skill-a").resolve()
    assert metadata.skill_md_path == (tmp_path / "skill-a" / "SKILL.md").resolve()


def test_discover_keeps_extra_frontmatter_fields(tmp_path: Path, write_skill) -> None:
    """Дополнительные поля frontmatter сохраняются в метаданных."""
    write_skill(tmp_path, "skill-a", frontmatter="name: skill-a\ndescription: X\nversion: 2")

    (metadata,) = SkillLoader(tmp_path).discover()

    assert metadata.model_extra == {"version": 2}


def test_load_skill_returns_full_content(tmp_path: Path, write_skill) -> None:
    """Загрузка возвращает метаданные и текст инструкций без frontmatter."""
    write_skill(tmp_path, "skill-a", "Описание A", body="Шаг 1. Сделай что-то.")
    loader = SkillLoader(tmp_path)
    (metadata,) = loader.discover()

    skill = loader.load_skill(metadata)

    assert skill.metadata == metadata
    assert skill.instructions == "Шаг 1. Сделай что-то."


def test_discover_skips_dir_without_skill_md(tmp_path: Path, write_skill, caplog) -> None:
    """Директория без SKILL.md пропускается с предупреждением в логе."""
    (tmp_path / "empty").mkdir()
    write_skill(tmp_path, "skill-a", "Описание A")
    caplog.set_level(logging.WARNING)

    discovered = SkillLoader(tmp_path).discover()

    assert [skill.name for skill in discovered] == ["skill-a"]
    assert any("empty" in record.getMessage() for record in caplog.records)


def test_discover_skips_invalid_frontmatter(tmp_path: Path, write_skill) -> None:
    """Директория с невалидным YAML в frontmatter пропускается."""
    write_skill(tmp_path, "broken", frontmatter="name: [незакрытый список")
    write_skill(tmp_path, "skill-a", "Описание A")

    discovered = SkillLoader(tmp_path).discover()

    assert [skill.name for skill in discovered] == ["skill-a"]


def test_discover_skips_file_without_frontmatter(tmp_path: Path) -> None:
    """SKILL.md без frontmatter не считается Skill."""
    skill_dir = tmp_path / "plain"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "Просто текст без frontmatter.\n",
        encoding="utf-8",
    )

    assert SkillLoader(tmp_path).discover() == []


def test_discover_skips_missing_required_field(tmp_path: Path, write_skill) -> None:
    """Skills без непустых name или description пропускаются."""
    write_skill(tmp_path, "no-description", frontmatter="name: no-description")
    write_skill(tmp_path, "empty-name", frontmatter='name: ""\ndescription: X')
    write_skill(tmp_path, "numeric-name", frontmatter="name: 123\ndescription: X")
    write_skill(tmp_path, "skill-a", "Описание A")

    discovered = SkillLoader(tmp_path).discover()

    assert [skill.name for skill in discovered] == ["skill-a"]


def test_discover_missing_skills_dir(tmp_path: Path) -> None:
    """Отсутствующая директория Skills даёт понятную ошибку."""
    loader = SkillLoader(tmp_path / "missing")

    with pytest.raises(FileNotFoundError, match="не найдена"):
        loader.discover()


def test_load_skill_rejects_path_outside_skills_dir(tmp_path: Path) -> None:
    """Загрузка SKILL.md вне директории Skills запрещена."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text(
        "---\nname: evil\ndescription: X\n---\nТело\n",
        encoding="utf-8",
    )
    root = tmp_path / "skills"
    root.mkdir()
    metadata = SkillMetadata(
        name="evil",
        description="X",
        skill_dir=outside,
        skill_md_path=outside / "SKILL.md",
    )

    with pytest.raises(ValueError, match="вне директории"):
        SkillLoader(root).load_skill(metadata)


def test_load_skill_rejects_relative_traversal(tmp_path: Path, write_skill) -> None:
    """Обход директории Skills через «..» в пути запрещён."""
    write_skill(tmp_path, "skill-a")
    root = tmp_path / "skills"
    root.mkdir()
    metadata = SkillMetadata(
        name="skill-a",
        description="Описание",
        skill_dir=root / ".." / "skill-a",
        skill_md_path=root / ".." / "skill-a" / "SKILL.md",
    )

    with pytest.raises(ValueError, match="вне директории"):
        SkillLoader(root).load_skill(metadata)


def test_load_skill_missing_file(tmp_path: Path) -> None:
    """Загрузка по пути без файла даёт FileNotFoundError."""
    root = tmp_path / "skills"
    root.mkdir()
    metadata = SkillMetadata(
        name="x",
        description="X",
        skill_dir=root / "x",
        skill_md_path=root / "x" / "SKILL.md",
    )

    with pytest.raises(FileNotFoundError):
        SkillLoader(root).load_skill(metadata)
