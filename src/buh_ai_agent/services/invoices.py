"""Счета на оплату покупателю (`Document_СчетНаОплатуПокупателю`).

Правила — Skill onec-sales-invoices:
- `Сумма` строки = Количество × Цена (до копеек); `СуммаДокумента` = Σ строк;
- `СуммаНДС` строк рассчитывает агент (1С через OData не пересчитывает);
- при `СуммаВключаетНДС=true` → `Сумма × ставка/(100+ставка)`;
- «Без НДС»: `ДокументБезНДС: true` + строки `СтавкаНДС: "БезНДС"`,
  `СуммаНДС: 0`;
- `СтруктурнаяЕдиница_Key` — банковский счёт организации («реквизиты
  для оплаты»);
- `Number` документа 1С присваивает сама — не отправлять;
- антидубликат: поиск счетов контрагента за период с равной суммой;
- строки — табличная часть `_Товары` (вмещает товары и услуги),
  номенклатура — составная ссылка (`Номенклатура` + `Номенклатура_Type`).
"""

from __future__ import annotations

from typing import Any

from buh_ai_agent.integrations.onec.client import OnecClient, format_document_date
from buh_ai_agent.integrations.onec.entities import ENTITY_SALES_INVOICE
from buh_ai_agent.integrations.onec.models import DocumentInfo, DocumentLine
from buh_ai_agent.services.vat import line_vat_amount, validate_amount

NOMENCLATURE_TYPE = "StandardODATA.Catalog_Номенклатура"


async def read_invoice(client: OnecClient, ref_key: str) -> DocumentInfo:
    """Перечитывает счёт: шапку + строки табличной части `_Товары`.

    Args:
        client: Клиент 1С.
        ref_key: GUID счёта.

    Returns:
        Документ с его строками.

    Raises:
        buh_ai_agent.integrations.onec.errors.OnecApiError: Ошибка чтения.
    """
    header = await client.get_entity(ENTITY_SALES_INVOICE, ref_key)
    lines = await client.read_table(ENTITY_SALES_INVOICE, "Товары", ref_key)
    return DocumentInfo(
        entity_set=ENTITY_SALES_INVOICE,
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


async def find_duplicate_invoices(
    client: OnecClient,
    counterparty_key: str,
    amount: float | None = None,
    *,
    since_date: str,
) -> list[DocumentInfo]:
    """Ищет счёта этого контрагента за период (антидубликат).

    Args:
        client: Клиент 1С.
        counterparty_key: GUID контрагента.
        amount: Сумма для точного совпадения; None — любая сумма.
        since_date: Дата `YYYY-MM-DD` — начало периода.

    Returns:
        Список счетов-кандидатов на дубликат.
    """
    rows = await client.query(
        ENTITY_SALES_INVOICE,
        filter_=(
            f"Контрагент_Key eq guid'{counterparty_key}' "
            f"and Date ge datetime'{since_date}T00:00:00'"
        ),
        select="Ref_Key,Number,Date,Posted,СуммаДокумента",
        order_by="Date desc",
        top=20,
    )
    invoices_found = [
        DocumentInfo(
            entity_set=ENTITY_SALES_INVOICE,
            ref_key=str(row.get("Ref_Key", "")),
            number=str(row.get("Number", "") or ""),
            date=str(row.get("Date", "") or ""),
            posted=bool(row.get("Posted", False)),
            amount=float(row.get("СуммаДокумента", 0) or 0),
        )
        for row in rows
    ]
    if amount is None:
        return invoices_found
    target = round(amount, 2)
    return [doc for doc in invoices_found if round(doc.amount, 2) == target]


def build_table_lines(
    lines: list[dict[str, Any]],
    vat_rate: str,
    includes_vat: bool,
) -> tuple[list[dict[str, Any]], float]:
    """Строит табличную часть счёта и суммарную сумму документа.

    `СуммаНДС` каждой строки рассчитывается по правилам Skill
    onec-validation (1С через OData не пересчитывает).

    Args:
        lines: Список строк с ключами: `nomenclature_key`, `content`,
            `quantity`, `price` (и опционально `vat_rate` — переопределение
            ставки конкретной строки).
        vat_rate: Ставка НДС по умолчанию для строк.
        includes_vat: `СуммаВключаетНДС`.

    Returns:
        Кортеж: (строки для `Товары`, `СуммаДокумента`).

    Raises:
        ValueError: Пустая строка, не задана номенклатура или сумма.
        buh_ai_agent.services.vat ValueError: Недопустимая ставка НДС.
    """
    table_lines: list[dict[str, Any]] = []
    total = 0.0
    for index, source in enumerate(lines, start=1):
        quantity = validate_amount(float(source["quantity"]))
        price = validate_amount(float(source["price"]))
        amount = validate_amount(quantity * price)
        rate = str(source.get("vat_rate") or vat_rate)
        line_vat = line_vat_amount(amount, rate, includes_vat=includes_vat)
        table_lines.append(
            {
                "LineNumber": index,
                "Номенклатура": source["nomenclature_key"],
                "Номенклатура_Type": NOMENCLATURE_TYPE,
                "Содержание": str(source.get("content") or ""),
                "Количество": quantity,
                "Цена": price,
                "Сумма": amount,
                "ПроцентСкидки": 0,
                "СуммаСкидки": 0,
                "СтавкаНДС": rate,
                "СуммаНДС": line_vat,
            }
        )
        total += amount
    return table_lines, round(total, 2)


def build_invoice_payload(
    *,
    organization_key: str,
    counterparty_key: str,
    contract_key: str,
    bank_account_key: str,
    currency_key: str,
    lines: list[dict[str, Any]],
    vat_rate: str,
    includes_vat: bool,
    document_date: str | None = None,
) -> dict[str, Any]:
    """Собирает payload счёта по проверенному шаблону Skill onec-sales-invoices.

    Args:
        organization_key: GUID организации.
        counterparty_key: GUID контрагента.
        contract_key: GUID договора.
        bank_account_key: GUID банковского счёта (`СтруктурнаяЕдиница_Key`).
        currency_key: GUID валюты документа.
        lines: Список строк с ключами: `nomenclature_key`, `content`,
            `quantity`, `price` (и опционально `vat_rate` — переопределение
            ставки конкретной строки).
        vat_rate: Ставка НДС по умолчанию для строк.
        includes_vat: `СуммаВключаетНДС`.
        document_date: Дата `YYYY-MM-DD` (None — сегодня).

    Returns:
        Payload для POST `Document_СчетНаОплатуПокупателю`.

    Raises:
        ValueError: Пустая строка, не задана номенклатура или сумма.
        buh_ai_agent.services.vat ValueError: Недопустимая ставка НДС.
    """
    doc_date = format_document_date(document_date)
    table_lines, total = build_table_lines(lines, vat_rate, includes_vat)

    is_vat_exempt = all(str(line["СтавкаНДС"]) == "БезНДС" for line in table_lines)
    payload: dict[str, Any] = {
        "Date": doc_date,
        "Posted": False,
        "ВидОперации": "ТоварыИУслуги",
        "Организация_Key": organization_key,
        "Контрагент_Key": counterparty_key,
        "ДоговорКонтрагента_Key": contract_key,
        "СтруктурнаяЕдиница_Key": bank_account_key,
        "ВалютаДокумента_Key": currency_key,
        "СуммаВключаетНДС": includes_vat,
        "СуммаДокумента": total,
        "Товары": table_lines,
    }
    if is_vat_exempt:
        payload["ДокументБезНДС"] = True
    return payload


async def create_invoice(client: OnecClient, payload: dict[str, Any]) -> DocumentInfo:
    """Создаёт счёт (POST) и перечитывает его шапку и строки.

    Args:
        client: Клиент 1С.
        payload: Payload из `build_invoice_payload`.

    Returns:
        Созданный счёт (перечитан после записи).

    Raises:
        buh_ai_agent.integrations.onec.errors.OnecApiError: Ошибка записи.
    """
    created = await client.create(ENTITY_SALES_INVOICE, payload)
    ref_key = str(created.get("Ref_Key", ""))
    if not ref_key:
        raise LookupError("1С не вернула Ref_Key созданного счёта.")
    return await read_invoice(client, ref_key)


async def update_invoice_lines(
    client: OnecClient,
    invoice: DocumentInfo,
    lines: list[dict[str, Any]],
    vat_rate: str,
    includes_vat: bool,
) -> DocumentInfo:
    """Заменяет строки табличной части счёта (PATCH с полным массивом `Товары`).

    Шапка не меняется — только строки и `СуммаДокумента`. Документ должен
    быть непроведённым (проверка состояния — на вызывающей стороне).

    Args:
        client: Клиент 1С.
        invoice: Текущее состояние счёта (шапка сохраняется).
        lines: Полный новый состав строк (`build_table_lines`).
        vat_rate: Ставка НДС по умолчанию для строк.
        includes_vat: `СуммаВключаетНДС`.

    Returns:
        Обновлённый счёт (перечитан после записи).
    """
    table_lines, total = build_table_lines(lines, vat_rate, includes_vat)
    payload = {"СуммаДокумента": total, "Товары": table_lines}
    await client.update(ENTITY_SALES_INVOICE, invoice.ref_key, payload)
    return await read_invoice(client, invoice.ref_key)
