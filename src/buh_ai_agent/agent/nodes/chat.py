"""Узел чата: формирование ответа на сообщение пользователя через LLM."""

from collections.abc import Awaitable, Callable

from langchain_core.language_models.chat_models import BaseChatModel

from buh_ai_agent.agent.state import ChatState


def make_chat_node(llm: BaseChatModel) -> Callable[[ChatState], Awaitable[dict[str, str]]]:
    """Создаёт асинхронный узел чата, замыкающий конкретную модель.

    Args:
        llm: Модель чата — любой провайдер, совместимый с BaseChatModel.

    Returns:
        Асинхронная функция узла для StateGraph.
    """

    async def chat_node(state: ChatState) -> dict[str, str]:
        """Вызывает модель с сообщением пользователя и возвращает текст ответа.

        Поддерживается только обычный текстовый ввод и текстовый ответ.

        Args:
            state: Текущее состояние графа.

        Returns:
            Частичное обновление состояния с заполненным полем response.
        """
        message = state["message"]
        result = await llm.ainvoke(message)
        return {"response": result.text}

    return chat_node
