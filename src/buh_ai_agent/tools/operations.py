"""Инструменты операций: регистрация и передача на подтверждение.

Агент оформляет любую задачу создания документов 1С операцией:

1. `create_operation` — регистрирует операцию (статус `processing`) с
   исходным запросом пользователя и контекстом диалога (chat_id,
   user_id, организация и база 1С).
2. `complete_operation` — передаёт операцию на подтверждение
   (`awaiting_confirmation`) с полным составом созданных документов
   (Ref_Key и номера).

Идентификатор диалога берётся из контекста (`DialogContext`), а не из
аргументов LLM — агент не может подделать привязку к чату. Инструмент
проверяет принадлежность операции текущему диалогу: чужой operation_id
вызывает ошибку.

Мультибазность: при нескольких базах 1С агент передаёт `database` — имя
базы из конфигурации; реестр проверяет имя и подставляет организацию
базы. При одной базе аргумент не нужен (используется контекст диалога).
"""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from buh_ai_agent.agent.context import MissingDialogContextError, get_dialog_context
from buh_ai_agent.integrations.onec.registry import OnecClients
from buh_ai_agent.operations import OperationDocument, OperationService
from buh_ai_agent.operations.models import ACTIVE_STATUSES
from buh_ai_agent.tools.base import tool_error, tool_success


def make_operation_tools(
    operation_service: OperationService,
    clients: OnecClients | None = None,
) -> list[BaseTool]:
    """Создаёт инструменты управления операциями.

    Args:
        operation_service: Сервис операций (с общим с приложением хранилищем).
        clients: Реестр подключений к базам 1С (None — 1С не подключена).

    Returns:
        Список LangChain-инструментов.
    """

    @tool
    async def create_operation(summary: str, database: str = "") -> str:
        """Регистрирует новую операцию создания документов 1С.

        Вызывайте в начале любой задачи создания/изменения документов.
        Если в контексте диалога уже есть активная операция, которую
        пользователь продолжает — не создавайте новую: работайте с
        существующим operation_id.

        Args:
            summary: Краткое описание задачи (исходный запрос пользователя).
            database: Имя базы 1С, в которой создаются документы. При
                нескольких базах указывайте базу, выбранную по запросу
                пользователя (неясно — сначала уточните у пользователя,
                не выбирайте базу молча).

        Returns:
            JSON: operation_id и статус операции.
        """
        try:
            context = get_dialog_context()
        except MissingDialogContextError as error:
            return tool_error(f"create_operation: {error}")
        database_id = context.database_id
        organization_id = context.organization_id
        if clients is not None and (database.strip() or not database_id):
            try:
                _, config = clients.resolve(database)
            except Exception as error:
                return tool_error(f"create_operation: {error}")
            database_id = config.database
            organization_id = config.defaults.organization.name
        try:
            operation = operation_service.create(
                summary,
                chat_id=context.chat_id,
                user_id=context.user_id,
                organization_id=organization_id,
                database_id=database_id,
            )
        except Exception as error:
            return tool_error(f"create_operation: {error}")
        return tool_success({"operation_id": operation.id, "status": operation.status.value})

    @tool
    async def complete_operation(
        operation_id: str,
        documents: list[dict[str, str]],
        result: str = "",
    ) -> str:
        """Передаёт операцию на подтверждение пользователю.

        Вызывайте после успешного создания всех документов 1С.
        Документы — обязательный полный актуальный список созданных
        в операции объектов: [{"type": "invoice", "ref_key": "...",
        "number": "..."}] — ref_key и number только из результатов Tools
        (create_sales_invoice и др.). Список заменяет предыдущий: при
        доработке операции передавайте все созданные документы, включая
        ранее созданные.

        Args:
            operation_id: Идентификатор операции (из create_operation).
            documents: Документы 1С (type, ref_key, number) — обязательны.
            result: Краткое описание результата для пользователя.

        Returns:
            JSON: operation_id и новый статус операции.
        """
        try:
            context = get_dialog_context()
        except MissingDialogContextError as error:
            return tool_error(f"complete_operation: {error}")
        operation = operation_service.get(operation_id)
        if operation is None:
            return tool_error(f"complete_operation: операция {operation_id} не найдена.")
        if operation.chat_id != context.chat_id:
            return tool_error(
                f"complete_operation: операция {operation_id} принадлежит другому диалогу."
            )
        if operation.status not in ACTIVE_STATUSES:
            return tool_error(
                f"complete_operation: операция {operation_id} в статусе "
                f"{operation.status}; работайте с активной операцией."
            )
        parsed = _parse_documents(documents)
        if isinstance(parsed, str):
            return tool_error(f"complete_operation: {parsed}")
        if not parsed:
            return tool_error(
                "complete_operation: не переданы документы. Укажите полный список "
                "созданных документов 1С: [{type, ref_key, number}] — ref_key и "
                "number из результатов Tools. Без списка операцию нельзя передать "
                "на подтверждение."
            )
        try:
            updated = operation_service.submit_for_confirmation(
                operation_id,
                chat_id=context.chat_id,
                documents=parsed,
                result={"summary": result} if result else None,
            )
        except Exception as error:
            return tool_error(f"complete_operation: {error}")
        return tool_success({"operation_id": updated.id, "status": updated.status.value})

    return [create_operation, complete_operation]


def _parse_documents(
    documents: list[dict[str, str]] | None,
) -> list[OperationDocument] | str:
    """Разбирает список документов от агента.

    Args:
        documents: Список словарей {type, ref_key, number}.

    Returns:
        Список OperationDocument или строка с описанием ошибки.
    """
    parsed: list[OperationDocument] = []
    for item in documents or []:
        if not isinstance(item, dict):
            return f"некорректный документ: {item!r}; ожидается словарь."
        ref_key = str(item.get("ref_key") or "").strip()
        if not ref_key:
            return "у документа отсутствует ref_key (идентификатор 1С)."
        doc_type = str(item.get("type") or "").strip()
        if not doc_type:
            return f"у документа {ref_key} не указан type."
        parsed.append(
            OperationDocument(
                type=doc_type,
                ref_key=ref_key,
                number=str(item.get("number") or "").strip(),
            )
        )
    return parsed
