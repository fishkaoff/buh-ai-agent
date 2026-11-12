"""Юнит-тесты инструментов операций (create_operation, complete_operation)."""

import json

import pytest

from buh_ai_agent.agent.context import DialogContext, bind_dialog_context
from buh_ai_agent.integrations.onec.client import OnecClient
from buh_ai_agent.integrations.onec.config import (
    OnecConnectionConfig,
    OnecDefaults,
    OnecOrganizationDefaults,
    OnecSafety,
)
from buh_ai_agent.integrations.onec.registry import OnecClients
from buh_ai_agent.operations import OperationService, OperationStatus
from buh_ai_agent.storage.sqlite import SQLiteStore
from buh_ai_agent.tools.operations import make_operation_tools


def make_base_config(name: str, organization: str) -> OnecConnectionConfig:
    """Конфигурация тестовой базы 1С (клиенты не выполняют запросов)."""
    return OnecConnectionConfig(
        database=name,
        base_url=f"http://onec.test/{name}/",
        username="user",
        password="test",
        defaults=OnecDefaults(organization=OnecOrganizationDefaults(name=organization)),
        safety=OnecSafety(),
    )


@pytest.fixture()
def two_bases() -> OnecClients:
    """Реестр с двумя тестовыми базами (клиенты без реальных запросов)."""
    configs = [
        make_base_config("osnovnaya", "ИП Агентов"),
        make_base_config("filial", "ООО Ромашка"),
    ]
    clients = {
        config.database: OnecClient(config.base_url, config.username, config.password)
        for config in configs
    }
    return OnecClients(configs, clients)


@pytest.fixture()
def service() -> OperationService:
    """Сервис операций с in-memory SQLite."""
    return OperationService(SQLiteStore(":memory:"))


@pytest.fixture()
def tools(service: OperationService) -> list:
    """Инструменты операций."""
    return make_operation_tools(service)


@pytest.fixture()
def context() -> DialogContext:
    """Контекст диалога."""
    return DialogContext(
        chat_id="chat-1", user_id="user-1", organization_id="ООО", database_id="base-1"
    )


async def test_create_operation_uses_dialog_context(
    tools: list, service: OperationService, context: DialogContext
) -> None:
    """create_operation берёт chat_id/user_id из контекста, а не из LLM."""
    with bind_dialog_context(context):
        result = json.loads(await tools[0].ainvoke({"summary": "Создай счёт на 20000"}))
    assert result["ok"] is True
    assert result["data"]["status"] == OperationStatus.PROCESSING.value
    operation = service.list_by_chat("chat-1")[0]
    assert operation.chat_id == "chat-1"
    assert operation.user_id == "user-1"
    assert operation.organization_id == "ООО"
    assert operation.database_id == "base-1"
    assert operation.request == "Создай счёт на 20000"


async def test_create_operation_without_context(tools: list) -> None:
    """Без контекста диалога create_operation возвращает ошибку."""
    result = json.loads(await tools[0].ainvoke({"summary": "Создай счёт"}))
    assert result["ok"] is False
    assert "контекст" in result["error"]


async def test_complete_operation_transfers_to_confirmation(
    tools: list, service: OperationService, context: DialogContext
) -> None:
    """complete_operation переводит операцию в awaiting_confirmation с документами."""
    with bind_dialog_context(context):
        created = json.loads(await tools[0].ainvoke({"summary": "Создай счёт"}))
        operation_id = created["data"]["operation_id"]
        completed = json.loads(
            await tools[1].ainvoke(
                {
                    "operation_id": operation_id,
                    "documents": [
                        {"type": "contract", "ref_key": "ref-1", "number": "1"},
                        {"type": "invoice", "ref_key": "ref-2", "number": "2"},
                    ],
                    "result": "Договор и счёт созданы",
                }
            )
        )
    assert completed["ok"] is True
    assert completed["data"]["status"] == OperationStatus.AWAITING_CONFIRMATION.value
    operation = service.get(operation_id)
    assert operation is not None
    assert operation.status == OperationStatus.AWAITING_CONFIRMATION
    assert len(operation.documents) == 2
    assert operation.documents[0].number == "1"
    assert operation.result == {"summary": "Договор и счёт созданы"}


async def test_complete_operation_foreign_operation_rejected(
    service: OperationService, context: DialogContext
) -> None:
    """complete_operation отказывает для операции чужого диалога."""
    other_operation = service.create("Чужая операция", chat_id="chat-99")
    tools = make_operation_tools(service)
    with bind_dialog_context(context):
        result = json.loads(
            await tools[1].ainvoke({"operation_id": other_operation.id, "documents": []})
        )
    assert result["ok"] is False
    assert "другому диалогу" in result["error"]


async def test_complete_operation_missing_operation(tools: list, context: DialogContext) -> None:
    """complete_operation для несуществующей операции — ошибка."""
    with bind_dialog_context(context):
        result = json.loads(await tools[1].ainvoke({"operation_id": "no-such-id", "documents": []}))
    assert result["ok"] is False
    assert "не найдена" in result["error"]


async def test_complete_operation_after_reject_rejected(
    tools: list, service: OperationService, context: DialogContext
) -> None:
    """complete_operation не работает с завершённой операцией."""
    with bind_dialog_context(context):
        created = json.loads(await tools[0].ainvoke({"summary": "Создай счёт"}))
        operation_id = created["data"]["operation_id"]
        await tools[1].ainvoke(
            {
                "operation_id": operation_id,
                "documents": [{"type": "invoice", "ref_key": "ref-1", "number": "1"}],
            }
        )
        service.reject(operation_id, chat_id="chat-1")
        result = json.loads(await tools[1].ainvoke({"operation_id": operation_id, "documents": []}))
    assert result["ok"] is False
    assert "статусе" in result["error"]


async def test_complete_operation_document_without_ref_key(
    tools: list, service: OperationService, context: DialogContext
) -> None:
    """Документ без ref_key отклоняется с понятной ошибкой."""
    with bind_dialog_context(context):
        created = json.loads(await tools[0].ainvoke({"summary": "Создай счёт"}))
        operation_id = created["data"]["operation_id"]
        result = json.loads(
            await tools[1].ainvoke(
                {"operation_id": operation_id, "documents": [{"type": "invoice", "number": "1"}]}
            )
        )
    assert result["ok"] is False
    assert "ref_key" in result["error"]


async def test_complete_operation_without_documents_rejected(
    tools: list, service: OperationService, context: DialogContext
) -> None:
    """complete_operation без списка документов отклоняется с инструкцией."""
    with bind_dialog_context(context):
        created = json.loads(await tools[0].ainvoke({"summary": "Создай счёт"}))
        operation_id = created["data"]["operation_id"]
        result = json.loads(await tools[1].ainvoke({"operation_id": operation_id, "documents": []}))
    assert result["ok"] is False
    assert "не переданы документы" in result["error"]
    # Операция осталась в processing — подтверждение не наступило.
    operation = service.get(operation_id)
    assert operation is not None
    assert operation.status == OperationStatus.PROCESSING


# ------------------------------------------------------------------
# create_operation: выбор базы 1С (мультибазность)
# ------------------------------------------------------------------


async def test_create_operation_with_explicit_database(
    service: OperationService, context: DialogContext, two_bases: OnecClients
) -> None:
    """Явно указанная база записывается в операцию с организацией этой базы."""
    tools = make_operation_tools(service, clients=two_bases)
    with bind_dialog_context(context):
        result = json.loads(
            await tools[0].ainvoke({"summary": "Создай счёт", "database": "filial"})
        )
    assert result["ok"] is True
    operation = service.list_by_chat("chat-1")[0]
    assert operation.database_id == "filial"
    assert operation.organization_id == "ООО Ромашка"


async def test_create_operation_without_database_multiple_bases_asks(
    service: OperationService, two_bases: OnecClients
) -> None:
    """При нескольких базах без database — ошибка со списком баз."""
    empty_context = DialogContext(chat_id="chat-1", user_id="user-1")
    tools = make_operation_tools(service, clients=two_bases)
    with bind_dialog_context(empty_context):
        result = json.loads(await tools[0].ainvoke({"summary": "Создай счёт"}))
    assert result["ok"] is False
    assert "уточните у пользователя" in result["error"]
    assert "osnovnaya" in result["error"]
    assert "filial" in result["error"]


async def test_create_operation_unknown_database_rejected(
    service: OperationService, context: DialogContext, two_bases: OnecClients
) -> None:
    """Неизвестное имя базы — ошибка, операция не создаётся."""
    tools = make_operation_tools(service, clients=two_bases)
    with bind_dialog_context(context):
        result = json.loads(
            await tools[0].ainvoke({"summary": "Создай счёт", "database": "no-such"})
        )
    assert result["ok"] is False
    assert "не найдена" in result["error"]
    assert not service.list_by_chat("chat-1")


async def test_create_operation_unknown_base_context_used_without_clients(
    tools: list, service: OperationService, context: DialogContext
) -> None:
    """Без реестра баз (1С не подключена) используется контекст диалога как раньше."""
    with bind_dialog_context(context):
        result = json.loads(await tools[0].ainvoke({"summary": "Создай счёт"}))
    assert result["ok"] is True
    operation = service.list_by_chat("chat-1")[0]
    assert operation.database_id == "base-1"
