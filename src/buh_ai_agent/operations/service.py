"""Сервис операций: машина состояний, идемпотентность, подтверждение.

Статусы: processing → awaiting_confirmation → confirmed | rejected | failed.

Создание бухгалтерских документов выполняется агентом через Tools до
момента передачи на подтверждение: операция в статусе
`awaiting_confirmation` уже содержит созданные документы 1С. Подтверждение
и отклонение только меняют состояние операции (проверяется принадлежность
диалогу); отправка по ЭДО на этом этапе не выполняется.

Защита от повторного выполнения одной операции — ключ идемпотентности,
проверяемый хранилищем (SQLite-данные переживают перезапуск приложения).
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from uuid import uuid4

from buh_ai_agent.operations.models import (
    ACTIVE_STATUSES,
    Operation,
    OperationDocument,
    OperationStatus,
)
from buh_ai_agent.operations.store import OperationStore


class OperationError(RuntimeError):
    """Недопустимый переход статуса, операция не найдена или чужой диалог."""


class OperationService:
    """Управляет операциями: создание, подтверждение, отклонение.

    Хранилище задаётся через `OperationStore` (SQLite в приложении,
    in-memory в тестах).
    """

    def __init__(self, store: OperationStore) -> None:
        """Создаёт сервис над заданным хранилищем.

        Args:
            store: Хранилище операций (например, `SQLiteStore`).
        """
        self._store = store
        self._lock = threading.Lock()

    def create(
        self,
        request: str,
        *,
        chat_id: str,
        user_id: str = "",
        organization_id: str = "",
        database_id: str = "",
        idempotency_key: str | None = None,
    ) -> Operation:
        """Создаёт операцию в статусе `processing`.

        Если операция с тем же ключом идемпотентности уже существует,
        возвращается она — повторное выполнение исключено.

        Args:
            request: Исходный запрос пользователя.
            chat_id: Идентификатор диалога (Telegram-чата).
            user_id: Идентификатор пользователя.
            organization_id: Организация 1С (если известна).
            database_id: Идентификатор базы 1С (если известна).
            idempotency_key: Ключ идемпотентности (пусто — без ключа).

        Returns:
            Созданная (или существующая при повторном ключе) операция.
        """
        now = datetime.now(tz=UTC).isoformat()
        with self._lock:
            if idempotency_key:
                existing = self._store.get_by_idempotency_key(idempotency_key)
                if existing is not None:
                    return existing
            operation = Operation(
                id=uuid4().hex,
                chat_id=chat_id,
                user_id=user_id,
                organization_id=organization_id,
                database_id=database_id,
                status=OperationStatus.PROCESSING,
                request=request,
                idempotency_key=idempotency_key,
                created_at=now,
                updated_at=now,
            )
            self._store.save(operation)
            return operation

    def submit_for_confirmation(
        self,
        operation_id: str,
        *,
        chat_id: str,
        documents: list[OperationDocument] | None = None,
        result: dict[str, object] | None = None,
    ) -> Operation:
        """Переводит операцию в `awaiting_confirmation`.

        Повторная передача допустима: при доработке неподтверждённой
        операции агент обновляет состав документов и снова передаёт её
        на подтверждение. Существующие документы при этом сохраняются —
        заданный список заменяет только указанные вызовом документы
        целиком, поэтому агент передаёт полный актуальный состав.

        Args:
            operation_id: Идентификатор операции.
            chat_id: Идентификатор диалога — должен совпадать с операцией.
            documents: Полный актуальный состав созданных документов 1С.
            result: Промежуточный результат выполнения.

        Returns:
            Обновлённая операция.

        Raises:
            OperationError: Операция не найдена, чужой диалог, или статус
                не допускает передачу на подтверждение.
        """
        with self._lock:
            operation = self._get(operation_id)
            self._check_chat(operation, chat_id)
            if operation.status not in ACTIVE_STATUSES:
                raise OperationError(
                    f"Операция {operation_id} в статусе {operation.status}; "
                    "передача на подтверждение возможна только для активной операции."
                )
            operation.status = OperationStatus.AWAITING_CONFIRMATION
            if documents is not None:
                operation.documents = list(documents)
            if result is not None:
                operation.result = result
            operation.updated_at = datetime.now(tz=UTC).isoformat()
            self._store.save(operation)
            return operation

    def confirm(self, operation_id: str, *, chat_id: str) -> Operation:
        """Подтверждает операцию: `awaiting_confirmation` → `confirmed`.

        Повторное подтверждение не допускается: операция в статусе
        `confirmed` (или любом конечном) не может быть подтверждена снова.
        На этом этапе подтверждение только меняет состояние операции —
        отправка по ЭДО не выполняется.

        Args:
            operation_id: Идентификатор операции.
            chat_id: Идентификатор диалога — должен совпадать с операцией.

        Returns:
            Операция в статусе `confirmed`.

        Raises:
            OperationError: Операция не найдена, чужой диалог или не ждёт
                подтверждения.
        """
        with self._lock:
            operation = self._get(operation_id)
            self._check_chat(operation, chat_id)
            if operation.status != OperationStatus.AWAITING_CONFIRMATION:
                raise OperationError(
                    f"Операция {operation_id} в статусе {operation.status}; "
                    f"ожидается {OperationStatus.AWAITING_CONFIRMATION}."
                )
            operation.status = OperationStatus.CONFIRMED
            operation.updated_at = datetime.now(tz=UTC).isoformat()
            self._store.save(operation)
            return operation

    def reject(self, operation_id: str, *, chat_id: str) -> Operation:
        """Отклоняет операцию: `awaiting_confirmation` → `rejected`.

        Повторное отклонение не допускается: отклонённая операция конечна.

        Args:
            operation_id: Идентификатор операции.
            chat_id: Идентификатор диалога — должен совпадать с операцией.

        Returns:
            Операция в статусе `rejected`.

        Raises:
            OperationError: Операция не найдена, чужой диалог или не ждёт
                подтверждения.
        """
        with self._lock:
            operation = self._get(operation_id)
            self._check_chat(operation, chat_id)
            if operation.status != OperationStatus.AWAITING_CONFIRMATION:
                raise OperationError(
                    f"Операция {operation_id} в статусе {operation.status}; "
                    f"ожидается {OperationStatus.AWAITING_CONFIRMATION}."
                )
            operation.status = OperationStatus.REJECTED
            operation.updated_at = datetime.now(tz=UTC).isoformat()
            self._store.save(operation)
            return operation

    def mark_failed(self, operation_id: str, error: str) -> Operation | None:
        """Помечает операцию неуспешной (статус `failed`).

        Args:
            operation_id: Идентификатор операции.
            error: Описание ошибки.

        Returns:
            Обновлённая операция или None, если операция не найдена.
        """
        with self._lock:
            operation = self._store.get(operation_id)
            if operation is None:
                return None
            operation.status = OperationStatus.FAILED
            operation.error = error
            operation.updated_at = datetime.now(tz=UTC).isoformat()
            self._store.save(operation)
            return operation

    def get(self, operation_id: str) -> Operation | None:
        """Возвращает операцию по идентификатору или None."""
        return self._store.get(operation_id)

    def list_operations(self) -> list[Operation]:
        """Возвращает все операции (порядок не определён)."""
        return self._store.list_operations()

    def list_by_chat(self, chat_id: str) -> list[Operation]:
        """Возвращает операции диалога (старые первыми)."""
        return self._store.list_by_chat(chat_id)

    def list_active_by_chat(self, chat_id: str) -> list[Operation]:
        """Возвращает активные (неподтверждённые) операции диалога."""
        return self._store.list_active_by_chat(chat_id)

    # ------------------------------------------------------------------
    # Внутренние помощники
    # ------------------------------------------------------------------

    def _get(self, operation_id: str) -> Operation:
        """Возвращает операцию или выбрасывает OperationError."""
        operation = self._store.get(operation_id)
        if operation is None:
            raise OperationError(f"Операция {operation_id} не найдена.")
        return operation

    @staticmethod
    def _check_chat(operation: Operation, chat_id: str) -> None:
        """Проверяет, что операция принадлежит указанному диалогу."""
        if operation.chat_id != chat_id:
            raise OperationError(f"Операция {operation.id} принадлежит другому диалогу.")
