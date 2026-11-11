"""Pydantic-модели Skills."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class SkillMetadata(BaseModel):
    """Метаданные Skill из frontmatter файла SKILL.md.

    Модель допускает дополнительные поля (extra="allow"): новые поля
    frontmatter сохраняются без изменения кода, что позволяет расширять
    метаданные в будущем.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    skill_dir: Path
    skill_md_path: Path


class Skill(BaseModel):
    """Полное содержимое Skill: метаданные и текст инструкций из SKILL.md."""

    model_config = ConfigDict(frozen=True)

    metadata: SkillMetadata
    instructions: str
