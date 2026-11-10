"""Интеграционные тесты HTTP API."""

from fastapi.testclient import TestClient

from buh_ai_agent.app import create_app


def test_health_returns_ok() -> None:
    """GET /health возвращает 200 и статус ok."""
    with TestClient(create_app()) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_chat_returns_501() -> None:
    """POST /chat возвращает 501 с понятным сообщением."""
    with TestClient(create_app()) as client:
        response = client.post("/chat", json={"message": "Привет, что ты умеешь?"})
        assert response.status_code == 501
        body = response.json()
        assert "detail" in body
        assert "не реализована" in body["detail"]


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
