"""Ошибки интеграции с 1С.

Формат ошибки OData 1С (Skill onec-error-handling):

    {"odata.error": {"code": "...", "message": {"value": "..."}}}
"""

import json
from typing import Any


class OnecError(Exception):
    """Базовая ошибка взаимодействия с 1С.

    Attributes:
        message: Текст ошибки, понятный агенту и пользователю.
        status: HTTP-код ответа, если ошибка пришла от HTTP-слоя.
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        """Инициализирует ошибку текстом и опциональным HTTP-кодом.

        Args:
            message: Описание ошибки.
            status: HTTP-код ответа 1С (если применимо).
        """
        super().__init__(message)
        self.message = message
        self.status = status


class OnecConnectionError(OnecError):
    """Сеть недоступна: соединение не установлено или истёк таймаут.

    Исход операции записи при такой ошибке неизвестен: POST мог дойти
    до 1С. Повторы выполняет вызывающий код (для чтения — безопасно,
    для записи — только после проверки на дубликаты).
    """


class OnecAuthError(OnecError):
    """Неверная авторизация (HTTP 401). Повторы бессмысленны."""


class OnecApiError(OnecError):
    """1С вернула ошибку по протоколу OData или не-JSON ответ.

    Attributes:
        odata_code: Значение `odata.error.code` из тела ответа.
    """

    def __init__(self, message: str, *, status: int, odata_code: str = "") -> None:
        """Инициализирует ошибку API.

        Args:
            message: Текст ошибки (из `odata.error.message.value` или общий).
            status: HTTP-код ответа.
            odata_code: Код ошибки OData, если он был разобран.
        """
        super().__init__(message, status=status)
        self.odata_code = odata_code


def parse_odata_error_body(body: str | bytes) -> dict[str, Any] | None:
    """Разбирает тело ответа 1С на предмет `odata.error`.

    Args:
        body: Тело HTTP-ответа (строка или байты).

    Returns:
        Словарь {"code": ..., "message": ...} или None, если тело не JSON
        или не содержит odata.error (например, HTML-страница веб-сервера).
    """
    try:
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    error = data.get("odata.error")
    if not isinstance(error, dict):
        return None
    message_field = error.get("message")
    message = (
        message_field.get("value", "")
        if isinstance(message_field, dict)
        else str(message_field or "")
    )
    return {"code": str(error.get("code", "")), "message": message}
