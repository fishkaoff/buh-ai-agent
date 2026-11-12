"""Юнит-тесты скачивания печатных форм PDF через HTTP-сервис печати 1С."""

import httpx
import pytest

from buh_ai_agent.integrations.onec.config import (
    OnecConnectionConfig,
    OnecDefaults,
    OnecSafety,
)
from buh_ai_agent.integrations.onec.errors import OnecApiError, OnecError
from buh_ai_agent.services import print_pdf

PDF_BYTES = b"%PDF-1.4\n%Test official print form\n%%EOF\n"


def make_config(print_service_url: str = "http://onec.test/hs/print") -> OnecConnectionConfig:
    """Конфигурация базы с (или без) HTTP-сервисом печати."""
    return OnecConnectionConfig(
        database="ai_agent",
        base_url="http://onec.test/odata/standard.odata/",
        username="user",
        password="test",
        defaults=OnecDefaults(),
        safety=OnecSafety(),
        print_service_url=print_service_url,
    )


def make_transport(handler: object) -> httpx.MockTransport:
    """Транспорт для HTTP-сервиса печати."""
    return httpx.MockTransport(handler)  # type: ignore[arg-type]


async def test_download_returns_pdf_bytes() -> None:
    """Успешный ответ сервиса возвращается как байты PDF."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/invoice/abc-123")
        return httpx.Response(200, content=PDF_BYTES, headers={"Content-Type": "application/pdf"})

    data = await print_pdf.download_print_form_pdf(
        make_config(), "invoice", "abc-123", transport=make_transport(handler)
    )
    assert data == PDF_BYTES


async def test_download_requires_configured_service() -> None:
    """Без print_service_url — ошибка с инструкцией, без HTTP-запроса."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=PDF_BYTES)

    with pytest.raises(OnecError, match="не настроен"):
        await print_pdf.download_print_form_pdf(
            make_config(print_service_url=""), "invoice", "abc", transport=make_transport(handler)
        )
    assert not calls


async def test_download_rejects_non_pdf_response() -> None:
    """Ответ не начинается с %PDF- — ошибка (сервис вернул не печатную форму)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>страница входа</html>")

    with pytest.raises(OnecApiError, match="не PDF"):
        await print_pdf.download_print_form_pdf(
            make_config(), "invoice", "abc", transport=make_transport(handler)
        )


async def test_download_reports_service_error_text() -> None:
    """Ошибка сервиса (4xx/5xx) отдаётся с текстом 1С для отладки расширения."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Ошибка печати: не найден макет")

    with pytest.raises(OnecApiError, match="не найден макет"):
        await print_pdf.download_print_form_pdf(
            make_config(), "invoice", "abc", transport=make_transport(handler)
        )


async def test_download_unknown_document_type() -> None:
    """Неподдержанный тип документа — ошибка до обращения к сети."""

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200, content=PDF_BYTES)

    with pytest.raises(ValueError, match="не поддержан"):
        await print_pdf.download_print_form_pdf(
            make_config(), "act", "abc", transport=make_transport(handler)
        )


def test_pdf_filename_uses_number_and_sanitizes() -> None:
    """Имя файла строится из номера; опасные символы заменяются."""
    assert print_pdf.pdf_filename("schet", number="0000-000001") == "schet_0000-000001.pdf"
    name = print_pdf.pdf_filename("upd", number='0000-1/1:*?"<>|', ref_key="abcdefab-1234")
    assert name == "upd_0000-1_1.pdf"
    # Без номера — метка из Ref_Key.
    assert print_pdf.pdf_filename("schet", ref_key="abcdefab-0000") == "schet_abcdefab.pdf"
