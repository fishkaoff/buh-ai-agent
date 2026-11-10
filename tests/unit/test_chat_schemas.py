"""Юнит-тесты валидации входящего сообщения."""

import pytest
from pydantic import ValidationError

from buh_ai_agent.api.schemas.chat import ChatRequest, ChatResponse


def test_chat_request_valid() -> None:
    """Корректное сообщение проходит валидацию."""
    request = ChatRequest(message="Привет, что ты умеешь?")
    assert request.message == "Привет, что ты умеешь?"


def test_chat_request_empty_message_rejected() -> None:
    """Пустое сообщение отклоняется."""
    with pytest.raises(ValidationError):
        ChatRequest(message="")


def test_chat_request_whitespace_message_rejected() -> None:
    """Сообщение из одних пробелов отклоняется."""
    with pytest.raises(ValidationError):
        ChatRequest(message="   ")


def test_chat_request_too_long_message_rejected() -> None:
    """Слишком длинное сообщение отклоняется."""
    with pytest.raises(ValidationError):
        ChatRequest(message="a" * 8001)


def test_chat_request_message_required() -> None:
    """Отсутствие поля message отклоняется."""
    with pytest.raises(ValidationError):
        ChatRequest()  # type: ignore[call-arg]


def test_chat_response_valid() -> None:
    """Модель ответа агента принимает непустой текст."""
    response = ChatResponse(reply="Я умею работать с 1С.")
    assert response.reply == "Я умею работать с 1С."


def test_chat_response_empty_reply_rejected() -> None:
    """Пустой ответ агента отклоняется."""
    with pytest.raises(ValidationError):
        ChatResponse(reply="")
