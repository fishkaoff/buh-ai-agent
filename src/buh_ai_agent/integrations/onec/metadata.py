"""Разбор XML `$metadata` 1С: перечисления, поля, типы.

Использует только стандартную библиотеку (xml.etree). Namespace-агностично:
1С OData 3.0 отдаёт `http://schemas.microsoft.com/ado/2009/11/edm`, а
OData 4 — `http://docs.oasis-open.org/odata/ns/edm`; поиск по локальному
имени тега (без namespace) работает для обоих форматов.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET


def _localname(tag: str) -> str:
    """Возвращает локальное имя тега без namespace."""
    return tag.rsplit("}", 1)[-1]


def extract_enum_values(metadata_xml: str, enum_name: str) -> list[str] | None:
    """Извлекает имена членов EnumType из XML метаданных.

    Args:
        metadata_xml: Текст `$metadata`.
        enum_name: Имя перечисления (например, `СтавкиНДС`).

    Returns:
        Список имён членов (в порядке следования в метаданных) или None,
        если EnumType с таким именем не найден.
    """
    try:
        root = ET.fromstring(metadata_xml)
    except ET.ParseError:
        return None
    for element in root.iter():
        if _localname(element.tag) != "EnumType":
            continue
        if element.get("Name") != enum_name:
            continue
        return [
            member.get("Name", "")
            for member in element
            if _localname(member.tag) == "Member" and member.get("Name")
        ]
    return None
