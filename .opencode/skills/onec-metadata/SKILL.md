---
name: onec-metadata
description: Исследование метаданных конфигурации 1С через стандартный OData $metadata — поиск справочников, документов, перечислений, реквизитов и типов, структура табличных частей. Самодостаточен (чистый HTTP), без зависимости от MCP.
---

# onec-metadata — метаданные 1С через $metadata

## Когда использовать

- Перед первой работой с любым объектом 1С: узнать реальные поля и типы.
- При ошибке `Сегмент пути ... не найден` / `Сущность ... не найдена`.
- Узнать допустимые значения перечисления (ставки НДС, виды договоров, виды операций).
- Найти EntitySet по человеческому названию.

Никогда не работайте с «предполагаемыми» именами полей — сначала опишите объект. Писать в поле можно только значения/типы, существующие в конфигурации.

## Получение $metadata

`GET {BASE}$metadata` — **без** `$format=json`: ответ XML размером ~12 МБ (норма для БП 3.0). Скачивайте файл и разбирайте скриптом локально — не тащите целиком в контекст.

```bash
curl -s -u LOGIN:PASS "http://HOST/BASE/odata/standard.odata/\$metadata" -o metadata.xml
```

Скрипт-помощник (портативный, без MCP): `scripts/metadata_extract.js metadata.xml [что]`:

```bash
node scripts/metadata_extract.js metadata.xml enums                # все перечисления + члены
node scripts/metadata_extract.js metadata.xml enum СтавкиНДС       # члены одного перечисления
node scripts/metadata_extract.js metadata.xml find Реализация      # EntitySet по подстроке
node scripts/metadata_extract.js metadata.xml fields Document_РеализацияТоваровУслуг
node scripts/metadata_extract.js metadata.xml fields Catalog_Номенклатура --relations
```

## Что есть в $metadata

- `<EntitySet Name="Catalog_Контрагents" EntityType="StandardODATA.Catalog_Контрагенты">` — карта сущностей (EntitySet в `<EntityContainer>`; имя EntitySet = источник данных).
- `<EntityType Name="...">` — поля (`<Property Name Type Nullable>`), ключ (`Ref_Key`), навигации (`<NavigationProperty>` — связи на другие объекты).
- `<EnumType Name="СтавкиНДС"><Member Name="..."/>...` — **единственный источник допустимых значений перечислений** (как EntitySet они не публикуются).
- Табличные части: у типа документа есть `<Property Name="Товары" Type="Collection(StandardODATA.Document_X_Товары_RowType)">` в шапке и **отдельный EntityType/EntitySet** `Document_X_Товары` для построчного чтения.

## Типовой порядок исследования

1. `find` по подстроке → имена EntitySet (класс по префиксу: `Catalog_` — справочник, `Document_` — документ, `InformationRegister_`/`AccumulationRegister_`/`AccountingRegister_` — регистры, `ChartOfAccounts_` — план счетов).
2. `fields <EntitySet>` → реквизиты и типы (поле-ссылка: `*_Key`; составная: `Поле`+`Поле_Type`; перечисление: `Edm.String` + отдельный `enum`).
3. Для документа — отдельно `fields` его табличных частей (`..._Товары`, `..._Услуги`).
4. `enums` → допустимые значения всех перечислений поля.
5. Только после этого — запросы данных (Skill `onec-odata`).

## Ключевые сущности этой конфигурации

Карта реальных объектов, реквизитов, перечислений и связей (проверена 10.11.2026) — `docs/onec-metadata-map.md`. Коротко:

| Область | EntitySet |
|---|---|
| Контрагенты | `Catalog_Контрагенты` |
| Договоры | `Catalog_ДоговорыКонтрагентов` (владелец — `Owner_Key`) |
| Организации | `Catalog_Организации` |
| Номенклатура | `Catalog_Номенклатура` |
| Виды номенклатуры | `Catalog_ВидыНоменклатуры` |
| Единицы измерения | `Catalog_КлассификаторЕдиницИзмерения` |
| Валюты / Склады / Банковские счета | `Catalog_Валюты`, `Catalog_Склады`, `Catalog_БанковскиеСчета` |
| Счёт покупателю | `Document_СчетНаОплатуПокупателю` (+ `_Товары`) |
| Реализация | `Document_РеализацияТоваровУслуг` (+ `_Товары`, `_Услуги`) |
| Счёт-фактура выданный | `Document_СчетФактураВыданный` |

## Ограничения

- Перечисления не читаются как EntitySet — только через `$metadata` (скрипт `scripts/metadata_extract.js`).
- `$metadata` большой — скачайте в файл, не в контекст.
- Перечисленные выше возможности MCP (`read_schema_describe_entity`, `read_schema_list_entities`) — удобная обёртка над тем же `$metadata` (см. `docs/onec-capabilities.md`); Skill самодостаточен и без него.
