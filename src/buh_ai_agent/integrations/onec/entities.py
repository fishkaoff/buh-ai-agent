"""Имена объектов метаданных 1С, используемые агентом.

Значения взяты из `docs/onec-metadata-map.md` и Skills — не придумываются.
Имена EntitySet технические, с кириллицей.
"""

ENTITY_COUNTERPARTIES = "Catalog_Контрагенты"
ENTITY_CONTRACTS = "Catalog_ДоговорыКонтрагентов"
ENTITY_NOMENCLATURE = "Catalog_Номенклатура"
ENTITY_ORGANIZATIONS = "Catalog_Организации"
ENTITY_BANK_ACCOUNTS = "Catalog_БанковскиеСчета"
ENTITY_CURRENCIES = "Catalog_Валюты"
ENTITY_NOMENCLATURE_UNITS = "Catalog_КлассификаторЕдиницИзмерения"
ENTITY_WAREHOUSES = "Catalog_Склады"
ENTITY_SALES_INVOICE = "Document_СчетНаОплатуПокупателю"
ENTITY_REALIZATION = "Document_РеализацияТоваровУслуг"
ENTITY_ISSUED_INVOICE = "Document_СчетФактураВыданный"
ENTITY_CHART_OF_ACCOUNTS = "ChartOfAccounts_Хозрасчетный"

# Перечисление допустимых ставок НДС в строках документов.
ENUM_VAT_RATES = "СтавкиНДС"

# Стандартные счета учёта для реализации (Skill onec-sales-realizations):
# OData не валидирует GUID счетов при записи — Ref_Key берётся только
# из плана счетов по коду.
ACCOUNT_SETTLEMENTS = "62.01"
ACCOUNT_REVENUE = "90.01.1"
ACCOUNT_EXPENSES = "90.02.1"
ACCOUNT_VAT = "90.03"
ACCOUNT_GOODS = "41"
