"""Юнит-тесты SQLite-хранилища: история, операции, персистентность."""

from pathlib import Path

from langchain_core.messages import HumanMessage

from buh_ai_agent.agent.history import serialize_message
from buh_ai_agent.operations import OperationService, OperationStatus
from buh_ai_agent.operations.models import OperationDocument
from buh_ai_agent.storage import SQLiteStore


def test_append_and_get_recent_messages(tmp_path: Path) -> None:
    """Сообщения сохраняются и читаются в хронологическом порядке."""
    store = SQLiteStore(tmp_path / "test.db")
    store.append_message("chat-1", "user-1", "human", "Привет")
    store.append_message("chat-1", "user-1", "ai", "Здравствуйте!")
    store.append_message("chat-2", "user-2", "human", "Другой чат")

    messages = store.get_recent_messages("chat-1", 10)
    assert [m["content"] for m in messages] == ["Привет", "Здравствуйте!"]
    assert messages[0]["role"] == "human"
    assert messages[0]["chat_id"] == "chat-1"
    assert messages[0]["user_id"] == "user-1"
    store.close()


def test_get_recent_messages_limit(tmp_path: Path) -> None:
    """Лимит возвращает последние N сообщений (старые первыми)."""
    store = SQLiteStore(tmp_path / "test.db")
    for index in range(5):
        store.append_message("chat-1", "user-1", "human", f"Сообщение {index}")
    messages = store.get_recent_messages("chat-1", 3)
    assert [m["content"] for m in messages] == ["Сообщение 2", "Сообщение 3", "Сообщение 4"]
    store.close()


def test_get_recent_messages_zero_limit(tmp_path: Path) -> None:
    """Лимит 0 — история не возвращается."""
    store = SQLiteStore(tmp_path / "test.db")
    store.append_message("chat-1", "user-1", "human", "Привет")
    assert store.get_recent_messages("chat-1", 0) == []
    store.close()


def test_chat_isolation(tmp_path: Path) -> None:
    """История разных чатов не смешивается."""
    store = SQLiteStore(tmp_path / "test.db")
    store.append_message("chat-1", "user-1", "human", "Чат 1")
    store.append_message("chat-2", "user-2", "human", "Чат 2")
    first = store.get_recent_messages("chat-1", 10)
    second = store.get_recent_messages("chat-2", 10)
    assert [m["content"] for m in first] == ["Чат 1"]
    assert [m["content"] for m in second] == ["Чат 2"]
    store.close()


def test_message_payload_roundtrip(tmp_path: Path) -> None:
    """Payload с сериализованным LangChain-сообщением читается."""
    store = SQLiteStore(tmp_path / "test.db")
    payload = serialize_message(HumanMessage(content="Привет"))
    store.append_message("chat-1", "user-1", "human", "Привет", payload=payload)
    messages = store.get_recent_messages("chat-1", 10)
    assert messages[0]["payload"] == payload
    store.close()


def test_operations_persist_between_reopens(tmp_path: Path) -> None:
    """Операции переживают переоткрытие базы (перезапуск приложения)."""
    db_path = tmp_path / "test.db"

    first_store = SQLiteStore(db_path)
    service = OperationService(first_store)
    operation = service.create(
        "Создай счёт", chat_id="chat-1", user_id="user-1", database_id="base-1"
    )
    service.submit_for_confirmation(
        operation.id,
        chat_id="chat-1",
        documents=[OperationDocument(type="invoice", ref_key="ref-1", number="1")],
    )
    first_store.close()

    second_store = SQLiteStore(db_path)
    restored = second_store.get(operation.id)
    assert restored is not None
    assert restored.status == OperationStatus.AWAITING_CONFIRMATION
    assert restored.chat_id == "chat-1"
    assert restored.documents[0].ref_key == "ref-1"
    second_store.close()


def test_operation_idempotency_key_persists(tmp_path: Path) -> None:
    """Идемпотентность работает между перезапусками."""
    db_path = tmp_path / "test.db"

    first_store = SQLiteStore(db_path)
    first = OperationService(first_store).create("x", chat_id="chat-1", idempotency_key="key-1")
    first_store.close()

    second_store = SQLiteStore(db_path)
    second = OperationService(second_store).create("x", chat_id="chat-1", idempotency_key="key-1")
    assert second.id == first.id
    second_store.close()


def test_list_by_chat_and_active(tmp_path: Path) -> None:
    """SQLite-хранилище фильтрует операции по чату и активности."""
    store = SQLiteStore(tmp_path / "test.db")
    service = OperationService(store)
    processing = service.create("x", chat_id="chat-1")
    awaiting = service.create("y", chat_id="chat-1")
    service.submit_for_confirmation(awaiting.id, chat_id="chat-1")
    confirmed = service.create("z", chat_id="chat-1")
    service.submit_for_confirmation(confirmed.id, chat_id="chat-1")
    service.confirm(confirmed.id, chat_id="chat-1")
    other = service.create("w", chat_id="chat-2")

    all_chat = store.list_by_chat("chat-1")
    assert [op.id for op in all_chat] == [processing.id, awaiting.id, confirmed.id]
    active = store.list_active_by_chat("chat-1")
    assert {op.id for op in active} == {processing.id, awaiting.id}
    assert [op.id for op in store.list_by_chat("chat-2")] == [other.id]
    store.close()


def test_message_with_operation_id(tmp_path: Path) -> None:
    """История сообщений связывается с операцией."""
    store = SQLiteStore(tmp_path / "test.db")
    store.append_message("chat-1", "user-1", "event", "Операция подтверждена", operation_id="op-1")
    messages = store.get_recent_messages("chat-1", 10)
    assert messages[0]["operation_id"] == "op-1"
    store.close()
