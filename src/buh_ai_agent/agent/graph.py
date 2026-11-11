"""Сборка и компиляция графа агента."""

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from buh_ai_agent.agent.nodes.chat import make_chat_node
from buh_ai_agent.agent.state import ChatState


def build_chat_graph(llm: BaseChatModel) -> CompiledStateGraph:
    """Собирает и компилирует граф агента: START → chat_node → END.

    Граф не привязан к конкретному провайдеру: узел получает модель через
    интерфейс BaseChatModel, поэтому провайдера можно заменить без изменения
    логики графа.

    Args:
        llm: Модель чата, созданная один раз при старте приложения.

    Returns:
        Скомпилированный граф чата.
    """
    builder = StateGraph(ChatState)
    builder.add_node("chat_node", make_chat_node(llm))
    builder.add_edge(START, "chat_node")
    builder.add_edge("chat_node", END)
    return builder.compile()
