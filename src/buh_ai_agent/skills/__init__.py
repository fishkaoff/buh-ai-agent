"""Инфраструктура Skills: модели, загрузчик и реестр."""

from buh_ai_agent.skills.loader import SkillLoader
from buh_ai_agent.skills.models import Skill, SkillMetadata
from buh_ai_agent.skills.registry import SkillRegistry

__all__ = ["Skill", "SkillLoader", "SkillMetadata", "SkillRegistry"]
