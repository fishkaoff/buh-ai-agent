"""Договоры контрагентов 1С: поиск, выбор последнего, нумерация, создание.

Правила — Skill onec-contracts:
- владелец — контрагент через `Owner_Key`;
- вид договора соответствует операции (продажа — `СПокупателем`);
- закрытые (`ДоговорЗакрыт`) не использовать для новых документов;
- `Номер` — строковый реквизит, 1С через OData его не нумерует:
  кандидат = max(числовых Номер) + 1, проверка занятости;
- `Description` — по образцу данных: «Номер от ДД.ММ.ГГГГ».
"""

from __future__ import annotations

from buh_ai_agent.integrations.onec.client import OnecClient
from buh_ai_agent.integrations.onec.entities import ENTITY_CONTRACTS
from buh_ai_agent.integrations.onec.models import Contract

_SELECT_CONTRACT = (
    "Ref_Key,Description,Номер,Дата,ВидДоговора,Организация_Key,"
    "ВалютаВзаиморасчетов_Key,ДоговорЗакрыт,Owner_Key"
)


async def find_contracts(
    client: OnecClient, counterparty_key: str, *, kind: str = ""
) -> list[Contract]:
    """Ищет договоры контрагента (серверный фильтр по `Owner_Key`).

    Args:
        client: Клиент 1С.
        counterparty_key: GUID контрагента.
        kind: Вид договора (`СПокупателем` и т.п.) — пусто: все виды.

    Returns:
        Список договоров (без пометки удаления).
    """
    filter_ = f"Owner_Key eq guid'{counterparty_key}'"
    rows = await client.query(
        ENTITY_CONTRACTS,
        filter_=filter_,
        select=_SELECT_CONTRACT,
        top=200,
    )
    contracts = [Contract.from_row(row) for row in rows if not row.get("DeletionMark")]
    if kind:
        contracts = [c for c in contracts if c.kind == kind]
    return contracts


def pick_latest_contract(contracts: list[Contract], *, kind: str = "") -> Contract | None:
    """Выбирает «последний подходящий» договор: максимум пары (Дата, Номер).

    Args:
        contracts: Договоры контрагента.
        kind: Вид договора (пусто — любой).

    Returns:
        Договор или None.
    """
    candidates = [c for c in contracts if not c.closed]
    if kind:
        candidates = [c for c in candidates if c.kind == kind]
    if not candidates:
        return None
    return max(candidates, key=lambda c: (c.date, c.number))


def next_contract_number(contracts: list[Contract]) -> str | None:
    """Вычисляет кандидата следующего номера договора.

    Правила Skill onec-contracts: кандидат = max(числовых `Номер`) + 1;
    если номера нечисловые/смешанные — надёжно определить нельзя,
    возвращается None (номер нужно спросить у пользователя).

    Args:
        contracts: Договоры (все контрагентов — сквозная последовательность).

    Returns:
        Кандидат номера строкой или None.
    """
    numbers: list[int] = []
    for contract in contracts:
        stripped = contract.number.strip()
        if stripped.isdigit():
            numbers.append(int(stripped))
    if not numbers:
        return None
    return str(max(numbers) + 1)


def contract_description(number: str, document_date: str) -> str:
    """Строит `Description` договора по образцу базы: «Номер от ДД.ММ.ГГГГ».

    Args:
        number: Номер договора.
        document_date: Дата `YYYY-MM-DD`.

    Returns:
        Наименование договора.
    """
    year, month, day = document_date.split("-")
    return f"{number} от {day}.{month}.{year}"


async def create_contract(
    client: OnecClient,
    *,
    counterparty_key: str,
    organization_key: str,
    currency_key: str,
    kind: str = "СПокупателем",
    number: str = "",
    document_date: str | None = None,
) -> Contract:
    """Создаёт договор по проверенному минимуму реквизитов.

    Args:
        client: Клиент 1С.
        counterparty_key: GUID контрагента (Owner_Key).
        organization_key: GUID организации.
        currency_key: GUID валюты взаиморасчетов (руб. — 643).
        kind: Вид договора (`СПокупателем` — продажа; обязателен).
        number: Номер договора (пусто — «б/н»; 1С через OData не нумерует).
        document_date: Дата `YYYY-MM-DD` (None — сегодня).

    Returns:
        Созданный договор (перечитан после записи).

    Raises:
        ValueError: Не задан вид договора или контрагент.
        buh_ai_agent.integrations.onec.errors.OnecApiError: Ошибка записи.
    """
    from buh_ai_agent.integrations.onec.client import format_document_date

    if not counterparty_key:
        raise ValueError("Не задан контрагент для договора.")
    if not kind:
        raise ValueError("Вид договора (ВидДоговора) обязателен.")

    doc_date = format_document_date(document_date)
    payload: dict[str, object] = {
        "Description": contract_description(number or "б/н", doc_date[:10]),
        "Дата": doc_date,
        "Owner_Key": counterparty_key,
        "Организация_Key": organization_key,
        "ВидДоговора": kind,
        "ВалютаВзаиморасчетов_Key": currency_key,
    }
    if number:
        payload["Номер"] = number

    created = await client.create(ENTITY_CONTRACTS, payload)
    ref_key = str(created.get("Ref_Key", ""))
    if not ref_key:
        raise LookupError("1С не вернула Ref_Key созданного договора.")
    return Contract.from_row(await client.get_entity(ENTITY_CONTRACTS, ref_key))
