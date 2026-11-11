"""Юнит-тесты сервиса агента."""

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from buh_ai_agent.agent.graph import build_chat_graph
from buh_ai_agent.agent.service import AgentService


async def test_run_returns_llm_response() -> None:
    """Асинхронный вызов графа возвращает текст ответа модели."""
    graph = build_chat_graph(FakeListChatModel(responses=["Ответ модели"]))
    service = AgentService(graph)
    reply = await service.run("Привет, что ты умеешь?")
    assert reply == "Ответ модели"


async def test_run_rejects_empty_message() -> None:
    """Пустое сообщение отклоняется с понятной ошибкой."""
    graph = build_chat_graph(FakeListChatModel(responses=["Ответ модели"]))
    service = AgentService(graph)
    with pytest.raises(ValueError, match="пустым"):
        await service.run("")


async def test_run_rejects_whitespace_message() -> None:
    """Сообщение из одних пробелов отклоняется."""
    graph = build_chat_graph(FakeListChatModel(responses=["Ответ модели"]))
    service = AgentService(graph)
    with pytest.raises(ValueError, match="пустым"):
        await service.run("   ")
