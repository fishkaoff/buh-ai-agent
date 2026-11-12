"""Узлы агента: простой чат и ReAct-цикл с tool-calling."""

from collections.abc import Awaitable, Callable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool

from buh_ai_agent.agent.state import AgentState, ChatState


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


def make_agent_node(
    llm: BaseChatModel,
    tools: list[BaseTool],
    system_prompt: str,
    *,
    max_iterations: int = 12,
) -> Callable[[AgentState], Awaitable[dict[str, object]]]:
    """Создаёт узел агента: LLM с привязанными Tools и системным промптом.

    Args:
        llm: Модель чата с поддержкой tool-calling.
        tools: Список доступных Tools.
        system_prompt: Системный промпт (роль, правила, список Skills).
        max_iterations: Максимум итераций цикла агент↔tools.

    Returns:
        Асинхронная функция узла для StateGraph.
    """
    model = llm.bind_tools(tools)

    async def agent_node(state: AgentState) -> dict[str, object]:
        """Вызывает модель с историей сообщений и системным промптом.

        Контекст активных операций диалога (`operation_context`) вставляется
        вторым системным сообщением — он меняется от запроса к запросу и не
        включается в фиксированный промпт.

        Args:
            state: Текущее состояние графа.

        Returns:
            Частичное обновление состояния: сообщение модели и счётчик итераций.
        """
        messages = list(state["messages"])
        if system_prompt and not (messages and isinstance(messages[0], SystemMessage)):
            messages.insert(0, SystemMessage(content=system_prompt))
        operation_context = state.get("operation_context") or ""
        if operation_context:
            messages.insert(
                1,
                SystemMessage(
                    content=f"<активные_операции>\n{operation_context}\n</активные_операции>"
                ),
            )
        ai_message = await model.ainvoke(messages)
        return {
            "messages": [ai_message],
            "iterations": state.get("iterations", 0) + 1,
        }

    return agent_node
