"""Интеграционные тесты HTTP API."""

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from tests.fake_models import FakeToolChatModel, fake_tool_llm

from buh_ai_agent.agent.service import AgentService
from buh_ai_agent.app import create_app


@pytest.fixture(autouse=True)
def _fake_llm_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подменяет фабрику LLM фейковой моделью для всех интеграционных тестов.

    Реальный ChatOpenAI требует учётных данных и сетевого доступа,
    поэтому в тестах используется FakeToolChatModel (поддерживает bind_tools).
    """
    monkeypatch.setattr(
        "buh_ai_agent.app.create_llm",
        lambda _settings: fake_tool_llm(AIMessage(content="Тестовый ответ модели.")),
    )


def test_health_returns_ok() -> None:
    """GET /health возвращает 200 и статус ok."""
    with TestClient(create_app()) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_chat_returns_reply_from_llm() -> None:
    """POST /chat возвращает 200 и ответ, полученный от модели."""
    with TestClient(create_app()) as client:
        response = client.post(
            "/chat",
            json={"chat_id": "chat-1", "user_id": "user-1", "message": "Привет, что ты умеешь?"},
        )
        assert response.status_code == 200
        assert response.json() == {
            "reply": "Тестовый ответ модели.",
            "operation_id": None,
            "operation_status": None,
            "files": [],
        }


def test_llm_created_once_per_app_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM и граф создаются один раз при старте и переиспользуются запросами."""
    calls: list[object] = []

    def counting_create_llm(settings: object) -> FakeToolChatModel:
        calls.append(settings)
        return fake_tool_llm(AIMessage(content="Ответ 1"), AIMessage(content="Ответ 2"))

    monkeypatch.setattr("buh_ai_agent.app.create_llm", counting_create_llm)
    app = create_app()
    with TestClient(app) as client:
        service_before = app.state.agent_service
        first = client.post(
            "/chat",
            json={"chat_id": "chat-1", "user_id": "user-1", "message": "Первое"},
        )
        second = client.post(
            "/chat",
            json={"chat_id": "chat-1", "user_id": "user-1", "message": "Второе"},
        )
        service_after = app.state.agent_service
        assert len(calls) == 1
        assert service_before is service_after
        assert first.json() == {
            "reply": "Ответ 1",
            "operation_id": None,
            "operation_status": None,
            "files": [],
        }
        assert second.json() == {
            "reply": "Ответ 2",
            "operation_id": None,
            "operation_status": None,
            "files": [],
        }


def test_chat_context_persists_between_messages() -> None:
    """История диалога сохраняется между сообщениями (SQLite)."""
    app = create_app()
    with TestClient(app) as client:
        client.post(
            "/chat",
            json={"chat_id": "chat-1", "user_id": "user-1", "message": "Первое"},
        )
        client.post(
            "/chat",
            json={"chat_id": "chat-1", "user_id": "user-1", "message": "Второе"},
        )
        rows = app.state.storage.get_recent_messages("chat-1", 100)
        assert [row["role"] for row in rows] == ["human", "ai", "human", "ai"]


def test_chat_context_isolated_between_chats() -> None:
    """Разные чаты не смешивают контекст."""
    app = create_app()
    with TestClient(app) as client:
        client.post(
            "/chat",
            json={"chat_id": "chat-1", "user_id": "user-1", "message": "Сообщение 1"},
        )
        client.post(
            "/chat",
            json={"chat_id": "chat-2", "user_id": "user-2", "message": "Сообщение 2"},
        )
        storage = app.state.storage
        assert len(storage.get_recent_messages("chat-1", 100)) == 2
        assert len(storage.get_recent_messages("chat-2", 100)) == 2


def test_lifespan_initializes_agent_service() -> None:
    """При старте приложения создаётся сервис агента с готовым графом."""
    app = create_app()
    with TestClient(app):
        assert isinstance(app.state.agent_service, AgentService)
        assert app.state.operation_service is not None
        assert app.state.storage is not None


def test_chat_rejects_empty_message() -> None:
    """POST /chat с пустым сообщением возвращает 422."""
    with TestClient(create_app()) as client:
        response = client.post(
            "/chat",
            json={"chat_id": "chat-1", "user_id": "user-1", "message": ""},
        )
        assert response.status_code == 422


def test_chat_rejects_missing_message() -> None:
    """POST /chat без поля message возвращает 422."""
    with TestClient(create_app()) as client:
        response = client.post("/chat", json={"chat_id": "chat-1", "user_id": "user-1"})
        assert response.status_code == 422


def test_chat_rejects_missing_chat_id() -> None:
    """POST /chat без chat_id возвращает 422."""
    with TestClient(create_app()) as client:
        response = client.post("/chat", json={"user_id": "user-1", "message": "Привет"})
        assert response.status_code == 422


def test_chat_rejects_non_string_message() -> None:
    """POST /chat с нестроковым message возвращает 422."""
    with TestClient(create_app()) as client:
        response = client.post(
            "/chat",
            json={"chat_id": "chat-1", "user_id": "user-1", "message": 123},
        )
        assert response.status_code == 422


# ------------------------------------------------------------------
# Полный цикл: операция через Tools и подтверждение через API
# ------------------------------------------------------------------


def test_operation_full_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Агент создаёт операцию и передаёт её на подтверждение; пользователь подтверждает."""
    import json

    from langchain_core.messages import AIMessage, ToolMessage

    class FlowChatModel(FakeToolChatModel):
        """FakeToolChatModel, подставляющий operation_id из результатов Tools."""

        def _generate(self, messages: list, *args: object, **kwargs: object):
            result = super()._generate(messages, *args, **kwargs)
            message = result.generations[0].message
            if getattr(message, "tool_calls", None):
                for call in message.tool_calls:
                    if (
                        call["name"] == "complete_operation"
                        and call["args"].get("operation_id") == "PLACEHOLDER"
                    ):
                        for item in reversed(messages):
                            if isinstance(item, ToolMessage):
                                data = json.loads(item.content).get("data") or {}
                                if "operation_id" in data:
                                    call["args"]["operation_id"] = data["operation_id"]
                                    break
            return result

    responses = [
        # Агент регистрирует операцию
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "create_operation",
                    "args": {"summary": "Создай счёт на блок питания"},
                    "id": "c1",
                }
            ],
        ),
        # Агент передаёт документы на подтверждение
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "complete_operation",
                    "args": {
                        "operation_id": "PLACEHOLDER",
                        "documents": [{"type": "invoice", "ref_key": "ref-1", "number": "1"}],
                        "result": "Счёт создан",
                    },
                    "id": "c2",
                }
            ],
        ),
        AIMessage(content="Счёт создан, ожидает подтверждения."),
        AIMessage(content="Счёт создан, ожидает подтверждения."),
        AIMessage(content="Счёт создан, ожидает подтверждения."),
    ]

    monkeypatch.setattr(
        "buh_ai_agent.app.create_llm", lambda _settings: FlowChatModel(responses=list(responses))
    )
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={
                "chat_id": "chat-1",
                "user_id": "user-1",
                "message": "Создай счёт на блок питания",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["operation_status"] == "awaiting_confirmation"
        operation_id = body["operation_id"]
        assert operation_id is not None

        # Операция содержит созданный документ с Ref_Key и номером
        operation = app.state.operation_service.get(operation_id)
        assert operation is not None
        assert operation.status == "awaiting_confirmation"
        assert operation.documents[0].ref_key == "ref-1"
        assert operation.documents[0].number == "1"

        # История содержит вызовы Tools (create_operation, complete_operation)
        rows = app.state.storage.get_recent_messages("chat-1", 100)
        assert any(row["role"] == "tool" for row in rows)

        # Пользователь подтверждает операцию
        confirm = client.post(
            f"/operations/{operation_id}/confirm",
            json={"chat_id": "chat-1"},
        )
        assert confirm.status_code == 200
        assert confirm.json()["status"] == "confirmed"

        # Повторное подтверждение запрещено
        repeated = client.post(
            f"/operations/{operation_id}/confirm",
            json={"chat_id": "chat-1"},
        )
        assert repeated.status_code == 409


def test_operation_visible_in_next_message_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Активная операция передаётся в контекст следующего сообщения диалога."""
    from langchain_core.messages import AIMessage

    monkeypatch.setattr(
        "buh_ai_agent.app.create_llm",
        lambda _settings: fake_tool_llm(AIMessage(content="Готов помочь с операцией.")),
    )
    app = create_app()
    with TestClient(app) as client:
        service = app.state.operation_service
        operation = service.create("Создай счёт", chat_id="chat-1", user_id="user-1")
        service.submit_for_confirmation(operation.id, chat_id="chat-1")

        response = client.post(
            "/chat",
            json={"chat_id": "chat-1", "user_id": "user-1", "message": "Добавь кабель"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["operation_id"] == operation.id
        assert body["operation_status"] == "awaiting_confirmation"


# ------------------------------------------------------------------
# Подтверждение и отклонение операций
# ------------------------------------------------------------------


@pytest.fixture()
def awaiting_operation_id(monkeypatch: pytest.MonkeyPatch) -> str:
    """Создаёт операцию в статусе awaiting_confirmation для чата chat-1."""
    app = create_app()
    with TestClient(app):
        service = app.state.operation_service
        operation = service.create(
            "Создай счёт для МТИ Стройсервис", chat_id="chat-1", user_id="user-1"
        )
        service.submit_for_confirmation(operation.id, chat_id="chat-1")
        return operation.id


def test_confirm_operation(monkeypatch: pytest.MonkeyPatch, awaiting_operation_id: str) -> None:
    """POST /operations/{id}/confirm переводит операцию в confirmed."""
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            f"/operations/{awaiting_operation_id}/confirm",
            json={"chat_id": "chat-1"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["operation_id"] == awaiting_operation_id
        assert body["status"] == "confirmed"


def test_confirm_operation_twice_rejected(
    monkeypatch: pytest.MonkeyPatch, awaiting_operation_id: str
) -> None:
    """Повторное подтверждение возвращает 409."""
    app = create_app()
    with TestClient(app) as client:
        client.post(
            f"/operations/{awaiting_operation_id}/confirm",
            json={"chat_id": "chat-1"},
        )
        response = client.post(
            f"/operations/{awaiting_operation_id}/confirm",
            json={"chat_id": "chat-1"},
        )
        assert response.status_code == 409


def test_reject_operation(monkeypatch: pytest.MonkeyPatch, awaiting_operation_id: str) -> None:
    """POST /operations/{id}/reject переводит операцию в rejected."""
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            f"/operations/{awaiting_operation_id}/reject",
            json={"chat_id": "chat-1"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "rejected"


def test_reject_twice_rejected(monkeypatch: pytest.MonkeyPatch, awaiting_operation_id: str) -> None:
    """Повторное отклонение возвращает 409."""
    app = create_app()
    with TestClient(app) as client:
        client.post(
            f"/operations/{awaiting_operation_id}/reject",
            json={"chat_id": "chat-1"},
        )
        response = client.post(
            f"/operations/{awaiting_operation_id}/reject",
            json={"chat_id": "chat-1"},
        )
        assert response.status_code == 409


def test_confirm_operation_from_other_chat_forbidden(
    monkeypatch: pytest.MonkeyPatch, awaiting_operation_id: str
) -> None:
    """Подтверждение операции из чужого чата возвращает 403."""
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            f"/operations/{awaiting_operation_id}/confirm",
            json={"chat_id": "chat-99"},
        )
        assert response.status_code == 403


def test_confirm_missing_operation_not_found() -> None:
    """Подтверждение несуществующей операции возвращает 404."""
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/operations/no-such-id/confirm",
            json={"chat_id": "chat-1"},
        )
        assert response.status_code == 404


def test_confirm_event_saved_to_history(
    monkeypatch: pytest.MonkeyPatch, awaiting_operation_id: str
) -> None:
    """Подтверждение записывает событие в историю диалога."""
    app = create_app()
    with TestClient(app) as client:
        client.post(
            f"/operations/{awaiting_operation_id}/confirm",
            json={"chat_id": "chat-1"},
        )
        rows = app.state.storage.get_recent_messages("chat-1", 100)
        assert any(row["role"] == "event" and "подтверждена" in row["content"] for row in rows)


def test_data_persists_across_app_restarts() -> None:
    """История и операции переживают перезапуск приложения."""
    operation_id: str | None = None
    with TestClient(create_app()) as client:
        client.post(
            "/chat",
            json={"chat_id": "chat-1", "user_id": "user-1", "message": "Привет"},
        )
        operation = client.app.state.operation_service.create(
            "Создай счёт", chat_id="chat-1", user_id="user-1"
        )
        operation_id = operation.id

    # «Перезапуск»: новое приложение на той же базе.
    with TestClient(create_app()) as client:
        client.post(
            "/chat",
            json={"chat_id": "chat-1", "user_id": "user-1", "message": "Продолжаем"},
        )
        app = client.app
        rows = app.state.storage.get_recent_messages("chat-1", 100)
        assert [row["role"] for row in rows] == ["human", "ai", "human", "ai"]
        restored = app.state.operation_service.get(operation_id)
        assert restored is not None
        assert restored.request == "Создай счёт"
