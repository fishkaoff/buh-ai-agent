"""История диалога: сериализация, восстановление, ограничение контекста.

Сообщения графа (пользователь, ответы агента, результаты Tools) хранятся
в SQLite в виде сериализованных LangChain-сообщений (`message_to_dict`).
Так восстанавливается полный контекст ReAct-цикла: AI-сообщения с
tool_calls и ToolMessage с результатами инструментов.

Контекст ограничен настройкой `agent_history_messages`: в LLM уходит
только последние N сообщений. Обрезка выполняется с учётом целостности
tool-потока: нельзя начинать историю с ToolMessage или с AI-сообщения,
у которого tool_calls отрезаны (модель отклонит такой запрос).
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    message_to_dict,
    messages_from_dict,
)


def serialize_message(message: BaseMessage) -> str:
    """Сериализует LangChain-сообщение в JSON-строку.

    Args:
        message: Сообщение графа (Human/AI/Tool/System).

    Returns:
        JSON-строка для столбца `payload` таблицы `chat_messages`.
    """
    return json.dumps(message_to_dict(message), ensure_ascii=False)


def deserialize_message(payload: str) -> BaseMessage | None:
    """Восстанавливает LangChain-сообщение из JSON-строки.

    Args:
        payload: JSON-строка, созданная `serialize_message`.

    Returns:
        Сообщение или None, если payload повреждён.
    """
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        restored = messages_from_dict([data])
    except (KeyError, TypeError, ValueError):
        return None
    return restored[0] if restored else None


def row_to_message(row: dict[str, Any]) -> BaseMessage:
    """Преобразует строку истории в LangChain-сообщение.

    Сообщения с полным payload восстанавливаются как есть (включая
    tool_calls и ToolMessage). Сообщения без payload (события —
    подтверждение/отклонение операций) превращаются в Human-сообщение,
    чтобы агент видел их в контексте.

    Args:
        row: Строка из `SQLiteStore.get_recent_messages`.

    Returns:
        LangChain-сообщение.
    """
    payload = row.get("payload")
    if payload:
        restored = deserialize_message(payload)
        if restored is not None:
            return restored
    return HumanMessage(content=str(row.get("content") or ""))


def trim_history(messages: list[BaseMessage], limit: int) -> list[BaseMessage]:
    """Обрезает историю до последних `limit` сообщений.

    Обрезка учитывает целостность tool-потока: первым сообщением истории
    не может быть ToolMessage или AI-сообщение с tool_calls (парные
    ToolMessage к нему могли отрезаться). Такие ведущие сообщения
    отбрасываются.

    Args:
        messages: Полная история (старые первыми).
        limit: Максимум сообщений (0 — пустая история).

    Returns:
        Обрезанная история.
    """
    if limit <= 0:
        return []
    if len(messages) <= limit:
        return list(messages)
    trimmed = list(messages[-limit:])
    while trimmed and (
        isinstance(trimmed[0], ToolMessage)
        or (isinstance(trimmed[0], AIMessage) and trimmed[0].tool_calls)
        or isinstance(trimmed[0], SystemMessage)
    ):
        trimmed = trimmed[1:]
    return trimmed


def build_operation_context(
    operations: list[Any],
    loaded_skills: list[str] | None = None,
) -> str:
    """Строит текстовый блок об активных операциях для системного промпта.

    Args:
        operations: Активные операции диалога (объекты `Operation`).
        loaded_skills: Навыки, уже загруженные в диалоге (не перезагружать).

    Returns:
        Текст для вставки в промпт; пустая строка, если нечего сообщить.
    """
    lines: list[str] = []
    if loaded_skills:
        lines.append(
            "Навыки, уже загруженные в этом диалоге (load_skill перезагружать не нужно): "
            + ", ".join(loaded_skills)
            + "."
        )
    if not operations:
        return "\n".join(lines)
    lines.append("Активные операции этого диалога (неподтверждённые):")
    for operation in operations:
        docs = (
            "; ".join(
                f"{doc.type} {doc.number} (Ref_Key {doc.ref_key})".strip()
                for doc in operation.documents
            )
            or "документы не созданы"
        )
        lines.append(
            f"- operation_id: {operation.id}, статус: {operation.status}, "
            f"запрос: «{operation.request}», созданные документы: {docs}."
        )
    lines.append(
        "Если запрос пользователя продолжает одну из этих операций — работайте "
        "с ней (не создавайте новую операцию и не создавайте документы заново). "
        "Если активных операций несколько и непонятно, о какой речь — задайте "
        "уточняющий вопрос."
    )
    return "\n".join(lines)
