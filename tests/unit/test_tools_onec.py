"""Юнит-тесты Tools 1С: поиск, создание, полный сценарий счёта и УПД."""

import json
from typing import Any

import httpx
from langchain_core.tools import BaseTool
from tests.unit.onec_helpers import (
    ACCOUNTS_ROWS,
    BANK_ACCOUNT_REF,
    CONTRACT_REF,
    CONTRACTOR_REF,
    INVOICE_REF,
    METADATA_XML,
    NOMENCLATURE_REF,
    ORG_REF,
    REALIZATION_REF,
    RUB_REF,
    VAT_INVOICE_REF,
    WAREHOUSE_REF,
    contract_row,
    counterparty_row,
    entity_ref,
    facture_row,
    invoice_line_row,
    invoice_row,
    make_client,
    make_transport,
    nomenclature_row,
    organization_row,
    realization_row,
    realization_service_line_row,
)

from buh_ai_agent.agent.context import DialogContext, bind_dialog_context
from buh_ai_agent.integrations.onec.config import OnecDefaults, OnecSafety
from buh_ai_agent.integrations.onec.registry import OnecClients
from buh_ai_agent.tools.onec import make_onec_tools


def make_config() -> Any:
    """Конфигурация базы 1С для тестов."""
    from buh_ai_agent.integrations.onec.config import OnecConnectionConfig

    return OnecConnectionConfig(
        database="ai_agent",
        base_url="http://onec.test/base/",
        username="user",
        password="test",
        defaults=OnecDefaults(currency_code="643", vat_rate="НДС5"),
        safety=OnecSafety(),
    )


def make_clients(
    transport: httpx.MockTransport | None = None,
) -> OnecClients:
    """Реестр подключений с одной тестовой базой (транспорт — по умолчанию)."""
    return OnecClients.single(
        make_client(transport if transport is not None else make_transport(make_routes())),
        make_config(),
    )


def make_routes() -> dict[tuple[str, str], Any]:
    """Маршруты 1С для полного сценария счёта и УПД."""
    return {
        ("GET", "Catalog_Организации"): [organization_row()],
        ("GET", "Catalog_Контрагенты?$"): [counterparty_row()],
        ("GET", "Catalog_Контрагенты(guid'"): counterparty_row(),
        ("GET", "Catalog_ДоговорыКонтрагентов"): [contract_row()],
        ("GET", "Catalog_Номенклатура"): [nomenclature_row()],
        ("POST", "Catalog_Номенклатура"): entity_ref(NOMENCLATURE_REF, "00-000005"),
        ("GET", "Catalog_Номенклатура(guid'"): nomenclature_row(),
        ("GET", "Catalog_Валюты"): [{"Ref_Key": RUB_REF, "Code": "643", "Description": "руб."}],
        ("GET", "Catalog_Склады"): [
            {"Ref_Key": WAREHOUSE_REF, "Description": "Основной склад", "IsFolder": False}
        ],
        ("GET", "Catalog_БанковскиеСчета"): [
            {"Ref_Key": BANK_ACCOUNT_REF, "Description": "Р/с 40802810", "Owner": ORG_REF}
        ],
        ("GET", "ChartOfAccounts_Хозрасчетный"): ACCOUNTS_ROWS,
        ("GET", "Document_СчетНаОплатуПокупателю(guid'"): invoice_row(),
        ("GET", "Document_СчетНаОплатуПокупателю_Товары"): [invoice_line_row()],
        # Антидубликат: счёта контрагента за сегодня не найдены.
        ("GET", "Document_СчетНаОплатуПокупателю?$"): [],
        ("GET", "Document_РеализацияТоваровУслуг(guid'"): realization_row(),
        ("GET", "Document_РеализацияТоваровУслуг_Услуги"): [realization_service_line_row()],
        ("GET", "Document_РеализацияТоваровУслуг_Товары"): [],
        ("GET", "$metadata"): httpx.Response(200, text=METADATA_XML),
        ("POST", "Document_СчетНаОплатуПокупателю"): entity_ref(INVOICE_REF, "0000-0000001"),
        ("POST", "Document_РеализацияТоваровУслуг"): entity_ref(REALIZATION_REF, "0000-0000003"),
        ("POST", "Document_СчетФактураВыданный"): entity_ref(VAT_INVOICE_REF, "0000-0000001"),
        ("GET", "Document_СчетФактураВыданный(guid'"): facture_row(),
    }


def test_tools_registered() -> None:
    """Tools 1С зарегистрированы и доступны агенту."""
    transport = make_transport(make_routes())
    tools = make_onec_tools(make_clients(transport))
    names = [t.name for t in tools]
    assert "find_counterparty" in names
    assert "create_counterparty" in names
    assert "find_contract" in names
    assert "create_contract" in names
    assert "find_nomenclature" in names
    assert "create_nomenclature" in names
    assert "create_sales_invoice" in names
    assert "get_document" in names
    assert "list_allowed_vat_rates" in names
    assert "export_document_pdf" in names
    assert all(isinstance(t, BaseTool) for t in tools)


async def test_find_counterparty() -> None:
    """find_counterparty возвращает найденного контрагента."""
    transport = make_transport(make_routes())
    tools = make_onec_tools(make_clients(transport))
    tool = next(t for t in tools if t.name == "find_counterparty")
    result = await tool.ainvoke({"name": "Ромашка"})
    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["data"]["count"] == 1
    assert parsed["data"]["counterparties"][0]["ref_key"] == CONTRACTOR_REF


async def test_find_counterparty_requires_query() -> None:
    """find_counterparty без ИНН и наименования — ошибка."""
    transport = make_transport(make_routes())
    tools = make_onec_tools(make_clients(transport))
    tool = next(t for t in tools if t.name == "find_counterparty")
    result = await tool.ainvoke({"name": "", "inn": ""})
    parsed = json.loads(result)
    assert parsed["ok"] is False
    assert "Укажите наименование" in parsed["error"]


async def test_find_nomenclature() -> None:
    """find_nomenclature возвращает найденные позиции."""
    transport = make_transport(make_routes())
    tools = make_onec_tools(make_clients(transport))
    tool = next(t for t in tools if t.name == "find_nomenclature")
    result = await tool.ainvoke({"query": "Консультация"})
    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["data"]["count"] == 1
    assert parsed["data"]["items"][0]["ref_key"] == NOMENCLATURE_REF


async def test_list_allowed_vat_rates() -> None:
    """list_allowed_vat_rates возвращает ставки из $metadata."""
    transport = make_transport(make_routes())
    tools = make_onec_tools(make_clients(transport))
    tool = next(t for t in tools if t.name == "list_allowed_vat_rates")
    result = await tool.ainvoke({})
    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert "НДС5" in parsed["data"]["rates"] or "НДС20" in parsed["data"]["rates"]


async def test_create_sales_invoice_full_scenario() -> None:
    """Полный сценарий: счёт → реализация → счёт-фактура (УПД)."""
    transport = make_transport(make_routes())
    tools = make_onec_tools(make_clients(transport))
    tool = next(t for t in tools if t.name == "create_sales_invoice")
    result = await tool.ainvoke(
        {
            "counterparty_key": CONTRACTOR_REF,
            "contract_key": CONTRACT_REF,
            "lines": [
                {
                    "name": "Разработка программного обеспечения",
                    "quantity": 1,
                    "price": 100000,
                    "is_service": True,
                }
            ],
            "vat_rate": "НДС5",
        }
    )
    parsed = json.loads(result)
    assert parsed["ok"] is True, parsed
    assert parsed["data"]["invoice"]["ref_key"] == INVOICE_REF
    assert parsed["data"]["realization"]["ref_key"] == REALIZATION_REF
    assert parsed["data"]["facture"]["ref_key"] == VAT_INVOICE_REF
    assert "ЧЕРНОВИК" in parsed["data"]["invoice_draft"]


async def test_create_sales_invoice_requires_lines() -> None:
    """create_sales_invoice без позиций — ошибка."""
    transport = make_transport(make_routes())
    tools = make_onec_tools(make_clients(transport))
    tool = next(t for t in tools if t.name == "create_sales_invoice")
    result = await tool.ainvoke(
        {
            "counterparty_key": CONTRACTOR_REF,
            "contract_key": CONTRACT_REF,
            "lines": [],
        }
    )
    parsed = json.loads(result)
    assert parsed["ok"] is False
    assert "Не переданы позиции" in parsed["error"]


async def test_create_sales_invoice_rejects_unsupported_vat() -> None:
    """Ставка НДС, отсутствующая в $metadata, отклоняется без записи."""
    routes = make_routes()
    routes[("GET", "$metadata")] = httpx.Response(200, text=METADATA_XML.replace("НДС5", "НДС20"))
    transport = make_transport(routes)
    tools = make_onec_tools(make_clients(transport))
    tool = next(t for t in tools if t.name == "create_sales_invoice")
    result = await tool.ainvoke(
        {
            "counterparty_key": CONTRACTOR_REF,
            "contract_key": CONTRACT_REF,
            "lines": [{"name": "Услуга", "quantity": 1, "price": 100000, "is_service": True}],
            "vat_rate": "НДС5",
        }
    )
    parsed = json.loads(result)
    assert parsed["ok"] is False
    assert "НДС5" in parsed["error"]
    assert "отсутствует" in parsed["error"]
    # Записи не было: POST-запросов к документам нет.
    posts = [r for r in transport.seen_requests if r.method == "POST"]  # type: ignore[attr-defined]
    assert not posts


async def test_create_sales_invoice_blocks_duplicate_open_invoice() -> None:
    """Непроведённый счёт контрагента за сегодня блокирует создание дубликата."""
    routes = make_routes()
    # Контрагент уже имеет непроведённый счёт за сегодня.
    routes[("GET", "Document_СчетНаОплатуПокупателю?$")] = [invoice_row(Posted=False)]
    transport = make_transport(routes)
    tools = make_onec_tools(make_clients(transport))
    tool = next(t for t in tools if t.name == "create_sales_invoice")
    result = await tool.ainvoke(
        {
            "counterparty_key": CONTRACTOR_REF,
            "contract_key": CONTRACT_REF,
            "lines": [{"name": "Услуга", "quantity": 1, "price": 100000, "is_service": True}],
            "vat_rate": "НДС5",
        }
    )
    parsed = json.loads(result)
    assert parsed["ok"] is False
    assert "дубликат" in parsed["error"]
    assert "update_sales_invoice_lines" in parsed["error"]
    assert "force_new" in parsed["error"]
    # Документ не создавался.
    posts = [r for r in transport.seen_requests if r.method == "POST"]  # type: ignore[attr-defined]
    assert not posts


async def test_create_sales_invoice_force_new_bypasses_duplicate_block() -> None:
    """force_new=true позволяет создать новый счёт при существующих."""
    routes = make_routes()
    routes[("GET", "Document_СчетНаОплатуПокупателю?$")] = [invoice_row(Posted=False)]
    transport = make_transport(routes)
    tools = make_onec_tools(make_clients(transport))
    tool = next(t for t in tools if t.name == "create_sales_invoice")
    result = await tool.ainvoke(
        {
            "counterparty_key": CONTRACTOR_REF,
            "contract_key": CONTRACT_REF,
            "lines": [{"name": "Услуга", "quantity": 1, "price": 100000, "is_service": True}],
            "vat_rate": "НДС5",
            "force_new": True,
        }
    )
    parsed = json.loads(result)
    assert parsed["ok"] is True, parsed
    assert parsed["data"]["invoice"]["ref_key"] == INVOICE_REF


async def test_create_sales_invoice_1c_unavailable() -> None:
    """Недоступность 1С — понятная ошибка, без stack traces."""
    transport = make_transport({("GET", "$metadata"): httpx.Response(200, text=METADATA_XML)})
    tools = make_onec_tools(make_clients(transport))
    tool = next(t for t in tools if t.name == "create_sales_invoice")
    result = await tool.ainvoke(
        {
            "counterparty_key": CONTRACTOR_REF,
            "contract_key": CONTRACT_REF,
            "lines": [{"name": "Услуга", "quantity": 1, "price": 100000, "is_service": True}],
        }
    )
    parsed = json.loads(result)
    assert parsed["ok"] is False
    assert "create_sales_invoice" in parsed["error"]
    assert "Traceback" not in parsed["error"]


# ------------------------------------------------------------------
# create_contract: сквозная нумерация и обязательный номер
# ------------------------------------------------------------------


def contract_routes(contracts_rows: list[dict[str, Any]]) -> dict[tuple[str, str], Any]:
    """Маршруты для create_contract: список договоров + создание и перечитывание."""
    return {
        ("GET", "Catalog_ДоговорыКонтрагентов"): contracts_rows,
        ("GET", "Catalog_Организации"): [organization_row()],
        ("GET", "Catalog_Валюты"): [{"Ref_Key": RUB_REF, "Code": "643", "Description": "руб."}],
        ("POST", "Catalog_ДоговорыКонтрагентов"): entity_ref(CONTRACT_REF, "00-000009"),
        ("GET", "Catalog_ДоговорыКонтрагентов(guid'"): contract_row(),
    }


async def test_create_contract_auto_number_is_global() -> None:
    """Кандидат номера = max(числовых Номер по ВСЕМ договорам базы) + 1."""
    # У контрагента договоров нет; номер 7 занят договором другого контрагента.
    rows = [contract_row(Номер="7", Owner_Key="another-owner-guid")]
    transport = make_transport(contract_routes(rows))
    tools = make_onec_tools(make_clients(transport))
    tool = next(t for t in tools if t.name == "create_contract")
    result = await tool.ainvoke({"counterparty_key": CONTRACTOR_REF, "kind": "СПокупателем"})
    parsed = json.loads(result)
    assert parsed["ok"] is True, parsed
    posts = [r for r in transport.seen_requests if r.method == "POST"]  # type: ignore[attr-defined]
    body = json.loads(posts[0].content)
    assert body["Номер"] == "8"
    from datetime import UTC, datetime

    expected_description = f"8 от {datetime.now(tz=UTC).strftime('%d.%m.%Y')}"
    assert body["Description"] == expected_description


async def test_create_contract_never_without_number() -> None:
    """Если номер определить нельзя — ошибка с просьбой спросить пользователя; «б/н» нет."""
    rows = [contract_row(Номер="б/н", Owner_Key=CONTRACTOR_REF)]
    transport = make_transport(contract_routes(rows))
    tools = make_onec_tools(make_clients(transport))
    tool = next(t for t in tools if t.name == "create_contract")
    result = await tool.ainvoke({"counterparty_key": CONTRACTOR_REF, "kind": "СПокупателем"})
    parsed = json.loads(result)
    assert parsed["ok"] is False
    assert "Уточните номер" in parsed["error"]
    posts = [r for r in transport.seen_requests if r.method == "POST"]  # type: ignore[attr-defined]
    assert not posts


async def test_create_contract_rejects_number_taken_by_other_counterparty() -> None:
    """Номер, занятый договором другого контрагента, не переиспользуется."""
    rows = [contract_row(Номер="5", Owner_Key="another-owner-guid")]
    transport = make_transport(contract_routes(rows))
    tools = make_onec_tools(make_clients(transport))
    tool = next(t for t in tools if t.name == "create_contract")
    result = await tool.ainvoke(
        {"counterparty_key": CONTRACTOR_REF, "kind": "СПокупателем", "number": "5"}
    )
    parsed = json.loads(result)
    assert parsed["ok"] is False
    assert "уже занят" in parsed["error"]
    posts = [r for r in transport.seen_requests if r.method == "POST"]  # type: ignore[attr-defined]
    assert not posts


async def test_create_contract_rejects_number_taken_by_other_kind() -> None:
    """Номер занят договором того же контрагента, но другого вида, — ошибка."""
    rows = [contract_row(Номер="5", Owner_Key=CONTRACTOR_REF, ВидДоговора="СПоставщиком")]
    transport = make_transport(contract_routes(rows))
    tools = make_onec_tools(make_clients(transport))
    tool = next(t for t in tools if t.name == "create_contract")
    result = await tool.ainvoke(
        {"counterparty_key": CONTRACTOR_REF, "kind": "СПокупателем", "number": "5"}
    )
    parsed = json.loads(result)
    assert parsed["ok"] is False
    assert "уже занят" in parsed["error"]


async def test_create_contract_same_owner_same_kind_returns_existing() -> None:
    """Договор с тем же номером, видом и контрагентом возвращается как существующий."""
    rows = [contract_row(Номер="5", Owner_Key=CONTRACTOR_REF, ВидДоговора="СПокупателем")]
    transport = make_transport(contract_routes(rows))
    tools = make_onec_tools(make_clients(transport))
    tool = next(t for t in tools if t.name == "create_contract")
    result = await tool.ainvoke(
        {"counterparty_key": CONTRACTOR_REF, "kind": "СПокупателем", "number": "5"}
    )
    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["data"]["already_exists"] is True
    posts = [r for r in transport.seen_requests if r.method == "POST"]  # type: ignore[attr-defined]
    assert not posts


async def test_create_contract_uses_explicit_number() -> None:
    """Явно указанный номер используется как есть."""
    transport = make_transport(contract_routes([]))
    tools = make_onec_tools(make_clients(transport))
    tool = next(t for t in tools if t.name == "create_contract")
    result = await tool.ainvoke(
        {"counterparty_key": CONTRACTOR_REF, "kind": "СПокупателем", "number": "12"}
    )
    parsed = json.loads(result)
    assert parsed["ok"] is True, parsed
    posts = [r for r in transport.seen_requests if r.method == "POST"]  # type: ignore[attr-defined]
    body = json.loads(posts[0].content)
    assert body["Номер"] == "12"


# ------------------------------------------------------------------
# Мультибазность: выбор базы аргументом database
# ------------------------------------------------------------------


def make_config_second() -> Any:
    """Конфигурация второй тестовой базы."""
    from buh_ai_agent.integrations.onec.config import OnecConnectionConfig

    return OnecConnectionConfig(
        database="filial",
        base_url="http://onec.test/filial/",
        username="user",
        password="test",
        defaults=OnecDefaults(currency_code="643", vat_rate="НДС5"),
        safety=OnecSafety(),
    )


async def test_tool_without_database_and_multiple_bases_asks() -> None:
    """При нескольких базах пустой database — ошибка со списком баз."""
    first = make_clients()
    second_transport = make_transport(make_routes())
    second = OnecClients.single(make_client(second_transport), make_config_second())
    registry = OnecClients((*first.configs, *second.configs), {**first.clients, **second.clients})
    tools = make_onec_tools(registry)
    tool = next(t for t in tools if t.name == "find_nomenclature")
    result = await tool.ainvoke({"query": "Консультация"})
    parsed = json.loads(result)
    assert parsed["ok"] is False
    assert "уточните у пользователя" in parsed["error"]
    assert "ai_agent" in parsed["error"]
    assert "filial" in parsed["error"]


async def test_tool_unknown_database_lists_available() -> None:
    """Неизвестное имя базы — ошибка со списком доступных."""
    tools = make_onec_tools(make_clients())
    tool = next(t for t in tools if t.name == "find_nomenclature")
    result = await tool.ainvoke({"query": "Консультация", "database": "no-such-base"})
    parsed = json.loads(result)
    assert parsed["ok"] is False
    assert "не найдена" in parsed["error"]
    assert "ai_agent" in parsed["error"]


async def test_tool_routes_to_selected_database() -> None:
    """Запрос уходит в базу, выбранную аргументом database."""
    first_transport = make_transport(make_routes())
    second_transport = make_transport(make_routes())
    first = OnecClients.single(make_client(first_transport), make_config())
    second = OnecClients.single(make_client(second_transport), make_config_second())
    registry = OnecClients((*first.configs, *second.configs), {**first.clients, **second.clients})
    tools = make_onec_tools(registry)
    tool = next(t for t in tools if t.name == "find_nomenclature")
    result = await tool.ainvoke({"query": "Консультация", "database": "filial"})
    parsed = json.loads(result)
    assert parsed["ok"] is True, parsed
    assert len(second_transport.seen_requests) > 0  # type: ignore[attr-defined]
    assert len(first_transport.seen_requests) == 0  # type: ignore[attr-defined]


async def test_single_base_works_without_database_argument() -> None:
    """Одна база: аргумент database не нужен."""
    tools = make_onec_tools(make_clients())
    tool = next(t for t in tools if t.name == "find_nomenclature")
    result = await tool.ainvoke({"query": "Консультация"})
    parsed = json.loads(result)
    assert parsed["ok"] is True, parsed


# ------------------------------------------------------------------
# export_document_pdf: официальный PDF через HTTP-сервис печати 1С
# ------------------------------------------------------------------


def make_clients_with_print(
    print_transport: httpx.MockTransport, print_service_url: str = "http://onec.test/hs/print"
) -> OnecClients:
    """Реестр с одной базой, у которой настроен HTTP-сервис печати."""
    config = make_config()
    config.print_service_url = print_service_url
    return OnecClients.single(make_client(make_transport(make_routes())), config)


INVOICE_PDF = b"%PDF-1.4\n%official invoice\n%%EOF\n"
UPD_PDF = b"%PDF-1.4\n%official upd\n%%EOF\n"


async def test_export_document_pdf_attaches_file_to_reply() -> None:
    """PDF счёта прикладывается к ответу диалога, в Tool — только метаданные."""
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=INVOICE_PDF))
    tools = make_onec_tools(make_clients_with_print(transport), print_transport=transport)
    tool = next(t for t in tools if t.name == "export_document_pdf")
    context = DialogContext(chat_id="chat-1", user_id="user-1")
    with bind_dialog_context(context):
        result = await tool.ainvoke({"document_type": "invoice", "ref_key": INVOICE_REF})
    parsed = json.loads(result)
    assert parsed["ok"] is True, parsed
    assert parsed["data"]["name"] == "schet_0000-0000001.pdf"
    assert parsed["data"]["number"] == "0000-0000001"
    assert parsed["data"]["attached_to_reply"] is True
    files = context.take_files()
    assert len(files) == 1
    assert files[0].kind == "invoice"
    assert files[0].name == "schet_0000-0000001.pdf"
    assert files[0].data == INVOICE_PDF
    # Повторный вызов take_files — файлы не хранятся.
    assert context.take_files() == []


async def test_export_document_pdf_upd_from_realization() -> None:
    """УПД печатается из реализации: шаблон realization, имя upd_…."""

    def print_handler(request: httpx.Request) -> httpx.Response:
        assert "/hs/print/realization/" in str(request.url)
        return httpx.Response(200, content=UPD_PDF)

    transport = httpx.MockTransport(print_handler)
    tools = make_onec_tools(make_clients_with_print(transport), print_transport=transport)
    tool = next(t for t in tools if t.name == "export_document_pdf")
    context = DialogContext(chat_id="chat-1", user_id="user-1")
    with bind_dialog_context(context):
        result = await tool.ainvoke({"document_type": "realization", "ref_key": REALIZATION_REF})
    parsed = json.loads(result)
    assert parsed["ok"] is True, parsed
    assert parsed["data"]["name"] == "upd_0000-0000001.pdf"
    assert parsed["data"]["document"] == "realization"
    files = context.take_files()
    assert files[0].kind == "upd"
    assert files[0].data == UPD_PDF


async def test_export_document_pdf_unknown_type() -> None:
    """Неподдержанный тип документа — ошибка со списком доступных."""
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=INVOICE_PDF))
    tools = make_onec_tools(make_clients_with_print(transport), print_transport=transport)
    tool = next(t for t in tools if t.name == "export_document_pdf")
    result = await tool.ainvoke({"document_type": "act", "ref_key": INVOICE_REF})
    parsed = json.loads(result)
    assert parsed["ok"] is False
    assert "invoice, realization" in parsed["error"]


async def test_export_document_pdf_service_error() -> None:
    """Ошибка сервиса печати возвращается с текстом 1С."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(500, text="Ошибка печати: не найден макет")
    )
    tools = make_onec_tools(make_clients_with_print(transport), print_transport=transport)
    tool = next(t for t in tools if t.name == "export_document_pdf")
    result = await tool.ainvoke({"document_type": "invoice", "ref_key": INVOICE_REF})
    parsed = json.loads(result)
    assert parsed["ok"] is False
    assert "не найден макет" in parsed["error"]


async def test_export_document_pdf_without_service_configured() -> None:
    """Сервис печати не настроен — понятная ошибка с направлением на инструкцию."""
    tools = make_onec_tools(make_clients())
    tool = next(t for t in tools if t.name == "export_document_pdf")
    result = await tool.ainvoke({"document_type": "invoice", "ref_key": INVOICE_REF})
    parsed = json.loads(result)
    assert parsed["ok"] is False
    assert "не настроен" in parsed["error"]
    assert "print_service_url" in parsed["error"]


# ------------------------------------------------------------------
# create_sales_invoice: официальные PDF прикладываются к ответу
# ------------------------------------------------------------------


def print_transport_two_forms() -> httpx.MockTransport:
    """Транспорт сервиса печати: PDF счёта и PDF УПД по своим путям."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/hs/print/invoice/" in url:
            return httpx.Response(200, content=INVOICE_PDF)
        if "/hs/print/realization/" in url:
            return httpx.Response(200, content=UPD_PDF)
        return httpx.Response(404, text="нет шаблона")

    return httpx.MockTransport(handler)


async def test_create_sales_invoice_attaches_official_pdfs() -> None:
    """При создании счёта PDF счёта и УПД прикладываются к ответу, черновиков нет."""
    print_transport = print_transport_two_forms()
    tools = make_onec_tools(
        make_clients_with_print(print_transport), print_transport=print_transport
    )
    tool = next(t for t in tools if t.name == "create_sales_invoice")
    context = DialogContext(chat_id="chat-1", user_id="user-1")
    with bind_dialog_context(context):
        result = await tool.ainvoke(
            {
                "counterparty_key": CONTRACTOR_REF,
                "contract_key": CONTRACT_REF,
                "lines": [
                    {"name": "Разработка ПО", "quantity": 1, "price": 100000, "is_service": True}
                ],
                "vat_rate": "НДС5",
            }
        )
    parsed = json.loads(result)
    assert parsed["ok"] is True, parsed
    assert parsed["data"]["invoice_pdf"]["name"] == "schet_0000-0000001.pdf"
    assert parsed["data"]["upd_pdf"]["name"] == "upd_0000-0000001.pdf"
    assert "invoice_draft" not in parsed["data"]
    assert "upd_draft" not in parsed["data"]
    files = context.take_files()
    assert [file.kind for file in files] == ["invoice", "upd"]
    assert files[0].data == INVOICE_PDF
    assert files[1].data == UPD_PDF


async def test_create_sales_invoice_pdf_failure_falls_back_to_drafts() -> None:
    """Ошибка сервиса печати не ломает создание: черновики + текст ошибки."""
    print_transport = httpx.MockTransport(
        lambda request: httpx.Response(500, text="Ошибка печати: не найден макет")
    )
    tools = make_onec_tools(
        make_clients_with_print(print_transport), print_transport=print_transport
    )
    tool = next(t for t in tools if t.name == "create_sales_invoice")
    context = DialogContext(chat_id="chat-1", user_id="user-1")
    with bind_dialog_context(context):
        result = await tool.ainvoke(
            {
                "counterparty_key": CONTRACTOR_REF,
                "contract_key": CONTRACT_REF,
                "lines": [
                    {"name": "Разработка ПО", "quantity": 1, "price": 100000, "is_service": True}
                ],
                "vat_rate": "НДС5",
            }
        )
    parsed = json.loads(result)
    assert parsed["ok"] is True, parsed
    assert "invoice_draft" in parsed["data"]
    assert "upd_draft" in parsed["data"]
    assert "не найден макет" in parsed["data"]["pdf_errors"]
    assert context.take_files() == []
