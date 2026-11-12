"""Состояния графа агента."""

from typing import NotRequired, TypedDict

from langgraph.graph import MessagesState


class ChatState(TypedDict):
    """Состояние графа простого чата (без Tools).

    Attributes:
        message: Сообщение пользователя.
        response: Ответ агента. Заполняется узлами графа, поэтому не обязателен
            во входном состоянии.
    """

    message: str
    response: NotRequired[str]


class AgentState(MessagesState):
    """Состояние ReAct-графа: история сообщений + счётчик итераций.

    Attributes:
        messages: История сообщений (Human/AI/Tool) с редьюсером add_messages.
        iterations: Число итераций цикла агент↔tools — защита от бесконечного
            tool-calling.
        operation_context: Текстовый блок об активных операциях диалога
            (заполняется сервисом агента перед вызовом графа).
    """

    iterations: NotRequired[int]
    operation_context: NotRequired[str]
