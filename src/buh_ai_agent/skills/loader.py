"""Загрузчик Skills: обнаружение директорий и чтение SKILL.md."""

import logging
from pathlib import Path
from typing import Any

import yaml

from buh_ai_agent.skills.models import Skill, SkillMetadata

logger = logging.getLogger(__name__)

SKILL_FILE_NAME = "SKILL.md"
_FRONTMATTER_DELIMITER = "---"


class SkillFormatError(ValueError):
    """Некорректный формат SKILL.md: нет frontmatter, YAML не разбирается и т.п."""


class SkillLoader:
    """Обнаруживает Skills в директории и читает файлы SKILL.md.

    Обнаружение читает только frontmatter; полный текст инструкций
    загружается по запросу через load_skill. Файлы из scripts/ не
    исполняются, содержимое references/ не читается автоматически.
    """

    def __init__(self, skills_dir: Path | str) -> None:
        """Инициализирует загрузчик директорией Skills.

        Args:
            skills_dir: Путь к директории Skills (относительный или абсолютный).
        """
        self._root = Path(skills_dir).resolve()

    def discover(self) -> list[SkillMetadata]:
        """Находит Skills в дочерних директориях и возвращает их метаданные.

        Директории без SKILL.md или с некорректным frontmatter пропускаются
        с записью предупреждения в лог, не прерывая обнаружение остальных.

        Returns:
            Список метаданных, отсортированный по имени Skill.

        Raises:
            FileNotFoundError: Если директория Skills не существует.
        """
        if not self._root.is_dir():
            raise FileNotFoundError(f"Директория Skills не найдена: {self._root}")

        discovered: list[SkillMetadata] = []
        for entry in sorted(self._root.iterdir(), key=lambda path: path.name):
            if not entry.is_dir():
                continue
            try:
                discovered.append(self._read_metadata(entry))
            except (OSError, ValueError) as error:
                logger.warning("Skill пропущен (%s): %s", entry.name, error)
        return discovered

    def load_skill(self, metadata: SkillMetadata) -> Skill:
        """Загружает полный текст инструкций Skill по его метаданным.

        Args:
            metadata: Метаданные, полученные при обнаружении.

        Returns:
            Полное содержимое Skill.

        Raises:
            ValueError: Если SKILL.md лежит вне директории Skills.
            FileNotFoundError: Если SKILL.md не найден по пути из метаданных.
            SkillFormatError: Если frontmatter в файле некорректен.
        """
        skill_md_path = metadata.skill_md_path.resolve()
        if not skill_md_path.is_relative_to(self._root):
            raise ValueError(
                f"SKILL.md {skill_md_path} находится вне директории Skills {self._root}"
            )
        if not skill_md_path.is_file():
            raise FileNotFoundError(f"SKILL.md не найден: {skill_md_path}")
        _frontmatter, instructions = self._parse(skill_md_path.read_text(encoding="utf-8"))
        return Skill(metadata=metadata, instructions=instructions)

    def _read_metadata(self, skill_dir: Path) -> SkillMetadata:
        """Читает frontmatter SKILL.md одной директории и строит метаданные.

        Args:
            skill_dir: Директория потенциального Skill.

        Returns:
            Метаданные Skill.

        Raises:
            SkillFormatError: Если SKILL.md отсутствует или frontmatter
                некорректен (нет обязательных полей name и description).
            OSError: Если файл не удалось прочитать.
        """
        skill_md_path = skill_dir / SKILL_FILE_NAME
        if not skill_md_path.is_file():
            raise SkillFormatError(f"{SKILL_FILE_NAME} не найден в {skill_dir.name}")
        frontmatter, _instructions = self._parse(skill_md_path.read_text(encoding="utf-8"))
        name = frontmatter.get("name")
        description = frontmatter.get("description")
        if not isinstance(name, str) or not name.strip():
            raise SkillFormatError("в frontmatter отсутствует непустое поле name")
        if not isinstance(description, str) or not description.strip():
            raise SkillFormatError("в frontmatter отсутствует непустое поле description")
        return SkillMetadata(
            **{
                **frontmatter,
                "skill_dir": skill_dir.resolve(),
                "skill_md_path": skill_md_path.resolve(),
            }
        )

    def _parse(self, text: str) -> tuple[dict[str, Any], str]:
        """Разбирает SKILL.md на YAML frontmatter и тело инструкций.

        Args:
            text: Полный текст файла SKILL.md.

        Returns:
            Кортеж: словарь frontmatter и текст инструкций без frontmatter.

        Raises:
            SkillFormatError: Если frontmatter отсутствует, не закрыт
                разделителем, содержит невалидный YAML или не является
                словарём.
        """
        lines = text.splitlines()
        if not lines or lines[0].strip() != _FRONTMATTER_DELIMITER:
            raise SkillFormatError("файл не начинается с frontmatter (---)")
        closing = None
        for index in range(1, len(lines)):
            if lines[index].strip() == _FRONTMATTER_DELIMITER:
                closing = index
                break
        if closing is None:
            raise SkillFormatError("frontmatter не закрыт разделителем (---)")
        try:
            data = yaml.safe_load("\n".join(lines[1:closing]))
        except yaml.YAMLError as error:
            raise SkillFormatError(f"невалидный YAML frontmatter: {error}") from error
        if not isinstance(data, dict):
            raise SkillFormatError("frontmatter должен быть YAML-словарём")
        return data, "\n".join(lines[closing + 1 :]).strip()
