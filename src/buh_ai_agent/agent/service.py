"""Сервис агента: последовательный диалог с сохранением контекста.

Диалог идентифицируется `chat_id` (идентификатор Telegram-чата): история
сообщений и активные операции загружаются только из этого диалога,
контексты разных чатов не смешиваются.

На каждый вызов:
1. Сообщение пользователя сохраняется в историю (SQLite).
2. Из истории загружается ограниченный контекст диалога (последние
   `history_limit` сообщений, включая результаты Tools).
3. Из хранилища операций берутся активные операции диалога — они
   передаются агенту в системном сообщении, чтобы агент продолжал
   существующие операции, а не создавал новые.
4. Граф вызывается с восстановленной историей; новые сообщения графа
   (ответы агента, результаты Tools) сохраняются в историю.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.state import CompiledStateGraph

from buh_ai_agent.agent.context import DialogContext, bind_dialog_context
from buh_ai_agent.agent.history import (
    build_operation_context,
    row_to_message,
    serialize_message,
    trim_history,
)
from buh_ai_agent.operations import OperationService
from buh_ai_agent.operations.models import Operation, OperationStatus
from buh_ai_agent.storage.sqlite import SQLiteStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentReply:
    """Ответ агента на сообщение пользователя.

    Attributes:
        reply: Текст ответа.
        operation_id: Идентификатор активной операции диалога (если есть) —
            для команд подтверждения/отклонения.
        operation_status: Статус этой операции.
    """

    reply: str
    operation_id: str | None = None
    operation_status: str | None = None


class AgentService:
    """Обёртка над скомпилированным графом для вызова из HTTP-слоя.

    HTTP-слой не знает внутреннего устройства графа: сервис принимает
    идентификаторы диалога/пользователя и сообщение, а историю, контекст
    операций и результаты Tools загружает и сохраняет сам.
    """

    def __init__(
        self,
        graph: CompiledStateGraph,
        store: SQLiteStore,
        operation_service: OperationService,
        *,
        history_limit: int = 10,
        organization_id: str = "",
        database_id: str = "",
    ) -> None:
        """Инициализирует сервис скомпилированным графом и хранилищами.

        Args:
            graph: Граф, скомпилированный один раз при старте приложения.
            store: SQLite-хранилище истории сообщений.
            operation_service: Сервис операций (то же хранилище).
            history_limit: Максимум сообщений истории в контексте LLM.
            organization_id: Организация 1С по умолчанию (из конфигурации).
            database_id: Идентификатор базы 1С (из конфигурации).
        """
        self._graph = graph
        self._store = store
        self._operation_service = operation_service
        self._history_limit = history_limit
        self._organization_id = organization_id
        self._database_id = database_id
        input_properties = graph.get_input_jsonschema().get("properties", {})
        self._messages_input = "messages" in input_properties and "message" not in input_properties

    async def run(self, chat_id: str, user_id: str, message: str) -> AgentReply:
        """Обрабатывает сообщение пользователя в рамках диалога.

        Args:
            chat_id: Идентификатор диалога (Telegram-чата).
            user_id: Идентификатор пользователя.
            message: Сообщение пользователя.

        Returns:
            Ответ агента и данные активной операции (если есть).

        Raises:
            ValueError: Если сообщение пустое или состоит только из пробелов.
        """
        if not message.strip():
            raise ValueError("Сообщение не может быть пустым.")

        # История загружается до сохранения текущего сообщения: оно
        # добавляется во вход графа отдельно (иначе — дубликат).
        history = trim_history(
            [
                row_to_message(row)
                for row in self._store.get_recent_messages(chat_id, self._history_limit)
            ],
            self._history_limit,
        )
        operation_context = build_operation_context(
            self._operation_service.list_active_by_chat(chat_id),
            loaded_skills=self._store.get_loaded_skills(chat_id),
        )
        self._store.append_message(chat_id, user_id, "human", message)

        context = DialogContext(
            chat_id=chat_id,
            user_id=user_id,
            organization_id=self._organization_id,
            database_id=self._database_id,
        )
        with bind_dialog_context(context):
            if self._messages_input:
                input_messages = [*history, HumanMessage(content=message)]
                # Каждому входному сообщению присваивается свежий id:
                # ответ модели не может столкнуться с историческим
                # сообщением (редьюсер add_messages заменяет по id).
                for item in input_messages:
                    item.id = uuid4().hex
                result = await self._graph.ainvoke(
                    {
                        "messages": input_messages,
                        "operation_context": operation_context,
                    }
                )
                # Редьюсер add_messages сохраняет входные сообщения в начале
                # в исходном порядке — новыми считаются всё после входа.
                new_messages = result["messages"][len(input_messages) :]
                reply = self._extract_reply(new_messages)
                self._save_graph_messages(chat_id, user_id, new_messages)
                self._record_token_usage(chat_id, new_messages)
            else:
                result = await self._graph.ainvoke({"message": message})
                reply = result["response"]
                # Простой граф (без Tools) принимает одно сообщение: история
                # восстанавливается сервисом, ответ сохраняется как есть.
                self._store.append_message(chat_id, user_id, "ai", reply)
        return self._build_reply(chat_id, reply)

    # ------------------------------------------------------------------
    # Внутренние помощники
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_reply(messages: list[object]) -> str:
        """Извлекает текст последнего AI-сообщения."""
        for message in reversed(messages):
            if isinstance(message, AIMessage):
                content = message.content
                reply = content if isinstance(content, str) else str(content)
                return reply.strip() or "Не удалось получить ответ агента."
        return "Не удалось получить ответ агента."

    def _save_graph_messages(self, chat_id: str, user_id: str, messages: list[object]) -> None:
        """Сохраняет новые сообщения графа (ответы, результаты Tools)."""
        for message in messages:
            try:
                self._store.append_message(
                    chat_id,
                    user_id,
                    getattr(message, "type", "ai"),
                    self._message_preview(message),
                    payload=serialize_message(message),  # type: ignore[arg-type]
                )
            except Exception as error:
                logger.warning("Не удалось сохранить сообщение в историю: %s", error)

    def _record_token_usage(self, chat_id: str, messages: list[object]) -> None:
        """Суммирует расход токенов за ход по метаданным AI-сообщений.

        Каждый вызов модели в ходе (ReAct-итерация) приносит usage_metadata;
        итоги сохраняются в SQLite для отчётов по диалогу.
        """
        input_tokens = 0
        output_tokens = 0
        cached_tokens = 0
        for message in messages:
            if not isinstance(message, AIMessage):
                continue
            usage = getattr(message, "usage_metadata", None) or {}
            input_tokens += int(usage.get("input_tokens") or 0)
            output_tokens += int(usage.get("output_tokens") or 0)
            details = usage.get("input_token_details") or {}
            cached_tokens += int(details.get("cache_read") or 0)
        if input_tokens or output_tokens:
            try:
                self._store.record_token_usage(chat_id, input_tokens, output_tokens, cached_tokens)
            except Exception as error:
                logger.warning("Не удалось записать расход токенов: %s", error)

    @staticmethod
    def _message_preview(message: object) -> str:
        """Возвращает человекочитаемый текст сообщения для истории."""
        content = getattr(message, "content", "")
        return content if isinstance(content, str) else str(content)

    def _build_reply(self, chat_id: str, reply: str) -> AgentReply:
        """Собирает ответ с данными активной операции диалога."""
        operation = self._latest_active_operation(chat_id)
        return AgentReply(
            reply=reply,
            operation_id=operation.id if operation else None,
            operation_status=operation.status.value if operation else None,
        )

    def _latest_active_operation(self, chat_id: str) -> Operation | None:
        """Возвращает самую свежую активную операцию диалога.

        Приоритет отдаётся операциям, ожидающим подтверждения, — их
        идентификатор нужен адаптеру для кнопок подтверждения.
        """
        active = self._operation_service.list_active_by_chat(chat_id)
        if not active:
            return None
        awaiting = [op for op in active if op.status == OperationStatus.AWAITING_CONFIRMATION]
        return (awaiting or active)[-1]
