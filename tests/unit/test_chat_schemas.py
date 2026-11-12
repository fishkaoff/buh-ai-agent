"""Юнит-тесты валидации входящего сообщения."""

import pytest
from pydantic import ValidationError

from buh_ai_agent.api.schemas.chat import (
    ChatRequest,
    ChatResponse,
    OperationActionRequest,
    OperationStatusResponse,
)


def test_chat_request_valid() -> None:
    """Корректное сообщение проходит валидацию."""
    request = ChatRequest(chat_id="chat-1", user_id="user-1", message="Привет, что ты умеешь?")
    assert request.chat_id == "chat-1"
    assert request.user_id == "user-1"
    assert request.message == "Привет, что ты умеешь?"


def test_chat_request_empty_message_rejected() -> None:
    """Пустое сообщение отклоняется."""
    with pytest.raises(ValidationError):
        ChatRequest(chat_id="chat-1", user_id="user-1", message="")


def test_chat_request_whitespace_message_rejected() -> None:
    """Сообщение из одних пробелов отклоняется."""
    with pytest.raises(ValidationError):
        ChatRequest(chat_id="chat-1", user_id="user-1", message="   ")


def test_chat_request_too_long_message_rejected() -> None:
    """Слишком длинное сообщение отклоняется."""
    with pytest.raises(ValidationError):
        ChatRequest(chat_id="chat-1", user_id="user-1", message="a" * 8001)


def test_chat_request_message_required() -> None:
    """Отсутствие поля message отклоняется."""
    with pytest.raises(ValidationError):
        ChatRequest(chat_id="chat-1", user_id="user-1")  # type: ignore[call-arg]


def test_chat_request_chat_id_required() -> None:
    """Отсутствие chat_id отклоняется — диалог должен быть идентифицирован."""
    with pytest.raises(ValidationError):
        ChatRequest(user_id="user-1", message="Привет")  # type: ignore[call-arg]


def test_chat_request_user_id_required() -> None:
    """Отсутствие user_id отклоняется."""
    with pytest.raises(ValidationError):
        ChatRequest(chat_id="chat-1", message="Привет")  # type: ignore[call-arg]


def test_chat_request_empty_chat_id_rejected() -> None:
    """Пустой chat_id отклоняется."""
    with pytest.raises(ValidationError):
        ChatRequest(chat_id="", user_id="user-1", message="Привет")


def test_chat_response_valid() -> None:
    """Модель ответа агента принимает непустой текст."""
    response = ChatResponse(reply="Я умею работать с 1С.")
    assert response.reply == "Я умею работать с 1С."
    assert response.operation_id is None


def test_chat_response_empty_reply_rejected() -> None:
    """Пустой ответ агента отклоняется."""
    with pytest.raises(ValidationError):
        ChatResponse(reply="")


def test_chat_response_with_operation() -> None:
    """Ответ с активной операцией содержит operation_id и статус."""
    response = ChatResponse(
        reply="Счёт создан.",
        operation_id="op-1",
        operation_status="awaiting_confirmation",
    )
    assert response.operation_id == "op-1"
    assert response.operation_status == "awaiting_confirmation"


def test_operation_action_request_valid() -> None:
    """Команда подтверждения содержит chat_id."""
    body = OperationActionRequest(chat_id="chat-1")
    assert body.chat_id == "chat-1"


def test_operation_action_request_requires_chat_id() -> None:
    """Команда без chat_id отклоняется."""
    with pytest.raises(ValidationError):
        OperationActionRequest()  # type: ignore[call-arg]


def test_operation_status_response() -> None:
    """Ответ со статусом операции сериализуется."""
    response = OperationStatusResponse(operation_id="op-1", status="confirmed")
    assert response.operation_id == "op-1"
    assert response.status == "confirmed"
