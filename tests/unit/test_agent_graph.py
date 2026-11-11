"""Юнит-тесты узла и графа агента."""

import inspect

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from buh_ai_agent.agent.graph import build_chat_graph
from buh_ai_agent.agent.nodes.chat import make_chat_node


def _fake_llm(*responses: str) -> FakeListChatModel:
    """Фейковая модель, возвращающая заготовленные ответы по порядку."""
    return FakeListChatModel(responses=list(responses))


async def test_chat_node_calls_llm_asynchronously() -> None:
    """Узел является асинхронной функцией, замкнутой на модель."""
    node = make_chat_node(_fake_llm("Ответ модели"))
    assert inspect.iscoroutinefunction(node)


async def test_chat_node_returns_response_from_llm() -> None:
    """Узел возвращает текст ответа модели в поле response."""
    node = make_chat_node(_fake_llm("Ответ модели"))
    result = await node({"message": "Привет"})
    assert set(result) == {"response"}
    assert result["response"] == "Ответ модели"


async def test_graph_ainvoke_updates_state() -> None:
    """Граф проходит START → chat_node → END и обновляет состояние."""
    graph = build_chat_graph(_fake_llm("Тестовый ответ"))
    result = await graph.ainvoke({"message": "Привет, что ты умеешь?"})
    assert result["message"] == "Привет, что ты умеешь?"
    assert result["response"] == "Тестовый ответ"


async def test_graph_ainvoke_is_repeatable() -> None:
    """Один и тот же скомпилированный граф обрабатывает несколько вызовов."""
    graph = build_chat_graph(_fake_llm("Первый ответ", "Второй ответ"))
    first = await graph.ainvoke({"message": "Первое"})
    second = await graph.ainvoke({"message": "Второе"})
    assert first["response"] == "Первый ответ"
    assert second["response"] == "Второй ответ"
