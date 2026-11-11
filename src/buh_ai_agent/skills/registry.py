"""Реестр Skills: хранение метаданных и доступ к полному содержимому."""

from buh_ai_agent.skills.loader import SkillLoader
from buh_ai_agent.skills.models import Skill, SkillMetadata


class SkillNotFoundError(KeyError):
    """Skill с запрошенным именем не зарегистрирован."""


class DuplicateSkillError(ValueError):
    """Попытка зарегистрировать Skill с уже занятым именем."""


class SkillRegistry:
    """Хранит метаданные обнаруженных Skills в памяти.

    Полное содержимое не хранится: инструкции загружаются лениво
    через SkillLoader по запросу.
    """

    def __init__(self, loader: SkillLoader) -> None:
        """Инициализирует реестр загрузчиком Skills.

        Args:
            loader: Загрузчик, через который выполняется обнаружение
                и ленивое чтение полного текста инструкций.
        """
        self._loader = loader
        self._skills: dict[str, SkillMetadata] = {}

    def register_discovered(self) -> list[SkillMetadata]:
        """Обнаруживает Skills через загрузчик и регистрирует их.

        Returns:
            Список всех зарегистрированных метаданных.

        Raises:
            DuplicateSkillError: Если у двух Skills совпало имя.
        """
        for metadata in self._loader.discover():
            self.register(metadata)
        return self.list_skills()

    def register(self, metadata: SkillMetadata) -> None:
        """Регистрирует метаданные Skill.

        Args:
            metadata: Метаданные Skill.

        Raises:
            DuplicateSkillError: Если Skill с таким именем уже зарегистрирован.
        """
        if metadata.name in self._skills:
            raise DuplicateSkillError(f"Skill с именем «{metadata.name}» уже зарегистрирован.")
        self._skills[metadata.name] = metadata

    def list_skills(self) -> list[SkillMetadata]:
        """Возвращает метаданные всех зарегистрированных Skills.

        Returns:
            Список метаданных, отсортированный по имени Skill.
        """
        return sorted(self._skills.values(), key=lambda skill: skill.name)

    def get_metadata(self, name: str) -> SkillMetadata:
        """Возвращает метаданные Skill по имени.

        Args:
            name: Имя Skill.

        Returns:
            Метаданные Skill.

        Raises:
            SkillNotFoundError: Если Skill не зарегистрирован.
        """
        try:
            return self._skills[name]
        except KeyError:
            raise SkillNotFoundError(f"Skill с именем «{name}» не зарегистрирован.") from None

    def load_skill(self, name: str) -> Skill:
        """Загружает полное содержимое Skill через загрузчик.

        Args:
            name: Имя Skill.

        Returns:
            Полное содержимое Skill с текстом инструкций.

        Raises:
            SkillNotFoundError: Если Skill не зарегистрирован.
        """
        return self._loader.load_skill(self.get_metadata(name))
