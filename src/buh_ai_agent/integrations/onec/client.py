"""Асинхронный OData 3.0-клиент 1С на httpx.

Реализует проверенные соглашения Skill onec-odata и зеркалит поведение
`config/onec/odata-client.js`:

- `$format=json` добавляется к каждому запросу, иначе 1С вернёт XML;
- фильтры: `substringof('текст', Поле)`, `Поле eq 'значение'`
  (`contains`/`tolower` не поддержаны);
- key-lookup: `EntitySet(guid'...')`;
- табличные части читаются отдельным запросом `..._Имя?$filter=Ref_Key eq guid'...'`
  (`$expand` возвращает 501);
- даты документов — `YYYY-MM-DDT00:00:00` без `Z`;
- запросы выполняются строго последовательно (1С обрабатывает запросы
  одной учётки по очереди);
- один повтор для GET при сетевой ошибке; для записей (POST/PATCH) исход
  после сетевой ошибки неизвестен — клиент не ретраит, решение о повторе
  принимает вызывающий код после проверки на дубликаты.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import SecretStr

from buh_ai_agent.integrations.onec.config import OnecConnectionConfig
from buh_ai_agent.integrations.onec.errors import (
    OnecApiError,
    OnecAuthError,
    OnecConnectionError,
    parse_odata_error_body,
)

logger = logging.getLogger(__name__)

# Символы, которые encodeURIComponent оставляет как есть: точно так же
# кодируем значения параметров, чтобы фильтры совпадали с проверенными
# из Skills (одинарные кавычки не кодируются).
_QUERY_SAFE = "!*'()~"
_PATH_SAFE = "/()'"

_RETRYABLE_STATUS = (502, 503, 504)


class OnecClient:
    """HTTP-клиент 1С по OData 3.0 с авторизацией Basic и ограниченными retry."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: SecretStr | str,
        *,
        timeout: float = 30.0,
        max_retries: int = 1,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Инициализирует клиент.

        Args:
            base_url: Базовый URL OData-интерфейса (оканчивается на `/`).
            username: Логин.
            password: Пароль (SecretStr, чтобы не попадал в repr/логи).
            timeout: Таймаут одного HTTP-запроса в секундах.
            max_retries: Число повторов GET при сетевых ошибках.
            transport: httpx-транспорт (для тестов); None — обычный сетевой.
        """
        self._base_url = base_url if base_url.endswith("/") else base_url + "/"
        self._auth = httpx.BasicAuth(
            username, password.get_secret_value() if isinstance(password, SecretStr) else password
        )
        self._max_retries = max(0, max_retries)
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            auth=self._auth,
            timeout=timeout,
            headers={"Accept": "application/json"},
            transport=transport,
        )
        self._metadata_cache: str | None = None
        self._enum_cache: dict[str, list[str]] = {}

    @classmethod
    def from_config(
        cls,
        config: OnecConnectionConfig,
        *,
        timeout: float = 30.0,
        max_retries: int = 1,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> OnecClient:
        """Создаёт клиент из собранной конфигурации подключения.

        Args:
            config: Конфигурация базы 1С (файл + переменные окружения).
            timeout: Таймаут HTTP-запроса.
            max_retries: Число повторов GET при сетевых ошибках.
            transport: httpx-транспорт (для тестов).

        Returns:
            Готовый клиент.
        """
        return cls(
            config.base_url,
            config.username,
            config.password,
            timeout=timeout,
            max_retries=max_retries,
            transport=transport,
        )

    async def aclose(self) -> None:
        """Закрывает HTTP-клиент."""
        await self._client.aclose()

    async def __aenter__(self) -> OnecClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Низкий уровень
    # ------------------------------------------------------------------

    def _build_url(self, path: str, params: list[tuple[str, str]] | None) -> str:
        """Строит полный URL: base + закодированный путь + query.

        Args:
            path: Путь после base (имя EntitySet, key-lookup, `$metadata`).
            params: Список пар (имя, значение) query-параметров в нужном порядке.

        Returns:
            Полный URL с percent-кодированием в стиле encodeURIComponent.
        """
        url = self._base_url + quote(path, safe=_PATH_SAFE)
        if params:
            url += "?" + "&".join(
                f"{name}={quote(value, safe=_QUERY_SAFE)}" for name, value in params
            )
        return url

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: list[tuple[str, str]] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Выполняет HTTP-запрос к 1С с обработкой ошибок.

        Запросы сериализуются внутренним lock'ом: 1С обрабатывает запросы
        одной учётки по очереди, параллельные вызовы недопустимы.

        Args:
            method: HTTP-метод (GET/POST/PATCH).
            path: Путь после base URL.
            params: Query-параметры (уже в порядке следования).
            json_body: JSON-тело для POST/PATCH.

        Returns:
            Ответ httpx (2xx).

        Raises:
            OnecConnectionError: Сетевая ошибка или таймаут (исход записи
                неизвестен; GET при исчерпании повторов).
            OnecAuthError: HTTP 401 — неверные учётные данные.
            OnecApiError: Прочие ошибки HTTP, включая ошибки OData.
        """
        url = self._build_url(path, params)
        is_read = method.upper() == "GET"
        attempts = self._max_retries + 1 if is_read else 1
        last_error: OnecConnectionError | None = None

        async with self._lock:
            for attempt in range(attempts):
                try:
                    response = await self._client.request(
                        method, url, json=json_body if json_body is not None else None
                    )
                    break
                except httpx.TimeoutException as error:
                    last_error = OnecConnectionError(
                        f"Таймаут запроса к 1С ({method} {path}): {error}"
                    )
                except httpx.HTTPError as error:
                    last_error = OnecConnectionError(
                        f"Сетевая ошибка запроса к 1С ({method} {path}): {error}"
                    )
                if attempt < attempts - 1:
                    logger.warning("Повтор запроса 1С (%s/%s): %s", attempt + 1, attempts, path)
            else:
                raise (
                    last_error
                    if last_error
                    else OnecConnectionError(f"Неизвестная сетевая ошибка ({method} {path})")
                )

        self._log_response(method, path, response)
        self._raise_for_status(method, path, response)
        return response

    @staticmethod
    def _log_response(method: str, path: str, response: httpx.Response) -> None:
        """Логирует факт запроса без секретов и без тел записей."""
        logger.info("1С OData %s %s -> %s", method, path, response.status_code)
        if logger.isEnabledFor(logging.DEBUG):
            body = getattr(response, "_content", b"") or b""
            logger.debug(
                "1С OData тело ответа (%s %s): %.500s",
                method,
                path,
                body.decode("utf-8", "replace"),
            )

    def _raise_for_status(self, method: str, path: str, response: httpx.Response) -> None:
        """Преобразует неуспешные ответы в исключения клиента.

        Args:
            method: HTTP-метод (для сообщений).
            path: Путь запроса (для сообщений).
            response: Ответ 1С.

        Raises:
            OnecAuthError: 401.
            OnecApiError: прочие не-2xx, включая не-JSON ответы.
        """
        if response.is_success:
            return
        if response.status_code == 401:
            raise OnecAuthError("1С отклонила авторизацию (HTTP 401): проверьте логин и пароль.")
        parsed = parse_odata_error_body(response.content)
        if parsed is not None:
            message = parsed["message"] or "ошибка 1С без описания"
            raise OnecApiError(
                f"Ошибка 1С (HTTP {response.status_code}, код {parsed['code'] or '-'}): {message}",
                status=response.status_code,
                odata_code=parsed["code"],
            )
        # Не-JSON ответ: например, HTML-страница веб-сервера при неверном пути.
        if response.status_code in _RETRYABLE_STATUS and method.upper() == "GET":
            raise OnecApiError(
                f"1С временно недоступна (HTTP {response.status_code}): {path}",
                status=response.status_code,
            )
        snippet = response.content[:200].decode("utf-8", "replace") if response.content else ""
        raise OnecApiError(
            f"1С вернула не-JSON ответ (HTTP {response.status_code}) для {path}. {snippet}".strip(),
            status=response.status_code,
        )

    # ------------------------------------------------------------------
    # Высокий уровень
    # ------------------------------------------------------------------

    async def query(
        self,
        entity_set: str,
        *,
        filter_: str | None = None,
        select: str | None = None,
        order_by: str | None = None,
        top: int | None = None,
        skip: int | None = None,
    ) -> list[dict[str, Any]]:
        """Читает список объектов EntitySet.

        Args:
            entity_set: Имя EntitySet (например, `Catalog_Контрагенты`).
            filter_: Текст `$filter` (substringof/eq/and/or).
            select: Список полей для `$select`.
            order_by: Текст `$orderby`.
            top: Ограничение числа строк.
            skip: Смещение.

        Returns:
            Массив объектов из поля `value` ответа.
        """
        params: list[tuple[str, str]] = [("$format", "json")]
        if filter_:
            params.append(("$filter", filter_))
        if select:
            params.append(("$select", select))
        if order_by:
            params.append(("$orderby", order_by))
        if top is not None:
            params.append(("$top", str(top)))
        if skip is not None:
            params.append(("$skip", str(skip)))
        response = await self.request("GET", entity_set, params=params)
        data = response.json()
        return data.get("value", []) if isinstance(data, dict) else []

    async def get_entity(
        self, entity_set: str, ref_key: str, *, select: str | None = None
    ) -> dict[str, Any]:
        """Читает один объект по ключу `EntitySet(guid'...')`.

        Args:
            entity_set: Имя EntitySet.
            ref_key: GUID объекта (Ref_Key).
            select: Список полей для `$select`.

        Returns:
            Объект как словарь.

        Raises:
            OnecApiError: 404 — объект не найден.
        """
        params = [("$format", "json")]
        if select:
            params.append(("$select", select))
        path = f"{entity_set}(guid'{ref_key}')"
        response = await self.request("GET", path, params=params)
        return response.json()

    async def create(self, entity_set: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Создаёт объект (POST). 1С присваивает Ref_Key/Number/Code сама.

        Args:
            entity_set: Имя EntitySet.
            payload: Тело создания; `Number` документа отправлять не нужно.

        Returns:
            Созданный объект из ответа (201) с присвоенными ключами.
        """
        response = await self.request("POST", entity_set, json_body=payload)
        return response.json()

    async def update(
        self, entity_set: str, ref_key: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Изменяет объект (PATCH) по ключу; 204 → None, 200 → тело.

        Args:
            entity_set: Имя EntitySet.
            ref_key: GUID объекта.
            payload: Только изменяемые поля.

        Returns:
            Тело ответа, если 1С вернула JSON, иначе None.
        """
        path = f"{entity_set}(guid'{ref_key}')"
        response = await self.request("PATCH", path, json_body=payload)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    async def read_table(
        self,
        entity_set: str,
        table_name: str,
        ref_key: str,
        *,
        order_by: str | None = "LineNumber",
    ) -> list[dict[str, Any]]:
        """Читает строки табличной части документа.

        `$expand` в 1С даёт 501, поэтому строки читаются отдельным
        запросом: `..._ИмяТЧ?$filter=Ref_Key eq guid'<Ref>'`.

        Args:
            entity_set: Имя EntitySet документа.
            table_name: Имя табличной части (`Товары`, `Услуги`, ...).
            ref_key: GUID документа (Ref_Key).
            order_by: Сортировка (по умолчанию `LineNumber`; None — без неё).

        Returns:
            Строки табличной части.
        """
        return await self.query(
            f"{entity_set}_{table_name}",
            filter_=f"Ref_Key eq guid'{ref_key}'",
            order_by=order_by,
        )

    async def get_metadata(self) -> str:
        """Возвращает XML `$metadata` (кэшируется на жизнь клиента)."""
        if self._metadata_cache is None:
            response = await self.request("GET", "$metadata")
            self._metadata_cache = response.text
        return self._metadata_cache

    async def list_enum_values(self, enum_name: str) -> list[str]:
        """Возвращает значения перечисления конфигурации из `$metadata`.

        Args:
            enum_name: Имя EnumType (например, `СтавкиНДС`).

        Returns:
            Список имён членов перечисления.

        Raises:
            OnecApiError: Перечисление не найдено в метаданных.
        """
        if enum_name in self._enum_cache:
            return self._enum_cache[enum_name]
        # Ленивый импорт, чтобы не тянуть ElementTree при каждом вызове.
        from buh_ai_agent.integrations.onec.metadata import extract_enum_values

        values = extract_enum_values(await self.get_metadata(), enum_name)
        if values is None:
            raise OnecApiError(f"Перечисление «{enum_name}» не найдено в $metadata 1С.", status=400)
        self._enum_cache[enum_name] = values
        return values


def format_document_date(date_iso: str | None = None) -> str:
    """Форматирует дату документа для OData: `YYYY-MM-DDT00:00:00` без Z.

    Args:
        date_iso: Дата в формате `YYYY-MM-DD` или None — сегодня (UTC).

    Returns:
        Строка даты в формате 1С OData.
    """
    parsed = date.fromisoformat(date_iso) if date_iso else datetime.now(tz=UTC).date()
    return f"{parsed.isoformat()}T00:00:00"
