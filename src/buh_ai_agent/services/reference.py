"""Служебные справочники 1С: организация, валюта, единица, склад, банк.

Правила — Skill onec-reference-data:
- GUID перечитываются запросом — данные базы меняются;
- валюта — `Code eq '643'` (руб. по умолчанию из конфигурации);
- единицы измерения и виды номенклатуры не создаются через OData;
- банковский счёт организации — полиморфный `Owner` (не `Организация_Key`).
"""

from __future__ import annotations

from buh_ai_agent.integrations.onec.client import OnecClient
from buh_ai_agent.integrations.onec.entities import (
    ENTITY_BANK_ACCOUNTS,
    ENTITY_CURRENCIES,
    ENTITY_NOMENCLATURE_UNITS,
    ENTITY_ORGANIZATIONS,
    ENTITY_WAREHOUSES,
)
from buh_ai_agent.integrations.onec.models import BankAccount, Organization, RefItem

_SELECT_ORGANIZATION = "Ref_Key,Description,ИНН,КПП,ОсновнойБанковскийСчет_Key"


async def get_main_organization(client: OnecClient, *, inn: str = "") -> Organization:
    """Возвращает основную (единственную) организацию базы.

    Args:
        client: Клиент 1С.
        inn: ИНН для выбора из конфигурации (пусто — любая единственная).

    Returns:
        Организация.

    Raises:
        LookupError: Организация не найдена или неоднозначна.
    """
    rows = await client.query(
        ENTITY_ORGANIZATIONS,
        select=_SELECT_ORGANIZATION,
        top=50,
    )
    candidates = [Organization.from_row(row) for row in rows if not row.get("IsFolder")]
    if inn:
        candidates = [c for c in candidates if c.inn == inn]
    if not candidates:
        raise LookupError(f"Организация{f' с ИНН {inn}' if inn else ''} не найдена в 1С.")
    if len(candidates) > 1:
        descriptions = ", ".join(c.description for c in candidates)
        raise LookupError(
            f"В базе несколько организаций ({descriptions}); уточните, какая из них нужна."
        )
    return candidates[0]


async def get_currency(client: OnecClient, code: str = "643") -> RefItem:
    """Возвращает валюту по коду.

    Args:
        client: Клиент 1С.
        code: Код валюты (по умолчанию руб. — 643).

    Returns:
        Валюта.

    Raises:
        LookupError: Валюта не найдена.
    """
    rows = await client.query(ENTITY_CURRENCIES, filter_=f"Code eq '{code}'", top=5)
    if not rows:
        raise LookupError(f"Валюта с кодом {code!r} не найдена в 1С.")
    return RefItem.from_row(rows[0])


async def get_unit(client: OnecClient, description: str) -> RefItem | None:
    """Возвращает единицу измерения по наименованию (шт, кг, ...).

    Args:
        client: Клиент 1С.
        description: Наименование единицы.

    Returns:
        Единица измерения или None, если её нет в классификаторе
        (создавать её через OData нельзя — попросите пользователя).
    """
    rows = await client.query(
        ENTITY_NOMENCLATURE_UNITS,
        filter_=f"substringof('{description}', Description)",
        top=10,
    )
    exact = [r for r in rows if r.get("Description", "").lower() == description.lower()]
    if exact:
        return RefItem.from_row(exact[0])
    return None


async def get_warehouse(client: OnecClient) -> RefItem | None:
    """Возвращает единственный не-папочный склад (для реализации товаров).

    Args:
        client: Клиент 1С.

    Returns:
        Склад или None (складов нет — тогда запросить у пользователя).
    """
    rows = await client.query(ENTITY_WAREHOUSES, top=50)
    warehouses = [RefItem.from_row(row) for row in rows if not row.get("IsFolder")]
    if len(warehouses) == 1:
        return warehouses[0]
    return None


async def get_org_bank_account(client: OnecClient, org_key: str) -> BankAccount | None:
    """Возвращает основной банковский счёт организации.

    Владелец — полиморфное поле `Owner` (не `Организация_Key`),
    поэтому фильтруем локально: банковских счетов организаций немного.

    Args:
        client: Клиент 1С.
        org_key: GUID организации.

    Returns:
        Счёт или None (не найден — тогда запросить у пользователя).
    """
    rows = await client.query(
        ENTITY_BANK_ACCOUNTS,
        select="Ref_Key,Description,НомерСчета,Owner",
        top=50,
    )
    accounts = [BankAccount.from_row(row) for row in rows]
    owned = [a for a in accounts if a.owner_key == org_key]
    if not owned:
        return None
    return owned[0]
