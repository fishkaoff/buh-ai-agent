"""Хранилище операций: протокол, in-memory и SQLite реализации.

По умолчанию приложение использует SQLite-хранилище
(`buh_ai_agent.storage.SQLiteStore`), которое переживает перезапуски.
In-memory реализация остаётся для юнит-тестов и как эталон интерфейса.
"""

from __future__ import annotations

import threading
from typing import Protocol

from buh_ai_agent.operations.models import ACTIVE_STATUSES, Operation


class OperationStore(Protocol):
    """Протокол хранилища операций.

    Реализации должны быть потокобезопасны: HTTP-запросы и агент
    обращаются к одному хранилищу.
    """

    def get(self, operation_id: str) -> Operation | None:
        """Возвращает операцию по идентификатору или None."""
        ...

    def get_by_idempotency_key(self, idempotency_key: str) -> Operation | None:
        """Возвращает операцию по ключу идемпотентности или None."""
        ...

    def save(self, operation: Operation) -> None:
        """Сохраняет (создаёт или обновляет) операцию."""
        ...

    def list_operations(self) -> list[Operation]:
        """Возвращает все операции (порядок не определён)."""
        ...

    def list_by_chat(self, chat_id: str) -> list[Operation]:
        """Возвращает операции диалога (старые первыми)."""
        ...

    def list_active_by_chat(self, chat_id: str) -> list[Operation]:
        """Возвращает активные (неподтверждённые) операции диалога."""
        ...


class InMemoryOperationStore:
    """Хранилище операций в памяти процесса.

    Потокобезопасно: доступ к словарям защищён `threading.Lock`.
    После перезапуска операции теряются — для продакшена используйте
    `SQLiteStore`.
    """

    def __init__(self) -> None:
        """Создаёт пустое хранилище."""
        self._operations: dict[str, Operation] = {}
        self._by_idempotency: dict[str, str] = {}
        self._lock = threading.Lock()

    def get(self, operation_id: str) -> Operation | None:
        """Возвращает операцию по идентификатору или None."""
        with self._lock:
            stored = self._operations.get(operation_id)
            return Operation.from_dict(stored) if stored is not None else None

    def get_by_idempotency_key(self, idempotency_key: str) -> Operation | None:
        """Возвращает операцию по ключу идемпотентности или None."""
        with self._lock:
            operation_id = self._by_idempotency.get(idempotency_key)
            if operation_id is None:
                return None
            stored = self._operations.get(operation_id)
            return Operation.from_dict(stored) if stored is not None else None

    def save(self, operation: Operation) -> None:
        """Сохраняет (создаёт или обновляет) операцию."""
        with self._lock:
            stored = operation.to_dict()
            self._operations[operation.id] = Operation.from_dict(stored)
            if operation.idempotency_key:
                self._by_idempotency[operation.idempotency_key] = operation.id

    def list_operations(self) -> list[Operation]:
        """Возвращает все операции (порядок не определён)."""
        with self._lock:
            return [
                Operation.from_dict(operation.to_dict()) for operation in self._operations.values()
            ]

    def list_by_chat(self, chat_id: str) -> list[Operation]:
        """Возвращает операции диалога, отсортированные по created_at."""
        operations = [op for op in self.list_operations() if op.chat_id == chat_id]
        return sorted(operations, key=lambda op: op.created_at)

    def list_active_by_chat(self, chat_id: str) -> list[Operation]:
        """Возвращает активные (неподтверждённые) операции диалога."""
        return [op for op in self.list_by_chat(chat_id) if op.status in ACTIVE_STATUSES]
