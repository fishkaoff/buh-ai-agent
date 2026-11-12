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

from buh_ai_agent.integrations.onec.config import OnecDefaults, OnecSafety
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
    client = make_client(transport)
    tools = make_onec_tools(client, make_config())
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
    assert all(isinstance(t, BaseTool) for t in tools)


async def test_find_counterparty() -> None:
    """find_counterparty возвращает найденного контрагента."""
    transport = make_transport(make_routes())
    client = make_client(transport)
    tools = make_onec_tools(client, make_config())
    tool = next(t for t in tools if t.name == "find_counterparty")
    result = await tool.ainvoke({"name": "Ромашка"})
    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["data"]["count"] == 1
    assert parsed["data"]["counterparties"][0]["ref_key"] == CONTRACTOR_REF


async def test_find_counterparty_requires_query() -> None:
    """find_counterparty без ИНН и наименования — ошибка."""
    transport = make_transport(make_routes())
    client = make_client(transport)
    tools = make_onec_tools(client, make_config())
    tool = next(t for t in tools if t.name == "find_counterparty")
    result = await tool.ainvoke({"name": "", "inn": ""})
    parsed = json.loads(result)
    assert parsed["ok"] is False
    assert "Укажите наименование" in parsed["error"]


async def test_find_nomenclature() -> None:
    """find_nomenclature возвращает найденные позиции."""
    transport = make_transport(make_routes())
    client = make_client(transport)
    tools = make_onec_tools(client, make_config())
    tool = next(t for t in tools if t.name == "find_nomenclature")
    result = await tool.ainvoke({"query": "Консультация"})
    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert parsed["data"]["count"] == 1
    assert parsed["data"]["items"][0]["ref_key"] == NOMENCLATURE_REF


async def test_list_allowed_vat_rates() -> None:
    """list_allowed_vat_rates возвращает ставки из $metadata."""
    transport = make_transport(make_routes())
    client = make_client(transport)
    tools = make_onec_tools(client, make_config())
    tool = next(t for t in tools if t.name == "list_allowed_vat_rates")
    result = await tool.ainvoke({})
    parsed = json.loads(result)
    assert parsed["ok"] is True
    assert "НДС5" in parsed["data"]["rates"] or "НДС20" in parsed["data"]["rates"]


async def test_create_sales_invoice_full_scenario() -> None:
    """Полный сценарий: счёт → реализация → счёт-фактура (УПД)."""
    transport = make_transport(make_routes())
    client = make_client(transport)
    tools = make_onec_tools(client, make_config())
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
    client = make_client(transport)
    tools = make_onec_tools(client, make_config())
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
    client = make_client(transport)
    tools = make_onec_tools(client, make_config())
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
    client = make_client(transport)
    tools = make_onec_tools(client, make_config())
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
    client = make_client(transport)
    tools = make_onec_tools(client, make_config())
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
    client = make_client(transport)
    tools = make_onec_tools(client, make_config())
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
