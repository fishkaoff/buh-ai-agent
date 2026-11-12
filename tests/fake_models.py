"""Фейковые LLM для тестов: поддержка bind_tools для ReAct-графа."""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool


class FakeToolChatModel(FakeMessagesListChatModel):
    """FakeMessagesListChatModel с поддержкой bind_tools.

    bind_tools возвращает self: ответы из responses проигрываются по
    порядку (циклично), независимо от привязанных инструментов. Позволяет
    тестировать ReAct-граф с tool-calling без реального LLM.
    """

    def bind_tools(
        self,
        tools: Sequence[BaseTool] | None,
        **kwargs: object,
    ) -> FakeToolChatModel:
        """Возвращает себя: инструменты привязывать не нужно."""
        return self


def fake_tool_llm(*responses: BaseMessage) -> FakeToolChatModel:
    """Создаёт фейковую модель с заготовленными ответами по порядку."""
    return FakeToolChatModel(responses=list(responses))
