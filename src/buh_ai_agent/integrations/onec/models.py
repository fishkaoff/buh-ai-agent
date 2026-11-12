"""Модели данных 1С: доменные представления строк OData.

Соответствуют карте метаданных `docs/onec-metadata-map.md` (БП 3.0,
база ai_agent). Поля с кириллицей — имена реквизитов OData.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Counterparty(BaseModel):
    """Контрагент (`Catalog_Контрагенты`)."""

    ref_key: str
    description: str
    inn: str = ""
    kpp: str = ""
    full_name: str = ""
    legal_type: str = ""
    is_folder: bool = False
    deletion_mark: bool = False

    @classmethod
    def from_row(cls, row: dict[str, object]) -> Counterparty:
        """Строит модель из строки OData-ответа."""
        return cls(
            ref_key=str(row.get("Ref_Key", "")),
            description=str(row.get("Description", "")),
            inn=str(row.get("ИНН", "") or ""),
            kpp=str(row.get("КПП", "") or ""),
            full_name=str(row.get("НаименованиеПолное", "") or ""),
            legal_type=str(row.get("ЮридическоеФизическоеЛицо", "") or ""),
            is_folder=bool(row.get("IsFolder", False)),
            deletion_mark=bool(row.get("DeletionMark", False)),
        )


class Contract(BaseModel):
    """Договор контрагента (`Catalog_ДоговорыКонтрагентов`)."""

    ref_key: str
    description: str
    number: str = ""
    date: str = ""
    kind: str = ""
    closed: bool = False
    owner_key: str = ""
    organization_key: str = ""
    currency_key: str = ""

    @classmethod
    def from_row(cls, row: dict[str, object]) -> Contract:
        """Строит модель из строки OData-ответа."""
        return cls(
            ref_key=str(row.get("Ref_Key", "")),
            description=str(row.get("Description", "")),
            number=str(row.get("Номер", "") or ""),
            date=str(row.get("Дата", "") or ""),
            kind=str(row.get("ВидДоговора", "") or ""),
            closed=bool(row.get("ДоговорЗакрыт", False)),
            owner_key=str(row.get("Owner_Key", "") or ""),
            organization_key=str(row.get("Организация_Key", "") or ""),
            currency_key=str(row.get("ВалютаВзаиморасчетов_Key", "") or ""),
        )


class Nomenclature(BaseModel):
    """Позиция номенклатуры (`Catalog_Номенклатура`)."""

    ref_key: str
    description: str
    full_name: str = ""
    article: str = ""
    is_service: bool = False
    is_folder: bool = False
    deletion_mark: bool = False
    unit_key: str = ""
    vat_kind: str = ""

    @classmethod
    def from_row(cls, row: dict[str, object]) -> Nomenclature:
        """Строит модель из строки OData-ответа."""
        return cls(
            ref_key=str(row.get("Ref_Key", "")),
            description=str(row.get("Description", "")),
            full_name=str(row.get("НаименованиеПолное", "") or ""),
            article=str(row.get("Артикул", "") or ""),
            is_service=bool(row.get("Услуга", False)),
            is_folder=bool(row.get("IsFolder", False)),
            deletion_mark=bool(row.get("DeletionMark", False)),
            unit_key=str(row.get("ЕдиницаИзмерения_Key", "") or ""),
            vat_kind=str(row.get("ВидСтавкиНДС", "") or ""),
        )


class Organization(BaseModel):
    """Организация (`Catalog_Организации`)."""

    ref_key: str
    description: str
    inn: str = ""
    kpp: str = ""
    main_bank_account_key: str = ""

    @classmethod
    def from_row(cls, row: dict[str, object]) -> Organization:
        """Строит модель из строки OData-ответа."""
        return cls(
            ref_key=str(row.get("Ref_Key", "")),
            description=str(row.get("Description", "")),
            inn=str(row.get("ИНН", "") or ""),
            kpp=str(row.get("КПП", "") or ""),
            main_bank_account_key=str(row.get("ОсновнойБанковскийСчет_Key", "") or ""),
        )


class BankAccount(BaseModel):
    """Банковский счёт (`Catalog_БанковскиеСчета`)."""

    ref_key: str
    description: str = ""
    account_number: str = ""
    owner_key: str = ""

    @classmethod
    def from_row(cls, row: dict[str, object]) -> BankAccount:
        """Строит модель из строки OData-ответа."""
        return cls(
            ref_key=str(row.get("Ref_Key", "")),
            description=str(row.get("Description", "") or ""),
            account_number=str(row.get("НомерСчета", "") or ""),
            owner_key=str(row.get("Owner", "") or ""),
        )


class RefItem(BaseModel):
    """Элемент служебного справочника (валюта, склад, единица)."""

    ref_key: str
    description: str = ""
    code: str = ""

    @classmethod
    def from_row(cls, row: dict[str, object]) -> RefItem:
        """Строит модель из строки OData-ответа."""
        return cls(
            ref_key=str(row.get("Ref_Key", "")),
            description=str(row.get("Description", "") or ""),
            code=str(row.get("Code", "") or ""),
        )


class DocumentLine(BaseModel):
    """Строка табличной части документа (счёта или реализации)."""

    line_number: int = 0
    nomenclature_key: str = ""
    nomenclature_type: str = ""
    content: str = ""
    quantity: float = 0.0
    price: float = 0.0
    amount: float = 0.0
    vat_rate: str = ""
    vat_amount: float = 0.0
    unit_key: str = ""

    @classmethod
    def from_invoice_row(cls, row: dict[str, object]) -> DocumentLine:
        """Строит модель из строки `_Товары` счёта покупателю.

        У счёта номенклатура — составная ссылка (`Номенклатура` +
        `Номенклатура_Type`).
        """
        return cls(
            line_number=int(row.get("LineNumber", 0) or 0),
            nomenclature_key=str(row.get("Номенклатура", "") or ""),
            nomenclature_type=str(row.get("Номенклатура_Type", "") or ""),
            content=str(row.get("Содержание", "") or ""),
            quantity=float(row.get("Количество", 0) or 0),
            price=float(row.get("Цена", 0) or 0),
            amount=float(row.get("Сумма", 0) or 0),
            vat_rate=str(row.get("СтавкаНДС", "") or ""),
            vat_amount=float(row.get("СуммаНДС", 0) or 0),
        )


class DocumentInfo(BaseModel):
    """Шапка документа с его строками (счёт, реализация, счёт-фактура)."""

    entity_set: str
    ref_key: str
    number: str = ""
    date: str = ""
    posted: bool = False
    amount: float = 0.0
    counterparty_key: str = ""
    contract_key: str = ""
    organization_key: str = ""
    kind: str = ""
    includes_vat: bool = True
    lines: list[DocumentLine] = Field(default_factory=list)

    def summary(self) -> str:
        """Краткое человекочитаемое описание документа."""
        lines_desc = "; ".join(
            f"{line.content or 'позиция'} × {line.quantity:g} = {line.amount:.2f}"
            for line in self.lines
        )
        return (
            f"{self.entity_set} №{self.number or 'б/н'} от {self.date[:10]} "
            f"на {self.amount:.2f} (проведён: {'да' if self.posted else 'нет'}); "
            f"строки: {lines_desc or 'нет'}"
        )
