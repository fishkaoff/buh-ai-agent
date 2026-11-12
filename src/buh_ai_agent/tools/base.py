"""Единый формат результата Tools для агента.

Каждый Tool возвращает JSON вида `{"ok": true, "data": ...}` или
`{"ok": false, "error": "..."}` — понятный для LLM формат, без
внутренних stack traces.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Результат вызова Tool.

    Attributes:
        ok: True — операция выполнена; False — ошибка.
        error: Описание ошибки (пусто — ошибок не было).
        data: Данные результата (пусто — данных нет).
    """

    ok: bool
    error: str | None = None
    data: dict[str, Any] | None = Field(default=None)

    def to_json(self) -> str:
        """Сериализует результат в JSON-строку для агента."""
        return self.model_dump_json(exclude_none=True)


def tool_success(data: dict[str, Any]) -> str:
    """Формирует JSON-строку успешного результата для агента."""
    return ToolResult(ok=True, data=data).to_json()


def tool_error(message: str) -> str:
    """Формирует JSON-строку ошибки для агента (без stack traces)."""
    return ToolResult(ok=False, error=message).to_json()


def json_dumps_safe(payload: object) -> str:
    """Сериализует объект в JSON без исключений (fallback — repr)."""
    try:
        return json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):
        return repr(payload)
