"""Состояние графа агента."""

from typing import NotRequired, TypedDict


class ChatState(TypedDict):
    """Состояние графа чата.

    Attributes:
        message: Сообщение пользователя.
        response: Ответ агента. Заполняется узлами графа, поэтому не обязателен
            во входном состоянии.
    """

    message: str
    response: NotRequired[str]
