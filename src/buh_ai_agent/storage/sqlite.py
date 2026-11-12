"""SQLite-хранилище: история диалогов и операции.

Реализует протокол `OperationStore` и хранит историю сообщений диалогов.
Используется стандартный модуль `sqlite3`: без внешних инфраструктурных
компонентов (PostgreSQL, Redis, Kafka), данные переживают перезапуски
приложения.

Схема (idempotent, применяется при каждом открытии):

- `chat_messages` — сообщения диалога: пользовательские, ответы агента,
  результаты Tools и события (подтверждение/отклонение операций).
  Результат Tools сохраняется в `payload` в виде сериализованного
  LangChain-сообщения (`message_to_dict`) — этого достаточно, чтобы
  восстановить полный контекст ReAct-цикла, включая tool_calls.
- `operations` — операции агента с привязкой к диалогу.

Потокобезопасность: один connection с `check_same_thread=False`,
защищённый `threading.Lock` (SQLite-транзакции короткие, этого
достаточно для HTTP-нагрузки MVP).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from buh_ai_agent.operations.models import ACTIVE_STATUSES, Operation

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    payload TEXT,
    operation_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_chat ON chat_messages (chat_id, id);

CREATE TABLE IF NOT EXISTS operations (
    id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT '',
    organization_id TEXT NOT NULL DEFAULT '',
    database_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    request TEXT NOT NULL DEFAULT '',
    documents TEXT NOT NULL DEFAULT '[]',
    result TEXT,
    error TEXT,
    idempotency_key TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_operations_chat ON operations (chat_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_operations_idempotency
    ON operations (idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS dialog_skills (
    chat_id TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    loaded_at TEXT NOT NULL,
    PRIMARY KEY (chat_id, skill_name)
);

CREATE TABLE IF NOT EXISTS token_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cached_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_token_usage_chat ON token_usage (chat_id, id);
"""


class SQLiteStore:
    """SQLite-хранилище: история сообщений диалогов и операции.

    Данные переживают перезапуск приложения. Потокобезопасно: все
    операции с БД идут под одним `threading.Lock`.
    """

    def __init__(self, db_path: str | Path) -> None:
        """Открывает (и при необходимости создаёт) базу данных.

        Args:
            db_path: Путь к файлу БД (директория создаётся автоматически);
                `:memory:` — база в памяти (для тестов).
        """
        path = Path(db_path)
        if path.parent and str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ------------------------------------------------------------------
    # История сообщений
    # ------------------------------------------------------------------

    def append_message(
        self,
        chat_id: str,
        user_id: str,
        role: str,
        content: str,
        payload: str | None = None,
        operation_id: str | None = None,
    ) -> None:
        """Добавляет сообщение в историю диалога.

        Args:
            chat_id: Идентификатор диалога.
            user_id: Идентификатор пользователя.
            role: Роль сообщения (human/ai/tool/system/event).
            content: Текст сообщения (человекочитаемый).
            payload: Сериализованное LangChain-сообщение (JSON) —
                используется для восстановления контекста графа.
            operation_id: Идентификатор связанной операции (если есть).
        """
        with self._lock:
            self._conn.execute(
                "INSERT INTO chat_messages (chat_id, user_id, role, content, payload,"
                " operation_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    chat_id,
                    user_id,
                    role,
                    content,
                    payload,
                    operation_id,
                    _now(),
                ),
            )
            self._conn.commit()

    def get_recent_messages(self, chat_id: str, limit: int) -> list[dict[str, Any]]:
        """Возвращает последние сообщения диалога (старые первыми).

        Args:
            chat_id: Идентификатор диалога.
            limit: Максимум сообщений (0 — история не возвращается).

        Returns:
            Список строк: {chat_id, user_id, role, content, payload,
            operation_id, created_at}.
        """
        if limit <= 0:
            return []
        with self._lock:
            cursor = self._conn.execute(
                "SELECT chat_id, user_id, role, content, payload, operation_id, created_at"
                " FROM chat_messages WHERE chat_id = ?"
                " ORDER BY id DESC LIMIT ?",
                (chat_id, limit),
            )
            rows = list(cursor)
        rows.reverse()  # хронологический порядок
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Загруженные навыки диалога (не перезагружать)
    # ------------------------------------------------------------------

    def mark_skill_loaded(self, chat_id: str, skill_name: str) -> None:
        """Запоминает, что навык уже загружен в диалоге.

        Args:
            chat_id: Идентификатор диалога.
            skill_name: Имя навыка.
        """
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO dialog_skills (chat_id, skill_name, loaded_at)"
                " VALUES (?, ?, ?)",
                (chat_id, skill_name, _now()),
            )
            self._conn.commit()

    def get_loaded_skills(self, chat_id: str) -> list[str]:
        """Возвращает имена навыков, уже загруженных в диалоге.

        Args:
            chat_id: Идентификатор диалога.

        Returns:
            Список имён навыков (в порядке первой загрузки).
        """
        with self._lock:
            cursor = self._conn.execute(
                "SELECT skill_name FROM dialog_skills WHERE chat_id = ? ORDER BY rowid ASC",
                (chat_id,),
            )
            return [str(row["skill_name"]) for row in cursor]

    # ------------------------------------------------------------------
    # Учёт токенов
    # ------------------------------------------------------------------

    def record_token_usage(
        self,
        chat_id: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
    ) -> None:
        """Сохраняет расход токенов за один ход диалога.

        Args:
            chat_id: Идентификатор диалога.
            input_tokens: Входные токены (суммарно за все вызовы модели в ходе).
            output_tokens: Выходные токены (суммарно).
            cached_tokens: Из них обслужено из кэша префикса (если провайдер вернул).
        """
        with self._lock:
            self._conn.execute(
                "INSERT INTO token_usage (chat_id, input_tokens, output_tokens,"
                " cached_tokens, created_at) VALUES (?, ?, ?, ?, ?)",
                (chat_id, input_tokens, output_tokens, cached_tokens, _now()),
            )
            self._conn.commit()

    def get_token_usage(self, chat_id: str) -> dict[str, int]:
        """Возвращает суммарный расход токенов диалога.

        Args:
            chat_id: Идентификатор диалога.

        Returns:
            Словарь: {input_tokens, output_tokens, cached_tokens, turns}.
        """
        with self._lock:
            cursor = self._conn.execute(
                "SELECT COUNT(*) AS turns,"
                " COALESCE(SUM(input_tokens), 0) AS input_tokens,"
                " COALESCE(SUM(output_tokens), 0) AS output_tokens,"
                " COALESCE(SUM(cached_tokens), 0) AS cached_tokens"
                " FROM token_usage WHERE chat_id = ?",
                (chat_id,),
            )
            row = cursor.fetchone()
        return {
            "turns": int(row["turns"]),
            "input_tokens": int(row["input_tokens"]),
            "output_tokens": int(row["output_tokens"]),
            "cached_tokens": int(row["cached_tokens"]),
        }

    # ------------------------------------------------------------------
    # OperationStore (протокол)
    # ------------------------------------------------------------------

    def get(self, operation_id: str) -> Operation | None:
        """Возвращает операцию по идентификатору или None."""
        with self._lock:
            cursor = self._conn.execute("SELECT * FROM operations WHERE id = ?", (operation_id,))
            row = cursor.fetchone()
        return Operation.from_dict(self._row_to_dict(row)) if row is not None else None

    def get_by_idempotency_key(self, idempotency_key: str) -> Operation | None:
        """Возвращает операцию по ключу идемпотентности или None."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM operations WHERE idempotency_key = ?", (idempotency_key,)
            )
            row = cursor.fetchone()
        return Operation.from_dict(self._row_to_dict(row)) if row is not None else None

    def save(self, operation: Operation) -> None:
        """Сохраняет (создаёт или обновляет) операцию."""
        with self._lock:
            self._conn.execute(
                """INSERT INTO operations (
                        id, chat_id, user_id, organization_id, database_id, status,
                        request, documents, result, error, idempotency_key,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        chat_id = excluded.chat_id,
                        user_id = excluded.user_id,
                        organization_id = excluded.organization_id,
                        database_id = excluded.database_id,
                        status = excluded.status,
                        request = excluded.request,
                        documents = excluded.documents,
                        result = excluded.result,
                        error = excluded.error,
                        idempotency_key = excluded.idempotency_key,
                        created_at = excluded.created_at,
                        updated_at = excluded.updated_at""",
                (
                    operation.id,
                    operation.chat_id,
                    operation.user_id,
                    operation.organization_id,
                    operation.database_id,
                    operation.status.value,
                    operation.request,
                    json.dumps(
                        [doc.model_dump(mode="json") for doc in operation.documents],
                        ensure_ascii=False,
                    ),
                    json.dumps(operation.result, ensure_ascii=False)
                    if operation.result is not None
                    else None,
                    operation.error,
                    operation.idempotency_key,
                    operation.created_at,
                    operation.updated_at,
                ),
            )
            self._conn.commit()

    def list_operations(self) -> list[Operation]:
        """Возвращает все операции (порядок не определён)."""
        with self._lock:
            cursor = self._conn.execute("SELECT * FROM operations")
            rows = list(cursor)
        return [Operation.from_dict(self._row_to_dict(row)) for row in rows]

    def list_by_chat(self, chat_id: str) -> list[Operation]:
        """Возвращает операции диалога, отсортированные по created_at."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM operations WHERE chat_id = ? ORDER BY created_at ASC, id ASC",
                (chat_id,),
            )
            rows = list(cursor)
        return [Operation.from_dict(self._row_to_dict(row)) for row in rows]

    def list_active_by_chat(self, chat_id: str) -> list[Operation]:
        """Возвращает активные (неподтверждённые) операции диалога."""
        operations = self.list_by_chat(chat_id)
        return [op for op in operations if op.status in ACTIVE_STATUSES]

    def close(self) -> None:
        """Закрывает соединение с базой данных."""
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------
    # Внутренние помощники
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        """Преобразует строку таблицы operations в словарь для модели."""
        return {
            "id": row["id"],
            "chat_id": row["chat_id"],
            "user_id": row["user_id"],
            "organization_id": row["organization_id"],
            "database_id": row["database_id"],
            "status": row["status"],
            "request": row["request"],
            "documents": json.loads(row["documents"] or "[]"),
            "result": json.loads(row["result"]) if row["result"] else None,
            "error": row["error"],
            "idempotency_key": row["idempotency_key"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


def _now() -> str:
    """Текущее время в ISO-формате UTC."""
    return datetime.now(tz=UTC).isoformat()
