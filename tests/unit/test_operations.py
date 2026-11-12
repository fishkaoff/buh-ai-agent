"""Юнит-тесты операций: хранилище, идемпотентность, подтверждение."""

import pytest

from buh_ai_agent.operations import (
    InMemoryOperationStore,
    Operation,
    OperationDocument,
    OperationError,
    OperationService,
    OperationStatus,
)


def make_service() -> OperationService:
    """Сервис с in-memory хранилищем."""
    return OperationService(InMemoryOperationStore())


# ------------------------------------------------------------------
# InMemoryOperationStore
# ------------------------------------------------------------------


def test_store_save_and_get() -> None:
    """Сохранение и чтение по идентификатору."""
    store = InMemoryOperationStore()
    operation = make_service().create("Создай счёт", chat_id="chat-1", user_id="user-1")
    store.save(operation)
    assert store.get(operation.id) is not None


def test_store_get_missing_returns_none() -> None:
    """Несуществующая операция — None."""
    store = InMemoryOperationStore()
    assert store.get("no-such-id") is None


def test_store_get_by_idempotency_key() -> None:
    """Поиск по ключу идемпотентности."""
    store = InMemoryOperationStore()
    operation = make_service().create("x", chat_id="c", idempotency_key="abc")
    store.save(operation)
    found = store.get_by_idempotency_key("abc")
    assert found is not None
    assert found.id == operation.id


def test_store_get_by_idempotency_key_missing() -> None:
    """Нет ключа — None."""
    store = InMemoryOperationStore()
    assert store.get_by_idempotency_key("no-such-key") is None


def test_store_list_operations() -> None:
    """Список операций."""
    store = InMemoryOperationStore()
    service = make_service()
    operation = service.create("x", chat_id="c")
    store.save(operation)
    operations = store.list_operations()
    assert len(operations) == 1
    assert operations[0].id == operation.id


def test_store_list_by_chat() -> None:
    """Операции возвращаются по диалогу, старые первыми."""
    store = InMemoryOperationStore()
    service = OperationService(store)
    first = service.create("x", chat_id="chat-1")
    service.create("y", chat_id="chat-2")
    second = service.create("z", chat_id="chat-1")
    chat_operations = store.list_by_chat("chat-1")
    assert [op.id for op in chat_operations] == [first.id, second.id]
    assert len(store.list_by_chat("chat-2")) == 1


def test_store_list_active_by_chat() -> None:
    """Активные операции: processing и awaiting_confirmation."""
    service = make_service()
    active = service.create("x", chat_id="chat-1")
    awaiting = service.create("y", chat_id="chat-1")
    service.submit_for_confirmation(awaiting.id, chat_id="chat-1")
    confirmed = service.create("z", chat_id="chat-1")
    service.submit_for_confirmation(confirmed.id, chat_id="chat-1")
    service.confirm(confirmed.id, chat_id="chat-1")
    rejected = service.create("w", chat_id="chat-1")
    service.submit_for_confirmation(rejected.id, chat_id="chat-1")
    service.reject(rejected.id, chat_id="chat-1")

    active_ids = [op.id for op in service.list_active_by_chat("chat-1")]
    assert active_ids == [active.id, awaiting.id]


# ------------------------------------------------------------------
# OperationService: создание и идемпотентность
# ------------------------------------------------------------------


def test_create_operation() -> None:
    """Создание операции в статусе processing с привязкой к диалогу."""
    service = make_service()
    operation = service.create(
        "Создай счёт для ООО Ромашка",
        chat_id="chat-1",
        user_id="user-1",
        organization_id="ООО Ромашка",
        database_id="base-1",
    )
    assert operation.status == OperationStatus.PROCESSING
    assert operation.chat_id == "chat-1"
    assert operation.user_id == "user-1"
    assert operation.organization_id == "ООО Ромашка"
    assert operation.database_id == "base-1"
    assert operation.request == "Создай счёт для ООО Ромашка"
    assert operation.documents == []
    assert operation.created_at
    assert operation.updated_at
    assert operation.result is None
    assert operation.error is None


def test_create_idempotency_key_returns_existing() -> None:
    """Повторное создание с тем же ключом возвращает существующую операцию."""
    service = make_service()
    first = service.create("x", chat_id="c", idempotency_key="key-1")
    second = service.create("x", chat_id="c", idempotency_key="key-1")
    assert first.id == second.id


def test_create_idempotency_key_missing() -> None:
    """Создание без ключа — каждый раз новая операция."""
    service = make_service()
    first = service.create("x", chat_id="c")
    second = service.create("x", chat_id="c")
    assert first.id != second.id


# ------------------------------------------------------------------
# OperationService: переходы статусов
# ------------------------------------------------------------------


def test_submit_for_confirmation() -> None:
    """processing → awaiting_confirmation с документами."""
    service = make_service()
    operation = service.create("x", chat_id="chat-1")
    operation = service.submit_for_confirmation(
        operation.id,
        chat_id="chat-1",
        documents=[OperationDocument(type="invoice", ref_key="ref-1", number="1")],
        result={"summary": "Счёт создан"},
    )
    assert operation.status == OperationStatus.AWAITING_CONFIRMATION
    assert operation.documents[0].ref_key == "ref-1"
    assert operation.result == {"summary": "Счёт создан"}


def test_submit_for_confirmation_repeats_allowed() -> None:
    """Повторная передача допустима при доработке операции."""
    service = make_service()
    operation = service.create("x", chat_id="chat-1")
    service.submit_for_confirmation(operation.id, chat_id="chat-1")
    operation = service.submit_for_confirmation(
        operation.id,
        chat_id="chat-1",
        documents=[OperationDocument(type="invoice", ref_key="ref-1")],
    )
    assert operation.status == OperationStatus.AWAITING_CONFIRMATION
    assert len(operation.documents) == 1


def test_submit_for_confirmation_missing() -> None:
    """Несуществующая операция — OperationError."""
    service = make_service()
    with pytest.raises(OperationError, match="не найдена"):
        service.submit_for_confirmation("no-such-id", chat_id="chat-1")


def test_submit_for_confirmation_foreign_chat() -> None:
    """Передача на подтверждение из чужого диалога запрещена."""
    service = make_service()
    operation = service.create("x", chat_id="chat-1")
    with pytest.raises(OperationError, match="другому диалогу"):
        service.submit_for_confirmation(operation.id, chat_id="chat-2")


def test_reject() -> None:
    """awaiting_confirmation → rejected."""
    service = make_service()
    operation = service.create("x", chat_id="chat-1")
    service.submit_for_confirmation(operation.id, chat_id="chat-1")
    operation = service.reject(operation.id, chat_id="chat-1")
    assert operation.status == OperationStatus.REJECTED


def test_reject_from_processing_not_allowed() -> None:
    """Отклонение из processing запрещено."""
    service = make_service()
    operation = service.create("x", chat_id="chat-1")
    with pytest.raises(OperationError, match="awaiting_confirmation"):
        service.reject(operation.id, chat_id="chat-1")


def test_reject_from_rejected_not_allowed() -> None:
    """Повторное отклонение запрещено."""
    service = make_service()
    operation = service.create("x", chat_id="chat-1")
    service.submit_for_confirmation(operation.id, chat_id="chat-1")
    service.reject(operation.id, chat_id="chat-1")
    with pytest.raises(OperationError, match="awaiting_confirmation"):
        service.reject(operation.id, chat_id="chat-1")


def test_reject_foreign_chat_not_allowed() -> None:
    """Отклонение из чужого диалога запрещено."""
    service = make_service()
    operation = service.create("x", chat_id="chat-1")
    service.submit_for_confirmation(operation.id, chat_id="chat-1")
    with pytest.raises(OperationError, match="другому диалогу"):
        service.reject(operation.id, chat_id="chat-2")


# ------------------------------------------------------------------
# OperationService: подтверждение
# ------------------------------------------------------------------


def test_confirm_transfers_status() -> None:
    """Подтверждение переводит операцию в confirmed."""
    service = make_service()
    operation = service.create("x", chat_id="chat-1")
    service.submit_for_confirmation(operation.id, chat_id="chat-1")
    operation = service.confirm(operation.id, chat_id="chat-1")
    assert operation.status == OperationStatus.CONFIRMED


def test_confirm_twice_not_allowed() -> None:
    """Повторное подтверждение запрещено."""
    service = make_service()
    operation = service.create("x", chat_id="chat-1")
    service.submit_for_confirmation(operation.id, chat_id="chat-1")
    service.confirm(operation.id, chat_id="chat-1")
    with pytest.raises(OperationError, match="awaiting_confirmation"):
        service.confirm(operation.id, chat_id="chat-1")


def test_confirm_from_processing_not_allowed() -> None:
    """Подтверждение из processing запрещено."""
    service = make_service()
    operation = service.create("x", chat_id="chat-1")
    with pytest.raises(OperationError, match="awaiting_confirmation"):
        service.confirm(operation.id, chat_id="chat-1")


def test_confirm_rejected_not_allowed() -> None:
    """Отклонённая операция не может быть подтверждена."""
    service = make_service()
    operation = service.create("x", chat_id="chat-1")
    service.submit_for_confirmation(operation.id, chat_id="chat-1")
    service.reject(operation.id, chat_id="chat-1")
    with pytest.raises(OperationError, match="awaiting_confirmation"):
        service.confirm(operation.id, chat_id="chat-1")


def test_confirm_foreign_chat_not_allowed() -> None:
    """Подтверждение из чужого диалога запрещено."""
    service = make_service()
    operation = service.create("x", chat_id="chat-1")
    service.submit_for_confirmation(operation.id, chat_id="chat-1")
    with pytest.raises(OperationError, match="другому диалогу"):
        service.confirm(operation.id, chat_id="chat-2")


def test_confirm_missing_operation() -> None:
    """Несуществующая операция — OperationError."""
    service = make_service()
    with pytest.raises(OperationError, match="не найдена"):
        service.confirm("no-such-id", chat_id="chat-1")


# ------------------------------------------------------------------
# OperationService: чтение и список
# ------------------------------------------------------------------


def test_get_missing_returns_none() -> None:
    """Несуществующая операция — None."""
    service = make_service()
    assert service.get("no-such-id") is None


def test_list_operations() -> None:
    """Список операций."""
    service = make_service()
    service.create("a", chat_id="c1")
    service.create("b", chat_id="c2")
    assert len(service.list_operations()) == 2


def test_mark_failed() -> None:
    """mark_failed переводит активную операцию в failed."""
    service = make_service()
    operation = service.create("x", chat_id="chat-1")
    service.mark_failed(operation.id, "Ошибка 1С")
    stored = service.get(operation.id)
    assert stored is not None
    assert stored.status == OperationStatus.FAILED
    assert stored.error == "Ошибка 1С"


def test_mark_failed_missing_returns_none() -> None:
    """mark_failed для несуществующей операции — None."""
    service = make_service()
    assert service.mark_failed("no-such-id", "ошибка") is None


def test_operation_to_dict_roundtrip() -> None:
    """Сериализация/десериализация операции."""
    service = make_service()
    operation = service.create("x", chat_id="chat-1", idempotency_key="key-1")
    restored = Operation.from_dict(operation.to_dict())
    assert restored.id == operation.id
    assert restored.status == operation.status
    assert restored.chat_id == operation.chat_id
    assert restored.request == operation.request
    assert restored.idempotency_key == operation.idempotency_key
