"""Юнит-тесты FastAPI-приложения."""

from fastapi import FastAPI

from buh_ai_agent.app import create_app


def test_create_app_returns_fastapi_instance() -> None:
    """Приложение создаётся и имеет правильный тип."""
    app = create_app()
    assert isinstance(app, FastAPI)


def test_app_has_expected_routes() -> None:
    """Приложение регистрирует маршруты /health и /chat."""
    app = create_app()
    paths = set(app.openapi()["paths"])
    assert "/health" in paths
    assert "/chat" in paths


def test_app_title_and_version() -> None:
    """Приложение использует настройки и версию из пакета."""
    app = create_app()
    assert app.title == "buh-ai-agent"
    assert app.version == "0.1.0"
