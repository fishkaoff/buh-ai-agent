"""Счёт-фактура выданный (`Document_СчетФактураВыданный`) — УПД.

Правила — Skill onec-upd:

- УПД — НЕ отдельный документ: это печатная форма реализации
  (`Document_РеализацияТоваровУслуг`); «сформировать УПД» = правильно
  создать и заполнить реализацию (Skill onec-sales-realizations);
- для книги продаж создаётся счёт-фактура выданный на основании
  реализации, записывается **минимальным payload** — 1С сама наследует
  реквизиты (организацию, контрагента, договор, суммы, НДС);
- полный payload с явными `Организация_Key`/`Контрагент_Key`/суммами
  вызывает 500 `Не удалось записать: "Счет-фактура выданный"!`;
- после POST — перечитать СФ и сверить наследование с реализацией.
"""

from __future__ import annotations

from buh_ai_agent.integrations.onec.client import OnecClient, format_document_date
from buh_ai_agent.integrations.onec.entities import ENTITY_ISSUED_INVOICE
from buh_ai_agent.integrations.onec.models import DocumentInfo, DocumentLine

REALIZATION_TYPE = "StandardODATA.Document_РеализацияТоваровУслуг"


async def create_facture(
    client: OnecClient,
    realization_key: str,
    *,
    document_date: str | None = None,
) -> DocumentInfo:
    """Создаёт счёт-фактуру выданный на основании реализации (УПД).

    Минимальный payload — реквизиты наследуются 1С из документа-основания.

    Args:
        client: Клиент 1С.
        realization_key: GUID реализации.
        document_date: Дата `YYYY-MM-DD` (None — сегодня).

    Returns:
        Созданный счёт-фактура (перечитан после записи).

    Raises:
        buh_ai_agent.integrations.onec.errors.OnecApiError: Ошибка записи.
    """
    payload: dict[str, object] = {
        "Date": format_document_date(document_date),
        "Posted": False,
        "ВидСчетаФактуры": "НаРеализацию",
        "ДокументОснование": realization_key,
        "ДокументОснование_Type": REALIZATION_TYPE,
        "ДокументыОснования": [
            {
                "LineNumber": 1,
                "ДокументОснование": realization_key,
                "ДокументОснование_Type": REALIZATION_TYPE,
            }
        ],
    }
    created = await client.create(ENTITY_ISSUED_INVOICE, payload)
    ref_key = str(created.get("Ref_Key", ""))
    if not ref_key:
        raise LookupError("1С не вернула Ref_Key созданного счёта-фактуры.")
    return await read_facture(client, ref_key)


async def read_facture(client: OnecClient, ref_key: str) -> DocumentInfo:
    """Перечитывает счёт-фактуру выданный.

    Args:
        client: Клиент 1С.
        ref_key: GUID счёта-фактуры.

    Returns:
        Документ.
    """
    header = await client.get_entity(ENTITY_ISSUED_INVOICE, ref_key)
    return DocumentInfo(
        entity_set=ENTITY_ISSUED_INVOICE,
        ref_key=str(header.get("Ref_Key", "")),
        number=str(header.get("Number", "") or ""),
        date=str(header.get("Date", "") or ""),
        posted=bool(header.get("Posted", False)),
        amount=float(header.get("СуммаДокумента", 0) or 0),
        counterparty_key=str(header.get("Контрагент_Key", "") or ""),
        organization_key=str(header.get("Организация_Key", "") or ""),
        kind=str(header.get("ВидСчетаФактуры", "") or ""),
        includes_vat=bool(header.get("СуммаВключаетНДС", True)),
        lines=[DocumentLine.from_invoice_row(row) for row in header.get("ДокументыОснования", [])],
    )


def verify_facture_inheritance(facture: DocumentInfo, realization: DocumentInfo) -> list[str]:
    """Проверяет наследование реквизитов счёта-фактуры из реализации.

    Skill onec-upd: после POST — сверьте `Организация_Key`,
    `Контрагент_Key`, `СуммаДокумента`, `СуммаНДСДокумента` с реализацией.

    Args:
        facture: Перечитанный счёт-фактура.
        realization: Реализация-основание.

    Returns:
        Список расхождений (пустой — наследование корректно).
    """
    problems: list[str] = []
    if facture.counterparty_key and facture.counterparty_key != realization.counterparty_key:
        problems.append(
            f"Контрагент СФ не совпадает с реализацией: {facture.counterparty_key} "
            f"!= {realization.counterparty_key}"
        )
    if facture.organization_key and facture.organization_key != realization.organization_key:
        problems.append(
            f"Организация СФ не совпадает с реализацией: {facture.organization_key} "
            f"!= {realization.organization_key}"
        )
    if realization.amount and facture.amount and facture.amount != realization.amount:
        problems.append(
            f"Сумма СФ не совпадает с реализацией: {facture.amount:.2f} != {realization.amount:.2f}"
        )
    return problems
