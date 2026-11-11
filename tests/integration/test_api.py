"""Интеграционные тесты HTTP API."""

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from buh_ai_agent.agent.service import AgentService
from buh_ai_agent.app import create_app


@pytest.fixture(autouse=True)
def _fake_llm_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подменяет фабрику LLM фейковой моделью для всех интеграционных тестов.

    Реальный ChatOpenAI требует учётных данных и сетевого доступа,
    поэтому в тестах используется FakeListChatModel.
    """
    monkeypatch.setattr(
        "buh_ai_agent.app.create_llm",
        lambda _settings: FakeListChatModel(responses=["Тестовый ответ модели."]),
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
        response = client.post("/chat", json={"message": "Привет, что ты умеешь?"})
        assert response.status_code == 200
        assert response.json() == {"reply": "Тестовый ответ модели."}


def test_llm_created_once_per_app_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM и граф создаются один раз при старте и переиспользуются запросами."""
    calls: list[object] = []

    def counting_create_llm(settings: object) -> FakeListChatModel:
        calls.append(settings)
        return FakeListChatModel(responses=["Ответ 1", "Ответ 2"])

    monkeypatch.setattr("buh_ai_agent.app.create_llm", counting_create_llm)
    app = create_app()
    with TestClient(app) as client:
        service_before = app.state.agent_service
        first = client.post("/chat", json={"message": "Первое"})
        second = client.post("/chat", json={"message": "Второе"})
        service_after = app.state.agent_service
        assert len(calls) == 1
        assert service_before is service_after
        assert first.json() == {"reply": "Ответ 1"}
        assert second.json() == {"reply": "Ответ 2"}


def test_lifespan_initializes_agent_service() -> None:
    """При старте приложения создаётся сервис агента с готовым графом."""
    app = create_app()
    with TestClient(app):
        assert isinstance(app.state.agent_service, AgentService)


def test_chat_rejects_empty_message() -> None:
    """POST /chat с пустым сообщением возвращает 422."""
    with TestClient(create_app()) as client:
        response = client.post("/chat", json={"message": ""})
        assert response.status_code == 422


def test_chat_rejects_missing_message() -> None:
    """POST /chat без поля message возвращает 422."""
    with TestClient(create_app()) as client:
        response = client.post("/chat", json={})
        assert response.status_code == 422


def test_chat_rejects_non_string_message() -> None:
    """POST /chat с нестроковым message возвращает 422."""
    with TestClient(create_app()) as client:
        response = client.post("/chat", json={"message": 123})
        assert response.status_code == 422
