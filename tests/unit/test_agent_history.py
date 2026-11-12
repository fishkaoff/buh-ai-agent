"""Юнит-тесты истории диалога: сериализация, лимит, контекст операций."""

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from buh_ai_agent.agent.history import (
    build_operation_context,
    deserialize_message,
    row_to_message,
    serialize_message,
    trim_history,
)
from buh_ai_agent.operations import Operation, OperationStatus


def test_serialize_deserialize_roundtrip() -> None:
    """Сериализация и восстановление сообщения сохраняют содержимое."""
    message = HumanMessage(content="Создай счёт")
    restored = deserialize_message(serialize_message(message))
    assert restored is not None
    assert isinstance(restored, HumanMessage)
    assert restored.content == "Создай счёт"


def test_serialize_deserialize_ai_with_tool_calls() -> None:
    """AI-сообщение с tool_calls восстанавливается целиком."""
    message = AIMessage(
        content="", tool_calls=[{"name": "create_invoice", "args": {"sum": 1}, "id": "call-1"}]
    )
    restored = deserialize_message(serialize_message(message))
    assert restored is not None
    assert isinstance(restored, AIMessage)
    assert restored.tool_calls == message.tool_calls


def test_deserialize_broken_payload_returns_none() -> None:
    """Повреждённый payload — None."""
    assert deserialize_message("not-json") is None
    assert deserialize_message('{"type": 42}') is None
    assert deserialize_message("") is None


def test_row_to_message_from_payload() -> None:
    """Строка с payload восстанавливается как LangChain-сообщение."""
    payload = serialize_message(ToolMessage(content="результат", tool_call_id="call-1"))
    message = row_to_message({"role": "tool", "content": "результат", "payload": payload})
    assert isinstance(message, ToolMessage)
    assert message.tool_call_id == "call-1"


def test_row_to_message_fallback_to_human() -> None:
    """Строка без payload (событие) превращается в Human-сообщение."""
    message = row_to_message({"role": "event", "content": "Операция подтверждена"})
    assert isinstance(message, HumanMessage)
    assert message.content == "Операция подтверждена"


def test_trim_history_within_limit() -> None:
    """История короче лимита не обрезается."""
    messages = [HumanMessage(content="1"), AIMessage(content="2")]
    assert trim_history(messages, 10) == messages


def test_trim_history_zero_limit() -> None:
    """Лимит 0 — пустая история."""
    assert trim_history([HumanMessage(content="1")], 0) == []


def test_trim_history_keeps_tool_integrity() -> None:
    """Первым сообщением не может быть ToolMessage или AI с tool_calls."""
    messages = [
        HumanMessage(content="Вопрос"),
        AIMessage(
            content="",
            tool_calls=[{"name": "t", "args": {}, "id": "call-1"}],
        ),
        ToolMessage(content="результат", tool_call_id="call-1"),
        AIMessage(content="Ответ"),
        HumanMessage(content="Продолжение"),
        AIMessage(content="Ответ 2"),
    ]
    trimmed = trim_history(messages, 3)
    # Последние 3: Продолжение, Ответ 2 + ... но обрезка начинается с
    # HumanMessage: [Продолжение, Ответ 2]? Проверяем валидность.
    assert len(trimmed) <= 3
    assert not isinstance(trimmed[0], ToolMessage)
    first = trimmed[0]
    if isinstance(first, AIMessage):
        assert not first.tool_calls


def test_trim_history_drops_orphan_tool_call_head() -> None:
    """AI-сообщение с отрезанными tool_calls отбрасывается."""
    messages = [
        HumanMessage(content="Вопрос"),
        AIMessage(
            content="",
            tool_calls=[{"name": "t", "args": {}, "id": "call-1"}],
        ),
        ToolMessage(content="результат", tool_call_id="call-1"),
        AIMessage(content="Ответ"),
    ]
    trimmed = trim_history(messages, 1)
    assert [type(m).__name__ for m in trimmed] == ["AIMessage"]
    assert trimmed[0].content == "Ответ"


def test_trim_history_drops_system_head() -> None:
    """SystemMessage в начале истории отбрасывается."""
    messages = [
        SystemMessage(content="Системное сообщение"),
        HumanMessage(content="Вопрос"),
        AIMessage(content="Ответ"),
    ]
    trimmed = trim_history(messages, 2)
    assert all(not isinstance(m, SystemMessage) for m in trimmed)


def make_operation(operation_id: str, status: OperationStatus) -> Operation:
    """Создаёт тестовую операцию."""
    return Operation(
        id=operation_id,
        chat_id="chat-1",
        user_id="user-1",
        status=status,
        request="Создай счёт",
        documents=[],
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def test_build_operation_context_empty() -> None:
    """Без активных операций контекст пуст."""
    assert build_operation_context([]) == ""


def test_build_operation_context_contains_operation() -> None:
    """Контекст содержит идентификатор, статус и запрос операции."""
    operation = make_operation("op-1", OperationStatus.AWAITING_CONFIRMATION)
    context = build_operation_context([operation])
    assert "op-1" in context
    assert OperationStatus.AWAITING_CONFIRMATION.value in context
    assert "Создай счёт" in context
    assert "уточняющий вопрос" in context
