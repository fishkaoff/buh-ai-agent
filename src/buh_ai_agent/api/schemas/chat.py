"""Pydantic-модели для эндпоинта /chat."""

import base64
from typing import Annotated

from pydantic import BaseModel, StringConstraints

from buh_ai_agent.agent.context import AgentFile

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


class ResponseFile(BaseModel):
    """Файл (PDF печатной формы) в ответе агента, base64.

    Файлы не сохраняются приложением — существуют только в этом ответе.

    Attributes:
        name: Имя файла («schet_0000-000001.pdf»).
        content_type: MIME-тип («application/pdf»).
        size: Размер в байтах.
        kind: Тип содержимого («invoice» — счёт, «upd» — УПД).
        data_base64: Содержимое файла в base64.
    """

    name: str
    content_type: str = "application/pdf"
    size: int
    kind: str = ""
    data_base64: str

    @classmethod
    def from_agent_file(cls, file: AgentFile) -> "ResponseFile":
        """Строит модель из файла, приложенного Tools к ответу."""
        return cls(
            name=file.name,
            content_type=file.content_type,
            size=len(file.data),
            kind=file.kind,
            data_base64=base64.b64encode(file.data).decode("ascii"),
        )


class ChatResponse(BaseModel):
    """Ответ агента на сообщение пользователя.

    Attributes:
        reply: Текст ответа.
        operation_id: Идентификатор активной операции диалога, если есть —
            используется для команд подтверждения/отклонения.
        operation_status: Статус активной операции.
        files: PDF печатных форм, сформированные при обработке сообщения
            (пусто — файлов нет).
    """

    reply: Message
    operation_id: str | None = None
    operation_status: str | None = None
    files: list[ResponseFile] = []


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
