"""Юнит-тесты бизнес-логики НДС.

`НДС5` — дефолт из `config/onec-config.json`; допустимость ставки по
$metadata проверяется на записи (Tools).
"""

import pytest

from buh_ai_agent.services.vat import (
    calculate_vat,
    document_vat_amount,
    line_vat_amount,
    parse_vat_rate,
    resolve_rate,
    validate_amount,
)


def test_parse_vat_rate_top() -> None:
    """НДС20 — по умолчанию «сверху»: 20%, «в том числе» из суффикса — False."""
    assert parse_vat_rate("НДС20") == (20, False)


def test_parse_vat_rate_included_hint() -> None:
    """НДС20_120 — суффикс подсказывает «в том числе»: 20%, True."""
    assert parse_vat_rate("НДС20_120") == (20, True)


def test_parse_vat_rate_all_known() -> None:
    """Все известные ставки разбираются."""
    expected = {
        "БезНДС": (0, False),
        "НДС0": (0, False),
        "НДС5": (5, False),
        "НДС10": (10, False),
        "НДС10_110": (10, True),
        "НДС18": (18, False),
        "НДС18_118": (18, True),
        "НДС20": (20, False),
        "НДС20_120": (20, True),
    }
    for rate, (percent, includes) in expected.items():
        assert parse_vat_rate(rate) == (percent, includes), rate


def test_parse_vat_rate_rejects_unknown() -> None:
    """НДС7/НДС22 и произвольные форматы отклоняются."""
    for rate in ("НДС7", "НДС22", "5%", "ПБЕС", ""):
        with pytest.raises(ValueError, match="Недопустимая ставка НДС"):
            parse_vat_rate(rate)


def test_line_vat_amount_included() -> None:
    """100000 × 20/120 = 16666.67 — проверенный пример из Skill
    (СуммаВключаетНДС=true, СтавкаНДС=НДС20)."""
    assert line_vat_amount(100000, "НДС20", includes_vat=True) == pytest.approx(16666.67)


def test_line_vat_amount_included_with_suffix() -> None:
    """Суффикс не влияет: расчёт определяется шапкой документа."""
    assert line_vat_amount(100000, "НДС20_120", includes_vat=True) == pytest.approx(16666.67)


def test_line_vat_amount_top() -> None:
    """При СуммаВключаетНДС=false: 100000 × 20/100 = 20000."""
    assert line_vat_amount(100000, "НДС20", includes_vat=False) == pytest.approx(20000.0)


def test_line_vat_amount_zero() -> None:
    """БезНДС и НДС0 — НДС 0."""
    assert line_vat_amount(1000, "БезНДС", includes_vat=True) == 0.0
    assert line_vat_amount(1000, "НДС0", includes_vat=False) == 0.0


def test_line_vat_amount_ten() -> None:
    """НДС10_110 при СуммаВключаетНДС=true: 1000 × 10/110 = 90.91."""
    assert line_vat_amount(1000, "НДС10", includes_vat=True) == pytest.approx(90.91)


def test_document_vat_amount_sums_lines() -> None:
    """Сумма НДС документа = Σ НДС строк."""
    assert document_vat_amount([16666.67, 1000.00, 0.0]) == pytest.approx(17666.67)


def test_calculate_vat() -> None:
    """Полный расчёт НДС."""
    calc = calculate_vat(100000, "НДС20", includes_vat=True)
    assert calc.rate == "НДС20"
    assert calc.percent == 20
    assert calc.includes_vat is True
    assert calc.exempt is False
    assert calc.vat_amount == pytest.approx(16666.67)


def test_calculate_vat_exempt() -> None:
    """БезНДС — это не 0%: exempt=True, НДС 0."""
    calc = calculate_vat(5000, "БезНДС", includes_vat=False)
    assert calc.exempt is True
    assert calc.percent == 0
    assert calc.vat_amount == 0.0


def test_resolve_rate_user_wins() -> None:
    """Явная ставка пользователя главнее дефолта."""
    assert resolve_rate("НДС20", "НДС20_120") == "НДС20"


def test_resolve_rate_default_when_user_none() -> None:
    """Без ставки пользователя — дефолт из конфигурации."""
    assert resolve_rate(None, "НДС20_120") == "НДС20_120"


def test_resolve_rate_rejects_invalid_default() -> None:
    """Недопустимый дефолт (произвольный формат) не проходит молча."""
    with pytest.raises(ValueError, match="Недопустимая ставка НДС"):
        resolve_rate(None, "НДС7")


def test_validate_amount() -> None:
    """Суммы округляются до копеек."""
    assert validate_amount(1000.123) == 1000.12


def test_validate_amount_rejects_nan() -> None:
    """NaN/inf запрещены."""
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError, match="NaN/inf"):
            validate_amount(bad)


def test_validate_amount_rejects_negative() -> None:
    """Отрицательные суммы запрещены."""
    with pytest.raises(ValueError, match="неотрицательной"):
        validate_amount(-1.0)
