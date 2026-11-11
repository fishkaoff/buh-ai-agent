"""Сервис агента: вызов графа из HTTP-слоя."""

from langgraph.graph.state import CompiledStateGraph


class AgentService:
    """Обёртка над скомпилированным графом для вызова из HTTP-слоя.

    HTTP-слой не знает внутреннего устройства графа: сервис принимает
    сообщение пользователя и возвращает готовый ответ.
    """

    def __init__(self, graph: CompiledStateGraph) -> None:
        """Инициализирует сервис скомпилированным графом.

        Args:
            graph: Граф, скомпилированный один раз при старте приложения.
        """
        self._graph = graph

    async def run(self, message: str) -> str:
        """Проводит сообщение пользователя через граф агента.

        Args:
            message: Сообщение пользователя.

        Returns:
            Ответ агента.

        Raises:
            ValueError: Если сообщение пустое или состоит только из пробелов.
        """
        if not message.strip():
            raise ValueError("Сообщение не может быть пустым.")
        result = await self._graph.ainvoke({"message": message})
        return result["response"]
