"""Официальные печатные формы (PDF) через HTTP-сервис расширения 1С.

Правила — Skill onec-print-forms (доработка №1): стандартный OData печатные
формы не отдаёт; расширение 1С публикует HTTP-сервис печати (инструкция —
`docs/onec-print-http-service.md`), приложение скачивает готовый PDF:

    GET {print_service_url}/{тип}/{Ref_Key}  →  200, application/pdf

- URL сервиса берётся из конфигурации базы (print_service_url);
- авторизация — та же Basic-пара, что у OData этой базы;
- ответ проверяется по сигнатуре `%PDF-` — сервис вернул не PDF, ошибка;
- ошибки сервиса возвращаются с текстом 1С (сервис отдаёт подробное
  представление ошибки) — по ним удобно отлаживать расширение;
- PDF не сохраняются приложением: они прикладываются к ответу текущего
  хода диалога (side-channel, `AgentFile`) и передаются клиенту в base64.
"""

from __future__ import annotations

import re

import httpx

from buh_ai_agent.integrations.onec.config import OnecConnectionConfig
from buh_ai_agent.integrations.onec.errors import OnecApiError

# Сигнатура PDF-файла: сервис обязан вернуть именно PDF.
PDF_MAGIC = b"%PDF-"

# Типы документов, для которых сервис печати уже развёрнут (шаблоны URL
# расширения). Расширяется по мере добавления шаблонов в расширении.
_SERVICE_PATHS: dict[str, str] = {
    "invoice": "invoice",  # Счёт на оплату покупателю
    "realization": "realization",  # Реализация товаров и услуг (УПД)
}


def print_service_path(document_type: str) -> str:
    """Возвращает сегмент пути сервиса для типа документа.

    Args:
        document_type: Тип документа (`invoice`, `realization`).

    Returns:
        Сегмент пути (`invoice`).

    Raises:
        ValueError: Тип документа не поддержан сервисом печати.
    """
    path = _SERVICE_PATHS.get(document_type)
    if path is None:
        raise ValueError(
            f"Тип документа {document_type!r} не поддержан HTTP-сервисом печати "
            f"(доступны: {', '.join(sorted(_SERVICE_PATHS))})."
        )
    return path


def _error_text(response: httpx.Response) -> str:
    """Извлекает текст ошибки из ответа сервиса (JSON или plain text)."""
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        try:
            data = response.json()
            for key in ("message", "error", "description"):
                value = data.get(key) if isinstance(data, dict) else None
                if value:
                    return str(value)
        except ValueError:
            pass
    return response.content[:300].decode("utf-8", "replace").strip()


async def download_print_form_pdf(
    config: OnecConnectionConfig,
    document_type: str,
    ref_key: str,
    *,
    timeout: float = 60.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bytes:
    """Скачивает печатную форму документа в PDF через HTTP-сервис расширения 1С.

    Args:
        config: Конфигурация базы (print_service_url, учётные данные).
        document_type: Тип документа (`invoice`, `realization`).
        ref_key: Ref_Key документа 1С (GUID).
        timeout: Таймаут HTTP-запроса (печать может занимать секунды).
        transport: httpx-транспорт (для тестов); None — обычный сетевой.

    Returns:
        Содержимое PDF-файла (байты).

    Raises:
        OnecError: Сервис печати не настроен для базы.
        OnecApiError: Ошибка HTTP или ответ не является PDF.
    """
    if not config.print_service_url:
        raise OnecApiError(
            "HTTP-сервис печати не настроен для базы "
            f"«{config.database}» (print_service_url). Инструкция — "
            "docs/onec-print-http-service.md.",
            status=503,
        )
    path = print_service_path(document_type)
    url = f"{config.print_service_url.rstrip('/')}/{path}/{ref_key}"

    async with httpx.AsyncClient(
        auth=(config.username, config.password.get_secret_value()),
        timeout=timeout,
        transport=transport,
        follow_redirects=False,
    ) as client:
        try:
            response = await client.get(url)
        except httpx.TimeoutException as error:
            raise OnecApiError(
                f"Таймаут запроса к сервису печати 1С: {error}", status=504
            ) from error
        except httpx.HTTPError as error:
            raise OnecApiError(
                f"Сетевая ошибка запроса к сервису печати 1С: {error}", status=503
            ) from error

    if response.status_code == 200:
        if not response.content.startswith(PDF_MAGIC):
            raise OnecApiError(
                "Сервис печати вернул не PDF "
                f"(начало: {response.content[:24].decode('utf-8', 'replace')!r}).",
                status=200,
            )
        return response.content
    raise OnecApiError(
        f"HTTP-сервис печати вернул ошибку (HTTP {response.status_code}): {_error_text(response)}",
        status=response.status_code,
    )


def pdf_filename(prefix: str, *, number: str = "", ref_key: str = "") -> str:
    """Строит имя PDF-файла печатной формы.

    Файлы не сохраняются приложением — имя нужно только клиенту ответа.

    Args:
        prefix: Начало имени (`schet`, `upd`).
        number: Номер документа из 1С (приоритетнее).
        ref_key: Ref_Key документа (fallback, если номер не получен).

    Returns:
        Имя файла («schet_0000-000001.pdf»).
    """
    label = _sanitize_name(number) if number else _sanitize_name(ref_key[:8])
    return f"{prefix}_{label}.pdf"


def _sanitize_name(value: str) -> str:
    """Оставляет в имени файла только безопасные символы."""
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", value).strip(" ._")
    return cleaned[:40] or "beznomer"
