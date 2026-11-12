"""Юнит-тесты FastAPI-приложения."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from tests.fake_models import fake_tool_llm

from buh_ai_agent.app import create_app
from buh_ai_agent.operations import OperationService
from buh_ai_agent.storage import SQLiteStore


def test_create_app_returns_fastapi_instance() -> None:
    """Приложение создаётся и имеет правильный тип."""
    app = create_app()
    assert isinstance(app, FastAPI)


def test_app_has_expected_routes() -> None:
    """Приложение регистрирует маршруты /health, /chat и операции."""
    app = create_app()
    paths = set(app.openapi()["paths"])
    assert "/health" in paths
    assert "/chat" in paths
    assert "/operations/{operation_id}/confirm" in paths
    assert "/operations/{operation_id}/reject" in paths


def test_app_title_and_version() -> None:
    """Приложение использует настройки и версию из пакета."""
    app = create_app()
    assert app.title == "buh-ai-agent"
    assert app.version == "0.1.0"


def test_lifespan_creates_operation_store_and_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lifespan создаёт SQLite-хранилище и сервис операций."""
    monkeypatch.setattr(
        "buh_ai_agent.app.create_llm",
        lambda _settings: fake_tool_llm(AIMessage(content="Тестовый ответ.")),
    )
    app = create_app()
    with TestClient(app):
        assert isinstance(app.state.operation_store, SQLiteStore)
        assert isinstance(app.state.storage, SQLiteStore)
        assert isinstance(app.state.operation_service, OperationService)
        # Сервис работает поверх хранилища из app.state.
        operation = app.state.operation_service.create("Создай счёт", chat_id="chat-1")
        assert app.state.operation_store.get(operation.id) is not None
