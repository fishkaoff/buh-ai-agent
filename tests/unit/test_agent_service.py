"""Юнит-тесты сервиса агента: диалоги, история, изоляция чатов."""

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from tests.fake_models import fake_tool_llm

from buh_ai_agent.agent.graph import build_chat_graph
from buh_ai_agent.agent.service import AgentService
from buh_ai_agent.operations import OperationService
from buh_ai_agent.storage.sqlite import SQLiteStore


@tool
async def dummy_tool(query: str = "") -> str:
    """Тестовый инструмент-заглушка."""
    return "заглушка"


def make_react_service(
    responses: list[AIMessage],
    *,
    history_limit: int = 10,
) -> AgentService:
    """Сервис агента с ReAct-графом и in-memory SQLite."""
    graph = build_chat_graph(fake_tool_llm(*responses), tools=[dummy_tool])
    store = SQLiteStore(":memory:")
    operation_service = OperationService(store)
    return AgentService(graph, store, operation_service, history_limit=history_limit)


def make_simple_service(
    responses: list[str],
    *,
    history_limit: int = 10,
) -> AgentService:
    """Сервис агента с простым графом (без Tools) и in-memory SQLite."""
    graph = build_chat_graph(FakeListChatModel(responses=responses))
    store = SQLiteStore(":memory:")
    operation_service = OperationService(store)
    return AgentService(graph, store, operation_service, history_limit=history_limit)


async def test_run_returns_llm_response() -> None:
    """Асинхронный вызов графа возвращает текст ответа модели."""
    service = make_simple_service(["Ответ модели"])
    result = await service.run("chat-1", "user-1", "Привет, что ты умеешь?")
    assert result.reply == "Ответ модели"


async def test_run_rejects_empty_message() -> None:
    """Пустое сообщение отклоняется с понятной ошибкой."""
    service = make_simple_service(["Ответ модели"])
    with pytest.raises(ValueError, match="пустым"):
        await service.run("chat-1", "user-1", "")


async def test_run_rejects_whitespace_message() -> None:
    """Сообщение из одних пробелов отклоняется."""
    service = make_simple_service(["Ответ модели"])
    with pytest.raises(ValueError, match="пустым"):
        await service.run("chat-1", "user-1", "   ")


async def test_history_is_saved_between_react_calls() -> None:
    """ReAct-цикл сохраняет сообщения пользователя и ответы с результатами Tools."""
    service = make_react_service(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "dummy_tool", "args": {"query": "x"}, "id": "call-1"}],
            ),
            AIMessage(content="Ответ с использованием результата"),
        ]
    )
    await service.run("chat-1", "user-1", "Первое сообщение")
    rows = service._store.get_recent_messages("chat-1", 10)
    roles = [row["role"] for row in rows]
    # human + ai(tool_calls) + tool + ai(финальный ответ)
    assert roles == ["human", "ai", "tool", "ai"]


async def test_react_reply_extracted_from_last_ai_message() -> None:
    """Ответ — текст последнего AI-сообщения, а не результата Tools."""
    service = make_react_service(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "dummy_tool", "args": {"query": "x"}, "id": "call-1"}],
            ),
            AIMessage(content="Финальный ответ"),
        ]
    )
    result = await service.run("chat-1", "user-1", "Сообщение")
    assert result.reply == "Финальный ответ"


async def test_chats_are_isolated() -> None:
    """Контекст разных чатов не смешивается."""
    service = make_simple_service(["Ответ 1", "Ответ 2"])
    await service.run("chat-1", "user-1", "Сообщение чата 1")
    await service.run("chat-2", "user-2", "Сообщение чата 2")
    first = service._store.get_recent_messages("chat-1", 10)
    second = service._store.get_recent_messages("chat-2", 10)
    assert len(first) == 2
    assert len(second) == 2
    assert first[0]["content"] == "Сообщение чата 1"
    assert second[0]["content"] == "Сообщение чата 2"


async def test_history_limit_bounds_react_context() -> None:
    """Лимит истории: в контекст LLM попадает ограниченное число сообщений."""
    service = make_react_service(
        [
            AIMessage(content="Ответ 1"),
            AIMessage(content="Ответ 2"),
        ],
        history_limit=4,
    )
    await service.run("chat-1", "user-1", "Вопрос 1")
    await service.run("chat-1", "user-1", "Вопрос 2")
    rows = service._store.get_recent_messages("chat-1", 100)
    assert len(rows) == 4  # Вопрос 1, Ответ 1, Вопрос 2, Ответ 2


async def test_reply_includes_active_operation() -> None:
    """Ответ содержит данные активной операции диалога."""
    service = make_simple_service(["Ответ"])
    operation = service._operation_service.create("Создай счёт", chat_id="chat-1", user_id="user-1")
    result = await service.run("chat-1", "user-1", "Продолжаем?")
    assert result.operation_id == operation.id
    assert result.operation_status == "processing"


async def test_reply_without_operations() -> None:
    """Без активных операций operation_id пуст."""
    service = make_simple_service(["Ответ"])
    result = await service.run("chat-1", "user-1", "Привет")
    assert result.operation_id is None
    assert result.operation_status is None


async def test_operation_context_built_for_active_operations() -> None:
    """Активные операции есть у первого чата и нет у подтверждённой операции."""
    service = make_simple_service(["Ответ"])
    service._operation_service.create("Создай счёт", chat_id="chat-1")
    other = service._operation_service.create("Создай акт", chat_id="chat-2")
    service._operation_service.submit_for_confirmation(other.id, chat_id="chat-2")
    service._operation_service.confirm(other.id, chat_id="chat-2")
    assert len(service._operation_service.list_active_by_chat("chat-1")) == 1
    assert service._operation_service.list_active_by_chat("chat-2") == []


# ------------------------------------------------------------------
# Side-channel файлов (PDF печатных форм) в ответе
# ------------------------------------------------------------------


@tool
async def file_tool() -> str:
    """Прикладывает тестовый PDF к ответу текущего хода."""
    from buh_ai_agent.agent.context import AgentFile, get_dialog_context

    get_dialog_context().attach_file(
        AgentFile(
            name="schet_test.pdf", content_type="application/pdf", data=b"%PDF-1.4", kind="invoice"
        )
    )
    return '{"ok": true}'


async def test_reply_carries_attached_files() -> None:
    """Файлы, приложенные Tools к ответу, возвращаются в AgentReply и не хранятся."""
    graph = build_chat_graph(
        fake_tool_llm(
            AIMessage(
                content="",
                tool_calls=[{"name": "file_tool", "args": {}, "id": "call-1"}],
            ),
            AIMessage(content="Счёт создан, PDF приложен"),
        ),
        tools=[file_tool],
    )
    service = AgentService(
        graph,
        SQLiteStore(":memory:"),
        OperationService(SQLiteStore(":memory:")),
    )
    result = await service.run("chat-1", "user-1", "Создай счёт с PDF")
    assert result.reply == "Счёт создан, PDF приложен"
    assert len(result.files) == 1
    assert result.files[0].name == "schet_test.pdf"
    assert result.files[0].data == b"%PDF-1.4"


async def test_reply_without_files() -> None:
    """Без приложенных файлов поле files пустое."""
    service = make_simple_service(["Ответ"])
    result = await service.run("chat-1", "user-1", "Привет")
    assert result.files == ()
