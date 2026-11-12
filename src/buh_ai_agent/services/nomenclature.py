"""Номенклатура 1С: поиск и создание позиций (товар/услуга).

Правила — Skill onec-nomenclature:
- в документах — только элементы (`IsFolder=false`, не помечены);
- точное совпадение — наименование без регистра или совпадение артикула;
- несколько похожих — показать пользователю список, не выбирать молча;
- создание: минимум `{ "Description": ..., "Услуга": bool }` — 1С сама
  подставляет вид номенклатуры, единицу «шт», группу и `ВидСтавкиНДС`;
  всё равно перечитать после создания;
- единицы измерения и виды номенклатуры не создаются через OData.
"""

from __future__ import annotations

from buh_ai_agent.integrations.onec.client import OnecClient
from buh_ai_agent.integrations.onec.entities import ENTITY_NOMENCLATURE
from buh_ai_agent.integrations.onec.models import Nomenclature

_SELECT_NOMENCLATURE = (
    "Ref_Key,Description,НаименованиеПолное,Артикул,Услуга,IsFolder,DeletionMark,"
    "ЕдиницаИзмерения_Key,ВидСтавкиНДС"
)


async def find_nomenclature(client: OnecClient, query: str) -> list[Nomenclature]:
    """Ищет позиции номенклатуры по подстроке наименования.

    Поиск по всем элементам (иерархия — `Parent_Key`), локальная фильтрация
    по подстроке без учёта регистра.

    Args:
        client: Клиент 1С.
        query: Подстрока наименования (или артикула).

    Returns:
        Список найденных элементов (не папки, без пометки удаления).
    """
    if not query:
        return []
    rows = await client.query(
        ENTITY_NOMENCLATURE,
        select=_SELECT_NOMENCLATURE,
        top=1000,
    )
    needle = query.lower()
    result = [
        Nomenclature.from_row(row)
        for row in rows
        if not row.get("IsFolder")
        and not row.get("DeletionMark")
        and (
            needle in str(row.get("Description", "")).lower()
            or needle == str(row.get("Артикул", "")).lower()
        )
    ]
    return result


async def find_exact_nomenclature(client: OnecClient, name: str) -> Nomenclature | None:
    """Ищет точное совпадение наименования без учёта регистра.

    Args:
        client: Клиент 1С.
        name: Наименование позиции.

    Returns:
        Позиция или None.
    """
    if not name:
        return None
    items = await find_nomenclature(client, name)
    needle = name.lower()
    for item in items:
        if item.description.lower() == needle:
            return item
    return None


async def create_nomenclature(
    client: OnecClient,
    *,
    name: str,
    is_service: bool,
    full_name: str = "",
    article: str = "",
) -> Nomenclature:
    """Создаёт позицию номенклатуры (товар или услуга).

    Перед созданием выполняет поиск-антидубликат: точное совпадение
    наименования без регистра. Существующая позиция главнее новой.

    Args:
        client: Клиент 1С.
        name: Наименование (как назвал пользователь — без переименований).
        is_service: True — услуга (`Услуга: true`), False — товар.
        full_name: Полное наименование для печати.
        article: Артикул.

    Returns:
        Созданная позиция (перечитана после записи).

    Raises:
        LookupError: Найдена существующая позиция с таким наименованием.
        ValueError: Пустое наименование.
        buh_ai_agent.integrations.onec.errors.OnecApiError: Ошибка записи.
    """
    if not name:
        raise ValueError("Наименование номенклатуры обязательно.")

    existing = await find_exact_nomenclature(client, name)
    if existing is not None:
        raise LookupError(
            f"Номенклатура «{existing.description}» уже существует ({existing.ref_key})."
        )

    payload: dict[str, object] = {"Description": name, "Услуга": is_service}
    if full_name:
        payload["НаименованиеПолное"] = full_name
    if article:
        payload["Артикул"] = article

    created = await client.create(ENTITY_NOMENCLATURE, payload)
    ref_key = str(created.get("Ref_Key", ""))
    if not ref_key:
        raise LookupError("1С не вернула Ref_Key созданной номенклатуры.")
    # 1С сама подставляет вид, единицу, группу и ВидСтавкиНДС — перечитать.
    return Nomenclature.from_row(await client.get_entity(ENTITY_NOMENCLATURE, ref_key))
