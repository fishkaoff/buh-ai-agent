"""Сборка и компиляция графа агента."""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from buh_ai_agent.agent.nodes.chat import make_agent_node, make_chat_node
from buh_ai_agent.agent.state import AgentState, ChatState


def build_chat_graph(
    llm: BaseChatModel,
    tools: list[BaseTool] | None = None,
    system_prompt: str = "",
    *,
    max_iterations: int = 12,
) -> CompiledStateGraph:
    """Собирает и компилирует граф агента.

    Без Tools — простой чат: START → chat_node → END.
    С Tools — ReAct-цикл: узел агента вызывает модель с привязанными
    Tools, модель либо вызывает инструменты (узел `tools`), либо даёт
    финальный текстовый ответ. Цикл ограничен max_iterations.

    Args:
        llm: Модель чата, созданная один раз при старте приложения.
        tools: Список LangChain-инструментов (None или [] — простой чат).
        system_prompt: Системный промпт (роль, правила, список Skills).
        max_iterations: Максимум итераций цикла агент↔tools.

    Returns:
        Скомпилированный граф чата.
    """
    if not tools:
        builder: StateGraph = StateGraph(ChatState)
        builder.add_node("chat_node", make_chat_node(llm))
        builder.add_edge(START, "chat_node")
        builder.add_edge("chat_node", END)
        return builder.compile()

    builder = StateGraph(AgentState)
    builder.add_node(
        "agent",
        make_agent_node(llm, tools, system_prompt, max_iterations=max_iterations),
    )
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "agent")

    def route(state: AgentState) -> str:
        """Маршрутизирует после узла агента: tools или завершение."""
        if state.get("iterations", 0) >= max_iterations:
            return END
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    builder.add_conditional_edges("agent", route)
    builder.add_edge("tools", "agent")
    return builder.compile()
