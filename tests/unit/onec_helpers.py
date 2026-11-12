"""Фейковый httpx-транспорт 1С и примеры ответов OData для тестов."""

from typing import Any
from urllib.parse import unquote

import httpx

from buh_ai_agent.integrations.onec.client import OnecClient

ORG_REF = "aa0ad33a-dba9-11f1-9a8f-a02942832943"
RUB_REF = "ea9005c5-7320-11ec-95fd-0242ac120003"
CONTRACTOR_REF = "35a7be11-7321-11ec-8111-0242ac120003"
CONTRACT_REF = "3c5f2b9c-0000-11f1-9a8f-a02942832943"
NOMENCLATURE_REF = "5f1e2d3c-0000-11ec-8111-0242ac120003"
BANK_ACCOUNT_REF = "a44d1e7b-dc3a-11f1-9a8f-a02942832943"
INVOICE_REF = "7a1b2c3d-0000-11f1-9a8f-a02942832943"
REALIZATION_REF = "8b2c3d4e-0000-11f1-9a8f-a02942832943"
VAT_INVOICE_REF = "9c3d4e5f-0000-11f1-9a8f-a02942832943"
UNIT_REF = "34394c2c-7321-11ec-8111-0242ac120003"
WAREHOUSE_REF = "34394c2a-7321-11ec-8111-0242ac120003"
SERVICE_KIND_REF = "316196ce-7321-11ec-8111-0242ac120003"
GOODS_KIND_REF = "34394c2d-7321-11ec-8111-0242ac120003"
ACCOUNT_SETTLEMENT_REF = "11111111-1111-1111-1111-111111111111"
ACCOUNT_REVENUE_REF = "22222222-2222-2222-2222-222222222222"
ACCOUNT_EXPENSES_REF = "33333333-3333-3333-3333-333333333333"
ACCOUNT_VAT_REF = "44444444-4444-4444-4444-444444444444"
ACCOUNT_GOODS_REF = "55555555-5555-5555-5555-555555555555"

METADATA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<edmx:Edmx xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">
  <edmx:DataServices>
    <Schema xmlns="http://docs.oasis-open.org/odata/ns/edm">
      <EnumType Name="СтавкиНДС">
        <Member Name="БезНДС"/>
        <Member Name="НДС0"/>
        <Member Name="НДС5"/>
        <Member Name="НДС10"/>
        <Member Name="НДС10_110"/>
        <Member Name="НДС18"/>
        <Member Name="НДС18_118"/>
        <Member Name="НДС20"/>
        <Member Name="НДС20_120"/>
      </EnumType>
      <EnumType Name="ВидыСтавокНДС">
        <Member Name="БезНДС"/>
        <Member Name="Нулевая"/>
        <Member Name="Общая"/>
      </EnumType>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>"""


def odata_error(status: int, code: str, message: str) -> httpx.Response:
    """Строит ответ с ошибкой OData 1С."""
    return httpx.Response(
        status,
        json={"odata.error": {"code": code, "message": {"lang": "ru", "value": message}}},
        request=httpx.Request("GET", "http://onec.test/"),
    )


def entity_ref(ref_key: str, code: str = "00-000001", number: str = "") -> dict[str, Any]:
    """Тело созданного объекта: Ref_Key + присвоенные Code/Number."""
    data: dict[str, Any] = {"Ref_Key": ref_key, "Code": code}
    if number:
        data["Number"] = number
    return data


def organization_row(**overrides: Any) -> dict[str, Any]:
    """Строка организации."""
    data: dict[str, Any] = {
        "Ref_Key": ORG_REF,
        "Description": "Агентов Т. Т. ИП",
        "ИНН": "1209328142",
        "КПП": "",
        "ОсновнойБанковскийСчет_Key": BANK_ACCOUNT_REF,
        "IsFolder": False,
    }
    data.update(overrides)
    return data


def counterparty_row(**overrides: Any) -> dict[str, Any]:
    """Строка контрагента."""
    data: dict[str, Any] = {
        "Ref_Key": CONTRACTOR_REF,
        "Description": "ООО Ромашка",
        "ИНН": "7701234567",
        "КПП": "770101001",
        "НаименованиеПолное": "ООО «Ромашка»",
        "ЮридическоеФизическоеЛицо": "ЮридическоеЛицо",
        "IsFolder": False,
        "DeletionMark": False,
    }
    data.update(overrides)
    return data


def contract_row(**overrides: Any) -> dict[str, Any]:
    """Строка договора."""
    data: dict[str, Any] = {
        "Ref_Key": CONTRACT_REF,
        "Description": "4 от 10.11.2026",
        "Номер": "4",
        "Дата": "2026-11-10T00:00:00",
        "ВидДоговора": "СПокупателем",
        "Организация_Key": ORG_REF,
        "ВалютаВзаиморасчетов_Key": RUB_REF,
        "ДоговорЗакрыт": False,
        "Owner_Key": CONTRACTOR_REF,
        "DeletionMark": False,
    }
    data.update(overrides)
    return data


def nomenclature_row(**overrides: Any) -> dict[str, Any]:
    """Строка номенклатуры."""
    data: dict[str, Any] = {
        "Ref_Key": NOMENCLATURE_REF,
        "Description": "Консультация",
        "НаименованиеПолное": "Консультация, час",
        "Артикул": "",
        "Услуга": True,
        "IsFolder": False,
        "DeletionMark": False,
        "ЕдиницаИзмерения_Key": UNIT_REF,
        "ВидСтавкиНДС": "Общая",
    }
    data.update(overrides)
    return data


def invoice_row(**overrides: Any) -> dict[str, Any]:
    """Шапка счёта на оплату покупателю."""
    data: dict[str, Any] = {
        "Ref_Key": INVOICE_REF,
        "Number": "0000-0000001",
        "Date": "2026-11-10T00:00:00",
        "Posted": False,
        "СуммаДокумента": 100000,
        "Контрагент_Key": CONTRACTOR_REF,
        "ДоговорКонтрагента_Key": CONTRACT_REF,
        "Организация_Key": ORG_REF,
        "ВидОперации": "ТоварыИУслуги",
        "СуммаВключаетНДС": True,
        "СтруктурнаяЕдиница_Key": BANK_ACCOUNT_REF,
    }
    data.update(overrides)
    return data


def invoice_line_row(**overrides: Any) -> dict[str, Any]:
    """Строка табличной части `_Товары` счёта."""
    data: dict[str, Any] = {
        "LineNumber": 1,
        "Номенклатура": NOMENCLATURE_REF,
        "Номенклатура_Type": "StandardODATA.Catalog_Номенклатура",
        "Содержание": "Консультация",
        "Количество": 8,
        "Цена": 12500,
        "Сумма": 100000,
        "СтавкаНДС": "НДС20",
        "СуммаНДС": 16666.67,
        "ПроцентСкидки": 0,
        "СуммаСкидки": 0,
    }
    data.update(overrides)
    return data


def realization_row(**overrides: Any) -> dict[str, Any]:
    """Шапка реализации товаров и услуг."""
    data: dict[str, Any] = {
        "Ref_Key": REALIZATION_REF,
        "Number": "0000-0000001",
        "Date": "2026-11-10T00:00:00",
        "Posted": False,
        "СуммаДокумента": 100000,
        "Контрагент_Key": CONTRACTOR_REF,
        "ДоговорКонтрагента_Key": CONTRACT_REF,
        "Организация_Key": ORG_REF,
        "ВидОперации": "Услуги",
        "СуммаВключаетНДС": True,
        "СчетНаОплатуПокупателю_Key": INVOICE_REF,
        "БанковскийСчетОрганизации_Key": BANK_ACCOUNT_REF,
    }
    data.update(overrides)
    return data


def realization_service_line_row(**overrides: Any) -> dict[str, Any]:
    """Строка табличной части `Услуги` реализации."""
    data: dict[str, Any] = {
        "LineNumber": 1,
        "Номенклатура_Key": NOMENCLATURE_REF,
        "Содержание": "Консультация",
        "Количество": 8,
        "Цена": 12500,
        "Сумма": 100000,
        "СтавкаНДС": "НДС20",
        "СуммаНДС": 16666.67,
        "СчетДоходов_Key": ACCOUNT_REVENUE_REF,
        "СчетРасходов_Key": ACCOUNT_EXPENSES_REF,
        "СчетУчетаНДСПоРеализации_Key": ACCOUNT_VAT_REF,
        "СчетНаОплатуПокупателю_Key": INVOICE_REF,
    }
    data.update(overrides)
    return data


def facture_row(**overrides: Any) -> dict[str, Any]:
    """Шапка счёта-фактуры выданного."""
    data: dict[str, Any] = {
        "Ref_Key": VAT_INVOICE_REF,
        "Number": "0000-0000001",
        "Date": "2026-11-10T00:00:00",
        "Posted": False,
        "СуммаДокумента": 100000,
        "Контрагент_Key": CONTRACTOR_REF,
        "Организация_Key": ORG_REF,
        "ВидСчетаФактуры": "НаРеализацию",
        "СуммаВключаетНДС": True,
        "ДокументыОснования": [
            {
                "LineNumber": 1,
                "ДокументОснование": REALIZATION_REF,
                "ДокументОснование_Type": "StandardODATA.Document_РеализацияТоваровУслуг",
            }
        ],
    }
    data.update(overrides)
    return data


ACCOUNTS_ROWS = [
    {"Ref_Key": ACCOUNT_SETTLEMENT_REF, "Code": "62.01"},
    {"Ref_Key": ACCOUNT_REVENUE_REF, "Code": "90.01.1"},
    {"Ref_Key": ACCOUNT_EXPENSES_REF, "Code": "90.02.1"},
    {"Ref_Key": ACCOUNT_VAT_REF, "Code": "90.03"},
    {"Ref_Key": ACCOUNT_GOODS_REF, "Code": "41"},
]


def make_client(transport: httpx.MockTransport) -> OnecClient:
    """Клиент 1С на тестовом транспорте (без реального подключения)."""
    return OnecClient("http://onec.test/odata/standard.odata/", "user", "pass", transport=transport)


def make_transport(routes: dict[tuple[str, str], Any]) -> httpx.MockTransport:
    """Транспорт 1С: словарь {(METHOD, path-суффикс): ответ}.

    Args:
        routes: Ответ в виде httpx.Response, dict (JSON) или list (value=).
            Совпадение — по вхождению path-суффикса в URL запроса
            (URL сравнивается в раскодированном виде, чтобы совпадали
            кириллические имена EntitySet).

    Returns:
        httpx.MockTransport со списком запросов в `seen_requests`.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        url = unquote(str(request.url))
        matches = [
            (method, suffix, result)
            for (method, suffix), result in routes.items()
            if request.method == method and suffix in url
        ]
        import os

        if os.environ.get("DEBUG_TRANSPORT"):
            print("URL:", url[:80], "matches:", [(s[:30]) for _, s, _ in matches])
        if matches:
            # Самый длинный суффикс — точный маршрут (guid'...') вместо
            # общего EntitySet.
            _, _, result = max(matches, key=lambda m: len(m[1]))
            if callable(result):
                return result(request)
            if isinstance(result, httpx.Response):
                return result
            if isinstance(result, list):
                return httpx.Response(200, json={"value": result})
            return httpx.Response(200, json=result)
        return httpx.Response(404, text="<html>not found</html>")

    transport = httpx.MockTransport(handler)
    transport.seen_requests = seen  # type: ignore[attr-defined]
    return transport
