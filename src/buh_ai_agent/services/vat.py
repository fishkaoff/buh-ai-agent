"""Бизнес-логика НДС.

Правила в точности из Skills onec-validation и onec-sales-invoices:

- Допустимые значения перечисления `СтавкиНДС` — только из `$metadata`
  этой конфигурации. Дефолт ставки — из настроек приложения (`ONEC_VAT_RATE`);
  допустимость ставки проверяется по живым метаданным при записи.
- СуммаНДС строки рассчитывается по признаку «в том числе» из шапки
  документа (`СуммаВключаетНДС`): при true → `Сумма × ставка/(100+ставка)`,
  иначе → `× ставка/100`. Суффикс ставки `_110`/`_120` — подсказка
  конструктора («в том числе»), но в проверенном payload Skill
  onec-sales-invoices используется `НДС20` при `СуммаВключаетНДС=true`.
- `СуммаНДС` строк рассчитывает агент — 1С через OData их не
  пересчитывает (пустой `СуммаНДС` в реализации → нет проводки
  Дт 90.03 Кт 68.02).
- Явная ставка пользователя главнее дефолта из конфигурации; недопустимую
  ставку молча не подменять — запросить у пользователя.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field

# Фактические значения перечисления `СтавкиНДС` из $metadata конфигурации
# (docs/onec-metadata-map.md). Используется как fallback-список, когда
# $metadata недоступен; реальная проверка — по живым метаданным.
# `НДС5` — возможный дефолт из настроек (ONEC_VAT_RATE): входит в список как
# парсируемое значение, но допустимость по $metadata проверяется на записи.
KNOWN_VAT_RATES: tuple[str, ...] = (
    "БезНДС",
    "НДС0",
    "НДС5",
    "НДС10",
    "НДС10_110",
    "НДС18",
    "НДС18_118",
    "НДС20",
    "НДС20_120",
)
_NO_VAT = "БезНДС"
_VAT_SUFFIX = "_"


def parse_vat_rate(rate: str) -> tuple[int, bool]:
    """Разбирает значение ставки НДС в процент и признак «в том числе».

    Признак «в том числе» из суффикса — только подсказка конструктора;
    фактический расчёт определяется шапкой документа (`СуммаВключаетНДС`).

    Args:
        rate: Значение перечисления `СтавкиНДС` (например, `НДС20_120`).

    Returns:
        Кортеж (процент, включает_ндс).

    Raises:
        ValueError: Если значение не входит в известный список.
    """
    value = rate.strip()
    if value not in KNOWN_VAT_RATES:
        raise ValueError(
            f"Недопустимая ставка НДС {value!r}. "
            f"Допустимые значения перечисления «СтавкиНДС»: "
            f"{', '.join(KNOWN_VAT_RATES)} — проверяйте актуальный список по $metadata."
        )
    if value == _NO_VAT or value == "НДС0":
        return 0, False
    if _VAT_SUFFIX in value:
        stem, _, _suffix = value.partition(_VAT_SUFFIX)
        percent = int(stem[len("НДС") :])
        return percent, True
    # НДС10, НДС18, НДС20 — «сверху» (по умолчанию).
    return int(value[len("НДС") :]), False


def line_vat_amount(amount: float, rate: str, *, includes_vat: bool) -> float:
    """Сумма НДС строки по правилам 1С (`СуммаНДС` рассчитывает агент).

    При `СуммаВключаетНДС=true` → `Сумма × ставка/(100+ставка)`;
    иначе → `Сумма × ставка/100`.

    Args:
        amount: Сумма строки.
        rate: Значение ставки НДС (`НДС20`, `НДС20_120`, `БезНДС`, ...).
        includes_vat: Признак «в том числе» из шапки документа.

    Returns:
        Сумма НДС строки (0 — для «Без НДС» и 0%).

    Raises:
        ValueError: Если ставка не входит в известный список.
    """
    percent, _ = parse_vat_rate(rate)
    if percent == 0:
        return 0.0
    base = amount / (1 + percent / 100) if includes_vat else amount
    return round(base * percent / 100, 2)


def document_vat_amount(lines: list[float]) -> float:
    """Сумма НДС документа = Σ НДС строк (с точностью до копейки).

    Args:
        lines: Суммы НДС строк документа.

    Returns:
        Сумма НДС документа.
    """
    return round(sum(lines), 2)


class VatCalculation(BaseModel):
    """Расчёт НДС для строки документа.

    Attributes:
        rate: Значение ставки НДС.
        percent: Числовая ставка НДС.
        includes_vat: Сумма включает НДС (суффикс `_110`/`_118`/`_120`).
        exempt: «Без НДС» — это не 0%.
        amount: Сумма строки.
        vat_amount: Сумма НДС строки.
    """

    rate: str
    percent: int = Field(ge=0, le=100)
    includes_vat: bool
    exempt: bool
    amount: float = Field(ge=0)
    vat_amount: float = Field(ge=0)


def calculate_vat(amount: float, rate: str, *, includes_vat: bool) -> VatCalculation:
    """Полный расчёт НДС для строки документа.

    Args:
        amount: Сумма строки.
        rate: Значение ставки НДС.
        includes_vat: Признак «в том числе» из шапки документа.

    Returns:
        Расчёт НДС с процентом и суммой.

    Raises:
        ValueError: Если ставка не входит в известный список.
    """
    percent, _ = parse_vat_rate(rate)
    return VatCalculation(
        rate=rate,
        percent=percent,
        includes_vat=includes_vat,
        exempt=rate == _NO_VAT,
        amount=round(amount, 2),
        vat_amount=line_vat_amount(amount, rate, includes_vat=includes_vat),
    )


def resolve_rate(user_rate: str | None, default_rate: str) -> str:
    """Выбирает ставку НДС: явная ставка пользователя главнее дефолта.

    Args:
        user_rate: Ставка, указанная пользователем (или None).
        default_rate: Ставка по умолчанию из настроек приложения (`ONEC_VAT_RATE`).

    Returns:
        Выбранная ставка (без изменений).

    Raises:
        ValueError: Если выбранная ставка не входит в известный список.
    """
    rate = (user_rate or default_rate).strip()
    parse_vat_rate(rate)  # валидация
    return rate


def validate_amount(amount: float) -> float:
    """Проверяет, что сумма — конечное неотрицательное число.

    NaN/inf и отрицательные суммы запрещены (Edm.Double не примет их).

    Args:
        amount: Сумма.

    Returns:
        Сумма, округлённая до копеек.

    Raises:
        ValueError: Если сумма NaN/inf или отрицательная.
    """
    if not math.isfinite(amount):
        raise ValueError(f"Недопустимая сумма {amount!r}: NaN/inf запрещены.")
    if amount < 0:
        raise ValueError(f"Недопустимая сумма {amount!r}: должна быть неотрицательной.")
    return round(amount, 2)
