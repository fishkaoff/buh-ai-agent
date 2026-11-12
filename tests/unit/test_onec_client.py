"""Юнит-тесты async OData-клиента 1С."""

import json
from typing import Any
from urllib.parse import unquote

import httpx
import pytest
from tests.unit.onec_helpers import METADATA_XML, odata_error

from buh_ai_agent.integrations.onec.client import OnecClient, format_document_date
from buh_ai_agent.integrations.onec.errors import (
    OnecApiError,
    OnecAuthError,
    OnecConnectionError,
)

BASE = "http://onec.test/odata/standard.odata/"


def make_client(
    routes: dict[tuple[str, str], Any] | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    max_retries: int = 1,
) -> OnecClient:
    """Создаёт клиент с мок-транспортом."""
    return OnecClient(
        BASE,
        "user",
        "pass",
        transport=transport
        or httpx.MockTransport(lambda request: httpx.Response(200, json={"value": []})),
        max_retries=max_retries,
    )


async def test_query_appends_format_json_and_parses_value() -> None:
    """query добавляет $format=json и возвращает поле value."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization", "")
        return httpx.Response(200, json={"value": [{"Ref_Key": "a", "Description": "ООО Ромашка"}]})

    async with make_client(transport=httpx.MockTransport(handler)) as client:
        rows = await client.query("Catalog_Контрагенты", top=10)

    assert rows == [{"Ref_Key": "a", "Description": "ООО Ромашка"}]
    assert "$format=json" in captured["url"]
    assert "$top=10" in captured["url"]
    assert captured["auth"].startswith("Basic ")
    assert (
        "Catalog_%D0%9A%D0%BE%D0%BD%D1%82%D1%80%D0%B0%D0%B3%D0%B5%D0%BD%D1%82%D1%8B"
        in captured["url"]
    )


async def test_filter_url_contains_decoded_filter() -> None:
    """URL содержит закодированный фильтр, который раскодируется обратно."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = unquote(str(request.url))
        return httpx.Response(200, json={"value": []})

    async with make_client(transport=httpx.MockTransport(handler)) as client:
        await client.query(
            "Catalog_ДоговорыКонтрагентов",
            filter_="Owner_Key eq guid'abc-123' and ДоговорЗакрыт eq false",
        )

    assert "Owner_Key eq guid'abc-123' and ДоговорЗакрыт eq false" in captured["url"]


async def test_get_entity_key_lookup_with_guid_quotes() -> None:
    """get_entity строит path EntitySet(guid'...')."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert unquote(str(request.url)).endswith("Catalog_Контрагенты(guid'abc')?$format=json")
        return httpx.Response(200, json={"Ref_Key": "abc", "Description": "ООО Ромашка"})

    async with make_client(transport=httpx.MockTransport(handler)) as client:
        entity = await client.get_entity("Catalog_Контрагенты", "abc")

    assert entity["Ref_Key"] == "abc"


async def test_create_returns_created_object() -> None:
    """create (POST) возвращает тело 201 с Ref_Key."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"Ref_Key": "new-ref", "Code": "00-000001"})

    async with make_client(transport=httpx.MockTransport(handler)) as client:
        created = await client.create(
            "Catalog_Контрагенты", {"Description": "ООО Ромашка", "ИНН": "123"}
        )

    assert created["Ref_Key"] == "new-ref"
    assert captured["body"]["Description"] == "ООО Ромашка"


async def test_update_patch_204_returns_none() -> None:
    """update (PATCH) с ответом 204 возвращает None."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    async with make_client(transport=httpx.MockTransport(handler)) as client:
        result = await client.update("Document_СчетНаОплатуПокупателю", "ref", {"Posted": True})

    assert result is None


async def test_read_table_filters_by_ref_key() -> None:
    """read_table читает `..._Товары?$filter=Ref_Key eq guid'...'`."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = unquote(str(request.url))
        assert "Document_СчетНаОплатуПокупателю_Товары" in url
        assert "Ref_Key eq guid'doc-ref'" in url
        assert "$orderby=LineNumber" in url
        return httpx.Response(200, json={"value": [{"LineNumber": 1, "Сумма": 100}]})

    async with make_client(transport=httpx.MockTransport(handler)) as client:
        rows = await client.read_table("Document_СчетНаОплатуПокупателю", "Товары", "doc-ref")

    assert rows[0]["Сумма"] == 100


async def test_401_raises_auth_error() -> None:
    """401 даёт OnecAuthError с понятным сообщением."""
    transport = httpx.MockTransport(lambda request: odata_error(401, "", "не авторизован"))
    async with make_client(transport=transport) as client:
        with pytest.raises(OnecAuthError, match="401"):
            await client.query("Catalog_Контрагенты")


async def test_odata_error_body_raises_api_error() -> None:
    """Ошибка odata.error превращается в OnecApiError с кодом и текстом."""
    transport = httpx.MockTransport(
        lambda request: odata_error(400, "6", "Сегмент пути Name не найден!")
    )
    async with make_client(transport=transport) as client:
        with pytest.raises(OnecApiError, match="Сегмент пути Name не найден!") as exc_info:
            await client.query("Catalog_Контрагенты", filter_="Name eq 'x'")
    assert exc_info.value.odata_code == "6"
    assert exc_info.value.status == 400


async def test_html_404_raises_api_error_without_json() -> None:
    """Не-JSON ответ 404 превращается в OnecApiError."""
    transport = httpx.MockTransport(lambda request: httpx.Response(404, text="<html>nope</html>"))
    async with make_client(transport=transport) as client:
        with pytest.raises(OnecApiError, match="не-JSON"):
            await client.query("Catalog_НетТакого")


async def test_get_retry_on_network_error() -> None:
    """GET повторяется при сетевой ошибке (один раз по умолчанию)."""
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json={"value": []})

    async with make_client(transport=httpx.MockTransport(handler)) as client:
        rows = await client.query("Catalog_Контрагенты")

    assert rows == []
    assert calls["count"] == 2


async def test_get_retry_exhausted_raises_connection_error() -> None:
    """При исчерпании повторов GET даёт OnecConnectionError."""
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        raise httpx.ConnectError("connection refused")

    async with make_client(transport=httpx.MockTransport(handler), max_retries=1) as client:
        with pytest.raises(OnecConnectionError):
            await client.query("Catalog_Контрагенты")
    assert calls["count"] == 2


async def test_post_not_retried_on_network_error() -> None:
    """POST не ретраится при сетевой ошибке: исход записи неизвестен."""
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        raise httpx.ConnectError("connection refused")

    async with make_client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(OnecConnectionError, match="Таймаут|Сетевая"):
            await client.create("Catalog_Контрагенты", {"Description": "X"})
    assert calls["count"] == 1


async def test_requests_are_sequential() -> None:
    """Запросы выполняются последовательно благодаря внутреннему lock."""
    order: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        order.append(request.url.path)
        return httpx.Response(200, json={"value": []})

    async with make_client(transport=httpx.MockTransport(handler)) as client:
        import asyncio

        await asyncio.gather(
            client.query("Catalog_Контрагенты"),
            client.query("Catalog_Контрагенты"),
        )

    assert len(order) == 2


async def test_metadata_cached_and_enum_values_extracted() -> None:
    """$metadata читается один раз; перечисление разбирается из XML."""
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, text=METADATA_XML, headers={"content-type": "application/xml"})

    async with make_client(transport=httpx.MockTransport(handler)) as client:
        first = await client.list_enum_values("СтавкиНДС")
        second = await client.list_enum_values("СтавкиНДС")

    assert first == [
        "БезНДС",
        "НДС0",
        "НДС5",
        "НДС10",
        "НДС10_110",
        "НДС18",
        "НДС18_118",
        "НДС20",
        "НДС20_120",
    ]
    assert first == second
    assert calls["count"] == 1


async def test_unknown_enum_raises() -> None:
    """Неизвестное перечисление даёт понятную ошибку."""
    async with make_client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=METADATA_XML))
    ) as client:
        with pytest.raises(OnecApiError, match="не найдено"):
            await client.list_enum_values("НетТакого")


def test_format_document_date() -> None:
    """Дата форматируется как YYYY-MM-DDT00:00:00 без Z."""
    assert format_document_date("2026-11-10") == "2026-11-10T00:00:00"


def test_format_document_date_default_is_today() -> None:
    """Без аргумента берётся текущая дата UTC."""
    result = format_document_date()
    assert result.endswith("T00:00:00")
    assert len(result) == 19
