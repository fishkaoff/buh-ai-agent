"""Pydantic-модели для эндпоинта /chat."""

from typing import Annotated

from pydantic import BaseModel, StringConstraints

Message = Annotated[str, StringConstraints(min_length=1, max_length=8000, strip_whitespace=True)]

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=256, strip_whitespace=True)]


class ChatRequest(BaseModel):
    """Входящее сообщение пользователя.

    Attributes:
        chat_id: Идентификатор диалога (Telegram-чата). Разные чаты
            имеют независимый контекст.
        user_id: Идентификатор пользователя Telegram.
        message: Текст сообщения.
    """

    chat_id: Identifier
    user_id: Identifier
    message: Message


class ChatResponse(BaseModel):
    """Ответ агента на сообщение пользователя.

    Attributes:
        reply: Текст ответа.
        operation_id: Идентификатор активной операции диалога, если есть —
            используется для команд подтверждения/отклонения.
        operation_status: Статус активной операции.
    """

    reply: Message
    operation_id: str | None = None
    operation_status: str | None = None


class OperationActionRequest(BaseModel):
    """Команда подтверждения/отклонения операции.

    Attributes:
        chat_id: Идентификатор диалога — операция должна принадлежать ему.
    """

    chat_id: Identifier


class OperationStatusResponse(BaseModel):
    """Результат смены статуса операции."""

    operation_id: str
    status: str
