"""Юнит-тесты разбора $metadata 1С."""

from tests.unit.onec_helpers import METADATA_XML

from buh_ai_agent.integrations.onec.metadata import extract_enum_values


def test_extract_vat_rates() -> None:
    """Перечисление СтавкиНДС разбирается по порядку метаданных."""
    values = extract_enum_values(METADATA_XML, "СтавкиНДС")
    assert values == [
        "БезНДС",
        "НДС0",
        "НДС5",
        "НДС10",
        "НДС10_110",
        "НДС18",
        "НДС18_118",
        "НДС20",
        "НДС20_120",
    ]


def test_extract_unknown_enum_returns_none() -> None:
    """Неизвестное перечисление возвращает None (не ошибку)."""
    assert extract_enum_values(METADATA_XML, "НетТакого") is None


def test_extract_invalid_xml_returns_none() -> None:
    """Невалидный XML возвращает None."""
    assert extract_enum_values("<not-xml", "СтавкиНДС") is None
