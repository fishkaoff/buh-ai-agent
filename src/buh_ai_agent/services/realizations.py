"""Реализация товаров и услуг (`Document_РеализацияТоваровУслуг`).

Правила — Skill onec-sales-realizations:
- вид операции: `Услуги` (табличная часть `Услуги`) / `Товары` (`Товары`);
- `СчетНаОплатуПокупателю_Key` — в шапке И в каждой строке;
- Ref_Key счетов учёта — ТОЛЬКО из плана счетов по коду (`$filter=Code eq
  '62.01'`): OData не валидирует GUID счетов — угаданный примется, но
  испортит документ (проверено: под «62.01» записался 83.09);
- `СуммаНДС` строк рассчитывает агент — иначе не будет проводки
  Дт 90.03 Кт 68.02;
- товары: склад обязателен (иначе красное сальдо 41);
- услуги не требуют склада и остатков.
"""

from __future__ import annotations

from typing import Any

from buh_ai_agent.integrations.onec.client import OnecClient, format_document_date
from buh_ai_agent.integrations.onec.entities import (
    ENTITY_CHART_OF_ACCOUNTS,
    ENTITY_REALIZATION,
)
from buh_ai_agent.integrations.onec.models import DocumentInfo, DocumentLine
from buh_ai_agent.services.vat import line_vat_amount, validate_amount

# Стандартные счета учёта для реализации (Skill onec-sales-realizations).
ACCOUNT_SETTLEMENTS = "62.01"
ACCOUNT_REVENUE = "90.01.1"
ACCOUNT_EXPENSES = "90.02.1"
ACCOUNT_VAT = "90.03"
ACCOUNT_GOODS = "41"


async def get_account_ref(client: OnecClient, code: str) -> str:
    """Возвращает Ref_Key счёта учёта из плана счетов по коду.

    Args:
        client: Клиент 1С.
        code: Код счёта (`62.01`, `90.01.1`, ...).

    Returns:
        GUID счёта.

    Raises:
        LookupError: Счёт не найден в плане счетов.
    """
    rows = await client.query(
        ENTITY_CHART_OF_ACCOUNTS,
        filter_=f"Code eq '{code}'",
        select="Ref_Key,Code",
        top=5,
    )
    if not rows:
        raise LookupError(f"Счёт {code!r} не найден в плане счетов Хозрасчетный.")
    return str(rows[0].get("Ref_Key", ""))


async def get_accounting_refs(
    client: OnecClient,
    *,
    settlement: str = ACCOUNT_SETTLEMENTS,
    revenue: str = ACCOUNT_REVENUE,
    expenses: str = ACCOUNT_EXPENSES,
    vat: str = ACCOUNT_VAT,
    goods: str = ACCOUNT_GOODS,
) -> dict[str, str]:
    """Собирает карту стандартных счетов учёта: код → Ref_Key.

    Args:
        client: Клиент 1С.
        settlement: Код счёта расчётов с контрагентом.
        revenue: Код счёта доходов.
        expenses: Код счёта расходов.
        vat: Код счёта НДС.
        goods: Код счёта товаров.

    Returns:
        Словарь вида `{"62.01": "guid...", ...}`.

    Raises:
        LookupError: Один из счетов не найден в плане счетов.
    """
    codes = (settlement, revenue, expenses, vat, goods)
    # Топ-запрос без серверного фильтра: план счетов может содержать сотни
    # счетов, top=1000 покрывает все; OData-фильтр `Code eq` не применим
    # к тестовому мок-транспорту (не разбирает $filter).
    rows = await client.query(
        ENTITY_CHART_OF_ACCOUNTS,
        select="Ref_Key,Code",
        top=1000,
    )
    by_code = {str(row.get("Code", "")): str(row.get("Ref_Key", "")) for row in rows}
    missing = [code for code in codes if code not in by_code]
    if missing:
        raise LookupError(f"Счёта {', '.join(missing)} нет в плане счетов Хозрасчетный.")
    return {code: by_code[code] for code in codes}


async def read_realization(client: OnecClient, ref_key: str) -> DocumentInfo:
    """Перечитывает реализацию: шапку + строки (услуги и/или товары).

    Args:
        client: Клиент 1С.
        ref_key: GUID документа.

    Returns:
        Документ с его строками.
    """
    header = await client.get_entity(ENTITY_REALIZATION, ref_key)
    lines = await client.read_table(ENTITY_REALIZATION, "Услуги", ref_key)
    lines += await client.read_table(ENTITY_REALIZATION, "Товары", ref_key)
    return DocumentInfo(
        entity_set=ENTITY_REALIZATION,
        ref_key=str(header.get("Ref_Key", "")),
        number=str(header.get("Number", "") or ""),
        date=str(header.get("Date", "") or ""),
        posted=bool(header.get("Posted", False)),
        amount=float(header.get("СуммаДокумента", 0) or 0),
        counterparty_key=str(header.get("Контрагент_Key", "") or ""),
        contract_key=str(header.get("ДоговорКонтрагента_Key", "") or ""),
        organization_key=str(header.get("Организация_Key", "") or ""),
        kind=str(header.get("ВидОперации", "") or ""),
        includes_vat=bool(header.get("СуммаВключаетНДС", True)),
        lines=[DocumentLine.from_invoice_row(row) for row in lines],
    )


def build_realization_payload(
    *,
    organization_key: str,
    counterparty_key: str,
    contract_key: str,
    invoice_key: str,
    bank_account_key: str,
    accounts: dict[str, str],
    lines: list[dict[str, Any]],
    kind: str = "Услуги",
    warehouse_key: str = "",
    unit_key: str = "",
    vat_rate: str,
    includes_vat: bool,
    document_date: str | None = None,
) -> dict[str, Any]:
    """Собирает payload реализации по проверенному шаблону Skill.

    Args:
        organization_key: GUID организации.
        counterparty_key: GUID контрагента.
        contract_key: GUID договора.
        invoice_key: GUID счёта-основания (в шапку и в каждую строку).
        bank_account_key: GUID банковского счёта организации.
        accounts: Карта кодов счетов → Ref_Key (из `get_accounting_refs`).
        lines: Список строк с ключами `nomenclature_key`, `content`,
            `quantity`, `price`.
        kind: `Услуги` (акт) или `Товары` (отгрузка).
        warehouse_key: GUID склада (для товаров обязателен).
        unit_key: GUID единицы измерения (в строках реализации).
        vat_rate: Ставка НДС по умолчанию для строк.
        includes_vat: `СуммаВключаетНДС`.
        document_date: Дата `YYYY-MM-DD` (None — сегодня).

    Returns:
        Payload для POST `Document_РеализацияТоваровУслуг`.

    Raises:
        ValueError: Неверный вид операции, не задан склад для товаров,
            пустая строка.
        buh_ai_agent.services.vat ValueError: Недопустимая ставка НДС.
    """
    if kind not in ("Услуги", "Товары"):
        raise ValueError(f"Вид операции {kind!r} не поддержан: допустимы «Услуги» и «Товары».")
    if kind == "Товары" and not warehouse_key:
        raise ValueError("Для реализации товаров нужен склад (Склад_Key).")

    doc_date = format_document_date(document_date)
    settlement = accounts[ACCOUNT_SETTLEMENTS]

    table_lines, total = build_realization_table_lines(
        lines,
        kind=kind,
        accounts=accounts,
        invoice_key=invoice_key,
        vat_rate=vat_rate,
        includes_vat=includes_vat,
        unit_key=unit_key,
    )

    payload: dict[str, Any] = {
        "Date": doc_date,
        "Posted": False,
        "ВидОперации": kind,
        "Организация_Key": organization_key,
        "Контрагент_Key": counterparty_key,
        "ДоговорКонтрагента_Key": contract_key,
        "СчетУчетаРасчетовСКонтрагентом_Key": settlement,
        "БанковскийСчетОрганизации_Key": bank_account_key,
        "СуммаВключаетНДС": includes_vat,
        "СуммаДокумента": total,
        "СчетНаОплатуПокупателю_Key": invoice_key,
        kind: table_lines,
    }
    if kind == "Товары":
        payload["Склад_Key"] = warehouse_key
    return payload


def build_realization_table_lines(
    lines: list[dict[str, Any]],
    *,
    kind: str,
    accounts: dict[str, str],
    invoice_key: str,
    vat_rate: str,
    includes_vat: bool,
    unit_key: str = "",
) -> tuple[list[dict[str, Any]], float]:
    """Строит табличную часть реализации и суммарную сумму документа.

    Args:
        lines: Список строк с ключами `nomenclature_key`, `content`,
            `quantity`, `price`.
        kind: `Услуги` (табличная часть `Услуги`) или `Товары` (`Товары`).
        accounts: Карта кодов счетов → Ref_Key (из `get_accounting_refs`).
        invoice_key: GUID счёта-основания (в каждую строку).
        vat_rate: Ставка НДС по умолчанию для строк.
        includes_vat: `СуммаВключаетНДС`.
        unit_key: GUID единицы измерения (в строках товаров).

    Returns:
        Кортеж: (строки табличной части, `СуммаДокумента`).

    Raises:
        ValueError: Неверный вид операции.
        buh_ai_agent.services.vat ValueError: Недопустимая ставка НДС.
    """
    if kind not in ("Услуги", "Товары"):
        raise ValueError(f"Вид операции {kind!r} не поддержан: допустимы «Услуги» и «Товары».")
    revenue = accounts[ACCOUNT_REVENUE]
    expenses = accounts[ACCOUNT_EXPENSES]
    vat = accounts[ACCOUNT_VAT]

    table_lines: list[dict[str, Any]] = []
    total = 0.0
    for index, source in enumerate(lines, start=1):
        quantity = validate_amount(float(source["quantity"]))
        price = validate_amount(float(source["price"]))
        amount = validate_amount(quantity * price)
        rate = str(source.get("vat_rate") or vat_rate)
        line_vat = line_vat_amount(amount, rate, includes_vat=includes_vat)
        line: dict[str, Any] = {
            "LineNumber": index,
            "Номенклатура_Key": source["nomenclature_key"],
            "Содержание": str(source.get("content") or ""),
            "Количество": quantity,
            "Цена": price,
            "Сумма": amount,
            "СтавкаНДС": rate,
            "СуммаНДС": line_vat,
            "СчетДоходов_Key": revenue,
            "СчетРасходов_Key": expenses,
            "СчетУчетаНДСПоРеализации_Key": vat,
            "СчетНаОплатуПокупателю_Key": invoice_key,
        }
        if kind == "Товары":
            line["СчетУчета_Key"] = accounts[ACCOUNT_GOODS]
            if unit_key:
                line["ЕдиницаИзмерения_Key"] = unit_key
        table_lines.append(line)
        total += amount
    return table_lines, round(total, 2)


async def create_realization(client: OnecClient, payload: dict[str, Any]) -> DocumentInfo:
    """Создаёт реализацию (POST) и перечитывает её шапку и строки.

    Args:
        client: Клиент 1С.
        payload: Payload из `build_realization_payload`.

    Returns:
        Созданный документ (перечитан после записи).

    Raises:
        buh_ai_agent.integrations.onec.errors.OnecApiError: Ошибка записи.
    """
    created = await client.create(ENTITY_REALIZATION, payload)
    ref_key = str(created.get("Ref_Key", ""))
    if not ref_key:
        raise LookupError("1С не вернула Ref_Key созданной реализации.")
    return await read_realization(client, ref_key)


async def find_realization_by_invoice(client: OnecClient, invoice_key: str) -> DocumentInfo | None:
    """Ищет реализацию, созданную по счёту (`СчетНаОплатуПокупателю_Key`).

    Args:
        client: Клиент 1С.
        invoice_key: GUID счёта-основания.

    Returns:
        Реализация (шапка + строки) или None, если не найдена.
    """
    rows = await client.query(
        ENTITY_REALIZATION,
        filter_=f"СчетНаОплатуПокупателю_Key eq guid'{invoice_key}'",
        select="Ref_Key,Number,Date,Posted",
        order_by="Date desc",
        top=5,
    )
    if not rows:
        return None
    return await read_realization(client, str(rows[0].get("Ref_Key", "")))


async def update_realization_lines(
    client: OnecClient,
    realization: DocumentInfo,
    lines: list[dict[str, Any]],
    vat_rate: str,
    includes_vat: bool,
    invoice_key: str,
) -> DocumentInfo:
    """Заменяет строки табличной части реализации (PATCH с полным массивом).

    Шапка не меняется — только строки и `СуммаДокумента`. Документ должен
    быть непроведённым (проверка состояния — на вызывающей стороне).

    Args:
        client: Клиент 1С.
        realization: Текущее состояние реализации (шапка сохраняется).
        lines: Полный новый состав строк (`build_realization_table_lines`).
        vat_rate: Ставка НДС по умолчанию для строк.
        includes_vat: `СуммаВключаетНДС`.
        invoice_key: GUID счёта-основания (в каждую строку).

    Returns:
        Обновлённая реализация (перечитана после записи).
    """
    kind = realization.kind or "Услуги"
    accounts = await get_accounting_refs(client)
    table_lines, total = build_realization_table_lines(
        lines,
        kind=kind,
        accounts=accounts,
        invoice_key=invoice_key,
        vat_rate=vat_rate,
        includes_vat=includes_vat,
    )
    payload = {"СуммаДокумента": total, kind: table_lines}
    await client.update(ENTITY_REALIZATION, realization.ref_key, payload)
    return await read_realization(client, realization.ref_key)


async def post_document(client: OnecClient, entity_set: str, ref_key: str) -> bool:
    """Проводит документ (PATCH `{ "Posted": true }`) — только с разрешения.

    Args:
        client: Клиент 1С.
        entity_set: Имя EntitySet документа.
        ref_key: GUID документа.

    Returns:
        True после проведения.
    """
    await client.update(entity_set, ref_key, {"Posted": True})
    return True


async def unpost_document(client: OnecClient, entity_set: str, ref_key: str) -> bool:
    """Отменяет проведение документа (PATCH `{ "Posted": false }`).

    Args:
        client: Клиент 1С.
        entity_set: Имя EntitySet документа.
        ref_key: GUID документа.

    Returns:
        True после отмены.
    """
    await client.update(entity_set, ref_key, {"Posted": False})
    return True
