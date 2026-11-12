"""Контрагенты 1С: поиск (по ИНН/наименованию), создание, обновление.

Правила — Skill onec-counterparties:
- поиск по ИНН → совпадение наименований без регистра → вероятный дубль;
- перед созданием — поиск (антидубликат); существующий элемент главнее;
- PATCH — только явно указанные пользователем поля, затем перечитать.
"""

from __future__ import annotations

from buh_ai_agent.integrations.onec.client import OnecClient
from buh_ai_agent.integrations.onec.entities import ENTITY_COUNTERPARTIES
from buh_ai_agent.integrations.onec.models import Counterparty

_SELECT_COUNTERPARTY = (
    "Ref_Key,Description,ИНН,КПП,НаименованиеПолное,ЮридическоеФизическоеЛицо,IsFolder,DeletionMark"
)


async def find_by_inn(client: OnecClient, inn: str) -> Counterparty | None:
    """Ищет контрагента по ИНН (точное равенство).

    Args:
        client: Клиент 1С.
        inn: ИНН (10 или 12 цифр).

    Returns:
        Контрагент или None.
    """
    if not inn:
        return None
    rows = await client.query(
        ENTITY_COUNTERPARTIES,
        filter_=f"ИНН eq '{inn}'",
        select=_SELECT_COUNTERPARTY,
        top=10,
    )
    for row in rows:
        if not row.get("IsFolder") and not row.get("DeletionMark"):
            return Counterparty.from_row(row)
    return None


async def find_by_name(client: OnecClient, name: str) -> list[Counterparty]:
    """Ищет контрагентов по подстроке наименования (без учёта регистра).

    Args:
        client: Клиент 1С.
        name: Подстрока наименования.

    Returns:
        Список найденных элементов (не папки, без пометки удаления).
    """
    if not name:
        return []
    rows = await client.query(
        ENTITY_COUNTERPARTIES,
        filter_=f"substringof('{name}', Description)",
        select=_SELECT_COUNTERPARTY,
        top=50,
    )
    needle = name.lower()
    return [
        Counterparty.from_row(row)
        for row in rows
        if not row.get("IsFolder")
        and not row.get("DeletionMark")
        and needle in str(row.get("Description", "")).lower()
    ]


async def find_counterparty(
    client: OnecClient, *, name: str = "", inn: str = ""
) -> list[Counterparty]:
    """Ищет контрагента по ИНН и/или наименованию.

    Правила Skill onec-counterparties: сначала ИНН, затем наименование;
    при совпадении наименования с другим ИНН — вероятный дубль, уточните
    у пользователя.

    Args:
        client: Клиент 1С.
        name: Подстрока наименования.
        inn: ИНН.

    Returns:
        Найденные контрагенты (могут быть дублями — уточните).

    Raises:
        ValueError: Не заданы ни ИНН, ни наименование.
    """
    if not inn and not name:
        raise ValueError("Нужно задать ИНН или наименование контрагента.")
    if inn:
        by_inn = await find_by_inn(client, inn)
        if by_inn is not None:
            return [by_inn]
    if name:
        return await find_by_name(client, name)
    return []


async def create_counterparty(
    client: OnecClient,
    *,
    name: str,
    inn: str = "",
    kpp: str = "",
    full_name: str = "",
    legal_type: str = "ЮридическоеЛицо",
) -> Counterparty:
    """Создаёт контрагента по проверенному минимуму реквизитов.

    Перед созданием выполняет поиск-антидубликат: по ИНН, затем по
    наименованию (без регистра). Существующий элемент главнее нового.

    Args:
        client: Клиент 1С.
        name: Наименование (как назвал пользователь — без переименований).
        inn: ИНН.
        kpp: КПП.
        full_name: Полное наименование для печати.
        legal_type: `ЮридическоеЛицо` или `ФизическоеЛицо` (перечисление).

    Returns:
        Созданный контрагент (перечитан после записи).

    Raises:
        LookupError: Найден существующий контрагент (дубликат).
        ValueError: Пустое наименование.
        buh_ai_agent.integrations.onec.errors.OnecApiError: Ошибка записи.
    """
    if not name:
        raise ValueError("Наименование контрагента обязательно.")

    if inn:
        existing = await find_by_inn(client, inn)
        if existing is not None:
            raise LookupError(
                f"Контрагент с ИНН {inn} уже существует: «{existing.description}» "
                f"({existing.ref_key})."
            )
    if name:
        existing_by_name = await find_by_name(client, name)
        if existing_by_name:
            raise LookupError(
                f"Контрагент с таким наименованием уже существует: "
                f"«{existing_by_name[0].description}» ({existing_by_name[0].ref_key})."
            )

    payload: dict[str, object] = {
        "Description": name,
        "ЮридическоеФизическоеЛицо": legal_type,
    }
    if inn:
        payload["ИНН"] = inn
    if kpp:
        payload["КПП"] = kpp
    if full_name:
        payload["НаименованиеПолное"] = full_name

    created = await client.create(ENTITY_COUNTERPARTIES, payload)
    ref_key = str(created.get("Ref_Key", ""))
    if not ref_key:
        raise LookupError("1С не вернула Ref_Key созданного контрагента.")
    return Counterparty.from_row(await client.get_entity(ENTITY_COUNTERPARTIES, ref_key))


async def update_counterparty(
    client: OnecClient, ref_key: str, fields: dict[str, object]
) -> Counterparty:
    """Обновляет только явно указанные поля контрагента и перечитывает.

    Args:
        client: Клиент 1С.
        ref_key: GUID контрагента.
        fields: Словарь полей OData (например, `{"ИНН": "..."}`).

    Returns:
        Обновлённый контрагент (перечитан после записи).
    """
    if not fields:
        raise ValueError("Нужно указать хотя бы одно поле для обновления.")
    await client.update(ENTITY_COUNTERPARTIES, ref_key, fields)
    return Counterparty.from_row(await client.get_entity(ENTITY_COUNTERPARTIES, ref_key))
