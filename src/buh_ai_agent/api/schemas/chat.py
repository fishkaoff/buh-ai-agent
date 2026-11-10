"""Pydantic-модели для эндпоинта /chat."""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

Message = Annotated[str, StringConstraints(min_length=1, max_length=8000, strip_whitespace=True)]


class ChatRequest(BaseModel):
    """Входящее сообщение пользователя."""

    message: Message


class ChatResponse(BaseModel):
    """Ответ агента на сообщение пользователя."""

    reply: Message


class ChatNotImplementedResponse(BaseModel):
    """Заглушка ответа на период до подключения LangGraph и LLM."""

    detail: str = Field(min_length=1)
