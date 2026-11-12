"""Инструменты агента: 1С-операции и Skills."""

from buh_ai_agent.tools.base import tool_error, tool_success
from buh_ai_agent.tools.onec import make_onec_tools
from buh_ai_agent.tools.skills import make_skill_tools

__all__ = ["make_onec_tools", "make_skill_tools", "tool_error", "tool_success"]
