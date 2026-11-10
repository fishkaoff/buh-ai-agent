# Возможности инфраструктуры 1С (MCP + OData)

Дата исследования: 10.11.2026, база `ai_agent` (OData 3.0, 2443 объекта). Проверено на практике; источник истины для своего состояния — `read_system_health_check`.

## 1. MCP-сервер `1c-odata` — 76 инструментов

Группы (полные сигнатуры — в MCP-каталоге, список — `search({ namespace: "1c-odata" })`):

| Группа | Инструменты (примеры) | Операции |
|---|---|---|
| `read.system` | `list_databases`, `list_organizations`, `health_check`, `data_freshness` | чтение состояния |
| `read.schema` | `list_entities`, `describe_entity` | метаданные (объекты, поля, типы, связи) |
| `read.counterparty` | `find_counterparty`, `get_counterparty`, `get_customer_history`, `get_supplier_history`, `get_reconciliation` | контрагенты и взаиморасчёты |
| `read.document` | `search_documents`, `get_document` | документы (поиск по виду/номеру/периоду/контрагенту; чтение с табличными частями) |
| `read.accounting` | `get_account_card`, `get_account_turnover`, `get_document_postings`, `check_month_close`, `get_balance_origin`, settlement_settings | учёт: ОСВ, проводки, закрытие месяца |
| `read.analytics` | `get_debtors`, `get_creditors`, `get_cash_balance`, `get_cashflow`, `get_sales`, `get_sales_breakdown`, `get_unpaid_invoices`, `get_inventory`, `get_payments_breakdown`, `get_purchases_breakdown`, `get_taxes_paid`, `get_deal_history` | аналитика |
| `read.audit` | `get_document_history` | время документа (выводимое) |
| `read.organization` | `get_organization_card` | реквизиты организации |
| `write.counterparty` | `create_counterparty`, `update_counterparty`, `create_bank_account`, `create_contact_person`, `create_group`, `set_group` | контрагенты: создание/изменение |
| `write.catalog` | `create_contract`, `create_nomenclature`, `update_nomenclature` | договоры, номенклатура |
| `write.entity` | `create_folder`, `move_to_folder`, `update_entity`, `mark_for_deletion` | универсальные изменения справочников |
| `write.document` | `post_document`, `copy_document`, `add_document_line`, `update_document_lines`, `remove_document_line`, `align_bank_payment_amounts`, `apply_bank_settlement_settings` | документы: проведение, копирование, правки строк |
| `write.sales` | `create_invoice`, `create_shipment`, `create_act`, `create_services_act`, `create_issued_invoice` | продажи: счёт, реализация, акт, счёт-фактура |
| `write.purchase` | `create_purchase`, `create_supplier_invoice`, `create_received_invoice` | закупки |
| `write.money` | `create_payment`, `create_bank_writeoff`, `create_cash_receipt`, `create_cash_payment`, `create_payout_order` | деньги |
| `write.warehouse` | `create_transfer`, `create_inventory`, `create_surplus`, `create_writeoff`, `create_return_from_customer`, `create_return_to_supplier` | склад |
| `write.accounting` | `set_settlement_settings` | настройки расчётов |
| `write.operation_status` | состояние операции записи | идемпотентность |

### Общие правила MCP

- Запись — двухфазная: **dry-run (по умолчанию) → показ пользователю → `confirm: true` + тот же `operationId`**. Повтор подтверждения с тем же `operationId` не создаёт дубликат.
- Проведение — отдельная операция (`write_document_post_document`), тоже dry-run/confirm.
- После каждой записи — контрольное чтение (поле `verified`, `readback`).
- Ограничение скорости: 1С обрабатывает запросы одной учётки по очереди — вызовы только последовательные.

## 2. OData (`standard.odata`, версия 3.0)

Прямой доступ тем же данным: `config/onec-config.json` + `config/onec/odata-client.js`. Ключевое (проверено):

- `$format=json` обязателен; `$filter=substringof('x', Поле)` и `eq` — работают; `contains`/`tolower` — 400.
- `$orderby/$top/$skip/$select` — работают; key-lookup `EntitySet(guid'...')` — работает.
- `$expand` табличных частей — 501; читать через `EntitySet_Часть?$filter=Ref_Key eq guid'...'`.
- POST — создание (201, автонумерация `Number`/`Code`); PATCH — изменение; табличные части — массивами в теле.
- Ошибки: `{"odata.error":{"code","message":{"value"}}}`; 401 — креды; 404(HTML) — путь; 501 — опция.
- Даты — `YYYY-MM-DDT00:00:00` (без `Z`).

## 3. Что НЕВОЗМОЖНО через текущую инфраструктуру (зафиксировано)

| Возможность | Статус | Альтернатива |
|---|---|---|
| Печатные формы (счёт, УПД, акт) | ❌ нет ни в OData, ни в MCP | печать человеком из 1С; доработка: HTTP-сервис в 1С (см. Skill `onec-print-forms`) |
| Экспорт PDF | ❌ | там же |
| Физическое удаление объектов | ❌ | только `mark_for_deletion` (мягкая) |
| Закрытие месяца, ручные проводки | ❌ (только проверка `check_month_close`) | человек в 1С |
| Поиск номенклатуры MCP-инструментом | ❌ (есть только поиск контрагентов) | прямой OData-запрос (Skill `onec-nomenclature`) |
| Ставка НДС 5%/7%/22% в документах | ❌ конфигурация не обновлена: перечисление `СтавкиНДС` = БезНДС, НДС0, НДС10, НДС10_110, НДС18, НДС18_118, НДС20, НДС20_120 (проверено записью — 400) | обновить конфигурацию 1С; до этого использовать НДС20/БезНДС и явно предупреждать пользователя |
| История проведения (время) | ограничено: `read_audit_get_document_history` даёт только выводимое время | — |
| Изменение проведённого документа | ❌ (сначала отмена проведения) | цикл unpost → правка → post (проверен) |
| Регистр «Счета учёта расчётов с контрагентами» | не опубликован в OData (замечание MCP) | счета расчётов — по умолчанию 62.01/60.01 |

## 4. Замечания по надёжности

- MCP-схема допускает `vatRate: НДС5/НДС7/НДС22`, но фактическая конфигурация их отвергает — **проверяйте допустимость ставки по `$metadata`** (Skill `onec-validation`) и не полагайтесь на список из схемы инструмента.
- MCP **не рассчитывает `СуммаНДС` строк** счёта/реализации — рассчитывайте и проверяйте сами (при записи счёта PATCH-ом, для реализации — до проведения, иначе не будет проводки Дт 90.03 Кт 68.02).
- Ссылка на счёт-основание в реализации хранится в шапке И в строках: `write_entity_update_entity` заполняет шапку; строки — при замене табличной части.

## 5. Безопасность

- База `ai_agent` — единственная подключённая, назначена «для проверки автоматизации».
- Правила (Skills `onec-document-management`, `onec-validation`): предпросмотр payload перед любой записью; проведение — только после явного разрешения; дублей не создавать; проверять результат каждой записи.
- **Важно**: Skills (`.opencode/skills/onec-*`) сознательно НЕ зависят от этого MCP — они описывают те же операции в терминах прямых OData-запросов (см. `docs/onec-skills-map.md`), чтобы работать без MCP в любом runtime (в т.ч. LangGraph). MCP — необязательный ускоритель с предпросмотром/подтверждением.
