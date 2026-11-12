"""Операции: модель, статусы, документы 1С.

Операция — единица длительного действия (например, создание счёта в 1С).
Операция привязана к диалогу (chat_id) и пользователю (user_id):
пользователь может продолжать неподтверждённую операцию («добавь ещё
позицию»), а подтверждение и отклонение выполняются строго из того же
чата, где операция создана.

Состояние хранится в SQLite (см. `buh_ai_agent.storage`) — данные
переживают перезапуск приложения.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class OperationStatus(StrEnum):
    """Статусы операции.

    processing → awaiting_confirmation → confirmed | rejected,
    любая ошибка → failed.
    """

    PROCESSING = "processing"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    FAILED = "failed"


ACTIVE_STATUSES: frozenset[OperationStatus] = frozenset(
    {OperationStatus.PROCESSING, OperationStatus.AWAITING_CONFIRMATION}
)


class OperationDocument(BaseModel):
    """Документ 1С, созданный в рамках операции.

    Attributes:
        type: Тип документа (например, «invoice», «contract», «upd»).
        ref_key: Идентификатор объекта 1С (Ref_Key) — только из результатов Tools.
        number: Номер документа 1С (пусто, если номер не получен).
    """

    type: str
    ref_key: str
    number: str = ""


class Operation(BaseModel):
    """Операция агента, привязанная к диалогу.

    Attributes:
        id: Уникальный идентификатор операции.
        chat_id: Идентификатор диалога (Telegram-чата).
        user_id: Идентификатор пользователя.
        organization_id: Организация 1С (если определена).
        database_id: Идентификатор базы 1С (если определена).
        status: Текущий статус.
        request: Исходный запрос пользователя, породивший операцию.
        documents: Документы 1С, созданные в рамках операции.
        result: Результат выполнения.
        error: Ошибка выполнения (пусто — ошибок не было).
        idempotency_key: Ключ идемпотентности; повторное `create` с тем же
            ключом возвращает уже существующую операцию.
        created_at: Момент создания (ISO-время UTC).
        updated_at: Момент последнего изменения (ISO-время UTC).
    """

    id: str
    chat_id: str
    user_id: str = ""
    organization_id: str = ""
    database_id: str = ""
    status: OperationStatus = OperationStatus.PROCESSING
    request: str = ""
    documents: list[OperationDocument] = Field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    idempotency_key: str | None = None
    created_at: str = Field(default="", description="ISO-время UTC")
    updated_at: str = Field(default="", description="ISO-время UTC")

    def to_dict(self) -> dict[str, Any]:
        """Сериализует операцию в словарь (для хранилища)."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Operation:
        """Строит операцию из словаря хранилища."""
        return cls.model_validate(data)
