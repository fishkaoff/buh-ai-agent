"""Юнит-тесты разбора ошибок OData 1С."""

import json

from buh_ai_agent.integrations.onec.errors import parse_odata_error_body


def test_parse_odata_error_standard_format() -> None:
    """Стандартная ошибка 1С разбирается в код и сообщение."""
    body = json.dumps(
        {
            "odata.error": {
                "code": "6",
                "message": {"lang": "ru", "value": "Сегмент пути Name не найден!"},
            }
        }
    ).encode()
    parsed = parse_odata_error_body(body)
    assert parsed == {"code": "6", "message": "Сегмент пути Name не найден!"}


def test_parse_odata_error_string_message() -> None:
    """Сообщение-строка (не словарь) тоже разбирается."""
    body = json.dumps({"odata.error": {"code": "", "message": "упрощённое сообщение"}}).encode()
    parsed = parse_odata_error_body(body)
    assert parsed is not None
    assert parsed["message"] == "упрощённое сообщение"


def test_parse_odata_error_html_body_returns_none() -> None:
    """HTML-ответ (не JSON) не считается ошибкой OData."""
    assert parse_odata_error_body(b"<html><body>404</body></html>") is None


def test_parse_odata_error_empty_json_returns_none() -> None:
    """JSON без odata.error не считается ошибкой OData."""
    assert parse_odata_error_body(json.dumps({"value": []}).encode()) is None


def test_parse_odata_error_str_input() -> None:
    """Тело может быть строкой."""
    parsed = parse_odata_error_body('{"odata.error": {"code": "1", "message": {"value": "ok"}}}')
    assert parsed is not None
    assert parsed["code"] == "1"
