"""Контрагенты 1С: поиск (по ИНН/наименованию), создание, обновление.

Правила — Skill onec-counterparties:
- поиск по ИНН → совпадение наименований без регистра → вероятный дубль;
- перед созданием — поиск (антидубликат); существующий элемент главнее;
- PATCH — только явно указанные пользователем поля, затем перечитать.
"""

from __future__ import annotations

import re

from buh_ai_agent.integrations.onec.client import OnecClient
from buh_ai_agent.integrations.onec.entities import ENTITY_COUNTERPARTIES
from buh_ai_agent.integrations.onec.models import Counterparty

_SELECT_COUNTERPARTY = (
    "Ref_Key,Description,ИНН,КПП,НаименованиеПолное,ЮридическоеФизическоеЛицо,IsFolder,DeletionMark"
)

# Слова-юридические формы: в наименовании 1С их может не быть, поэтому при
# первом пустом поиске они отбрасываются (см. find_by_name).
_LEGAL_FORMS = frozenset(
    {"ооо", "оао", "зао", "пао", "ао", "одо", "ип", "тоо", "чуп", "гуп", "муп"}
)

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _name_tokens(name: str) -> tuple[list[str], list[str]]:
    r"""Разбивает наименование на слова без пунктуации и кавычек.

    Args:
        name: Наименование в любом формате («ООО «Логистик Плюс»»).

    Returns:
        Пара (все слова, значимые слова без юрформ). Токены в нижнем регистре;
        токены из `\w+` не содержат кавычек, поэтому безопасны для OData-фильтра.
    """
    tokens = [token.lower() for token in _TOKEN_RE.findall(name)]
    significant = [token for token in tokens if token not in _LEGAL_FORMS]
    return tokens, (significant or tokens)


def _name_filter(tokens: list[str]) -> str:
    """Строит OData-фильтр: каждое слово должно входить в Description."""
    return " and ".join(f"substringof('{token}', Description)" for token in tokens)


def _matches_all(description: str, tokens: list[str]) -> bool:
    """Проверяет, что каждое слово запроса входит в наименование (без регистра)."""
    haystack = description.lower()
    return all(token in haystack for token in tokens)


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


async def _find_by_tokens(client: OnecClient, tokens: list[str]) -> list[Counterparty]:
    """Выбирает контрагентов, у которых Description содержит все слова.

    Args:
        client: Клиент 1С.
        tokens: Слова запроса в нижнем регистре.

    Returns:
        Найденные элементы (не папки, без пометки удаления), отсортированы
        по длине наименования — более точные совпадения первыми.
    """
    rows = await client.query(
        ENTITY_COUNTERPARTIES,
        filter_=_name_filter(tokens),
        select=_SELECT_COUNTERPARTY,
        top=50,
    )
    found = [
        Counterparty.from_row(row)
        for row in rows
        if not row.get("IsFolder")
        and not row.get("DeletionMark")
        and _matches_all(str(row.get("Description", "")), tokens)
    ]
    found.sort(key=lambda c: (len(c.description), c.description))
    return found


async def find_by_name(client: OnecClient, name: str) -> list[Counterparty]:
    """Ищет контрагентов по словам наименования (без учёта регистра).

    Поиск устойчив к формату наименования: пробелы, кавычки и пунктуация
    не важны — «Логистик Плюс» находит и «ЛогистикПлюс», и «ООО «Логистик
    Плюс»». Сначала требует совпадения всех слов; если пусто, повторяет
    поиск без юридических форм (ООО, ИП, …).

    Args:
        client: Клиент 1С.
        name: Наименование в любом формате.

    Returns:
        Список найденных элементов (не папки, без пометки удаления).
    """
    tokens, significant = _name_tokens(name)
    if not tokens:
        return []
    found = await _find_by_tokens(client, tokens)
    if not found and significant != tokens:
        found = await _find_by_tokens(client, significant)
    return found


async def find_counterparty(
    client: OnecClient, *, name: str = "", inn: str = ""
) -> list[Counterparty]:
    """Ищет контрагента по ИНН и/или наименованию.

    Правила Skill onec-counterparties: сначала ИНН, затем наименование;
    при совпадении наименования с другим ИНН — вероятный дубль, уточните
    у пользователя. Поиск по наименованию устойчив к формату: пробелы,
    кавычки и юридическая форма (ООО, ИП, …) не важны.

    Args:
        client: Клиент 1С.
        name: Наименование в любом формате («Логистик Плюс», «ЛогистикПлюс»).
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
