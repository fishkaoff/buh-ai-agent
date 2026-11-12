"""Контекст диалога: привязка вызовов Tools к текущему чату.

Инструменты операций (`buh_ai_agent.tools.operations`) создаются один раз
при старте приложения, а идентификатор диалога известен только в момент
обработки сообщения. Диалоговый контекст передаётся через `ContextVar`:
сервис агента выставляет его перед вызовом графа, инструменты читают
внутри замыкания. `ContextVar` корректно изолирует параллельные запросы
в asyncio — каждый вызов графа получает свою копию контекста.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


class MissingDialogContextError(RuntimeError):
    """Инструмент вызван вне диалога (контекст не установлен)."""


@dataclass(frozen=True)
class DialogContext:
    """Контекст текущего диалога.

    Attributes:
        chat_id: Идентификатор диалога (Telegram-чата).
        user_id: Идентификатор пользователя.
        organization_id: Организация 1С из конфигурации (если известна).
        database_id: Идентификатор базы 1С из конфигурации (если известна).
    """

    chat_id: str
    user_id: str = ""
    organization_id: str = ""
    database_id: str = ""


_dialog_context: ContextVar[DialogContext | None] = ContextVar("dialog_context", default=None)


def get_dialog_context() -> DialogContext:
    """Возвращает контекст текущего диалога.

    Returns:
        Контекст диалога, установленный сервисом агента.

    Raises:
        MissingDialogContextError: Контекст не установлен.
    """
    context = _dialog_context.get()
    if context is None:
        raise MissingDialogContextError("Инструмент вызван вне диалога: контекст не установлен.")
    return context


@contextmanager
def bind_dialog_context(context: DialogContext) -> Iterator[None]:
    """Устанавливает контекст диалога внутри блока.

    Args:
        context: Контекст диалога (chat_id, user_id, данные 1С).
    """
    token = _dialog_context.set(context)
    try:
        yield
    finally:
        _dialog_context.reset(token)
