"""Инструменты 1С: контрагенты, договоры, номенклатура, документы.

Каждый Tool — типизированная операция над сервисами 1С. Tools возвращают
JSON-строку `{"ok": true, "data": ...}` или `{"ok": false, "error": ...}`,
понятную для агента. Ошибки не содержат stack traces.

Ограничения:
- Tool не выполняет произвольный код/SQL/скрипты из LLM;
- идентификаторы объектов 1С (Ref_Key) — только из результатов Tools;
- read-операции не изменяют данные; write-операции создают объекты
  через сервисы 1С (с проверкой на дубликаты).
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, tool

from buh_ai_agent.integrations.onec.client import OnecClient
from buh_ai_agent.integrations.onec.config import OnecConnectionConfig
from buh_ai_agent.integrations.onec.entities import (
    ENTITY_COUNTERPARTIES,
    ENUM_VAT_RATES,
)
from buh_ai_agent.services import (
    contracts,
    counterparties,
    factures,
    invoices,
    nomenclature,
    realizations,
    reference,
    vat,
)
from buh_ai_agent.services.print_forms import render_invoice_draft, render_upd_draft
from buh_ai_agent.tools.base import tool_error, tool_success


def _today_iso() -> str:
    """Текущая дата в формате YYYY-MM-DD (по местному времени сервера)."""
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d")


def make_onec_tools(client: OnecClient, config: OnecConnectionConfig) -> list[BaseTool]:
    """Создаёт инструменты 1С: контрагенты, договоры, номенклатура, документы.

    Args:
        client: OData-клиент 1С.
        config: Конфигурация базы (дефолты — НДС, валюта).

    Returns:
        Список LangChain-инструментов.
    """

    @tool
    async def find_counterparty(name: str = "", inn: str = "") -> str:
        """Ищет контрагента по наименованию и/или ИНН.

        ИНН главнее наименования. Возвращает список найденных контрагентов
        (Ref_Key, наименование, ИНН). Пустой список — контрагент не найден;
        уточните у пользователя, создать ли нового.
        """
        try:
            if not name and not inn:
                return tool_error("Укажите наименование или ИНН контрагента.")
            found = await counterparties.find_counterparty(client, name=name, inn=inn)
            return tool_success(
                {
                    "count": len(found),
                    "counterparties": [
                        {
                            "ref_key": c.ref_key,
                            "description": c.description,
                            "inn": c.inn,
                            "kpp": c.kpp,
                        }
                        for c in found
                    ],
                }
            )
        except Exception as error:
            return tool_error(f"find_counterparty: {error}")

    @tool
    async def create_counterparty(
        name: str, inn: str = "", kpp: str = "", full_name: str = ""
    ) -> str:
        """Создаёт контрагента. Перед созданием проверяет дубликаты (по ИНН и наименованию).

        Если контрагент уже существует — вернётся ошибка с его Ref_Key;
        в этом случае используйте существующего контрагента вместо создания.
        """
        try:
            created = await counterparties.create_counterparty(
                client, name=name, inn=inn, kpp=kpp, full_name=full_name
            )
            return tool_success(
                {
                    "ref_key": created.ref_key,
                    "description": created.description,
                    "inn": created.inn,
                }
            )
        except Exception as error:
            return tool_error(f"create_counterparty: {error}")

    @tool
    async def find_contract(counterparty_key: str, kind: str = "") -> str:
        """Ищет договоры контрагента по виду (например «СПокупателем»).

        Возвращает список договоров (Ref_Key, наименование, номер, дата).
        Пустой список — договоров нет; уточните у пользователя, создать ли новый.
        """
        try:
            found = await contracts.find_contracts(client, counterparty_key, kind=kind)
            return tool_success(
                {
                    "count": len(found),
                    "contracts": [
                        {
                            "ref_key": c.ref_key,
                            "description": c.description,
                            "number": c.number,
                            "date": c.date[:10],
                            "kind": c.kind,
                            "closed": c.closed,
                        }
                        for c in found
                    ],
                }
            )
        except Exception as error:
            return tool_error(f"find_contract: {error}")

    @tool
    async def create_contract(
        counterparty_key: str, kind: str = "СПокупателем", number: str = "", date: str = ""
    ) -> str:
        """Создаёт договор контрагента. Номер — по правилу max(числовых Номер)+1, если не задан.

        Аргументы:
            counterparty_key: Ref_Key контрагента (из find_counterparty).
            kind: Вид договора («СПокупателем» — продажа; «СПоставщиком» — закупка).
            number: Номер (пусто — автоматически).
            date: Дата «YYYY-MM-DD» (пусто — сегодня).

        Если договор с таким номером уже существует — вернётся существующий
        (already_exists=True), используйте его.
        """
        try:
            existing = await contracts.find_contracts(client, counterparty_key, kind=kind)
            number = number or contracts.next_contract_number(existing) or ""
            if number:
                duplicate = [c for c in existing if c.number == number]
                if duplicate:
                    return tool_success(
                        {
                            "ref_key": duplicate[0].ref_key,
                            "description": duplicate[0].description,
                            "number": duplicate[0].number,
                            "already_exists": True,
                        }
                    )
            org = await reference.get_main_organization(client)
            currency = await reference.get_currency(client, config.defaults.currency_code)
            created = await contracts.create_contract(
                client,
                counterparty_key=counterparty_key,
                organization_key=org.ref_key,
                currency_key=currency.ref_key,
                kind=kind,
                number=number,
                document_date=date or None,
            )
            return tool_success(
                {
                    "ref_key": created.ref_key,
                    "description": created.description,
                    "number": created.number,
                    "kind": created.kind,
                }
            )
        except Exception as error:
            return tool_error(f"create_contract: {error}")

    @tool
    async def find_nomenclature(query: str) -> str:
        """Ищет позиции номенклатуры по подстроке наименования.

        Возвращает список найденных позиций (Ref_Key, наименование, услуга/товар).
        Пустой список — позиции нет; уточните у пользователя, создать ли новую
        (услуга или товар).
        """
        try:
            if not query:
                return tool_error("Укажите наименование или подстроку.")
            found = await nomenclature.find_nomenclature(client, query)
            return tool_success(
                {
                    "count": len(found),
                    "items": [
                        {
                            "ref_key": n.ref_key,
                            "description": n.description,
                            "is_service": n.is_service,
                        }
                        for n in found
                    ],
                }
            )
        except Exception as error:
            return tool_error(f"find_nomenclature: {error}")

    @tool
    async def create_nomenclature(name: str, is_service: bool) -> str:
        """Создаёт позицию номенклатуры (услуга или товар).

        Аргументы:
            name: Наименование (как назвал пользователь).
            is_service: True — услуга, False — товар.

        Перед созданием проверяет дубликаты по наименованию; если позиция
        уже существует — вернётся ошибка с её Ref_Key.
        """
        try:
            created = await nomenclature.create_nomenclature(
                client, name=name, is_service=is_service
            )
            return tool_success(
                {
                    "ref_key": created.ref_key,
                    "description": created.description,
                    "is_service": created.is_service,
                }
            )
        except Exception as error:
            return tool_error(f"create_nomenclature: {error}")

    @tool
    async def create_sales_invoice(
        counterparty_key: str,
        contract_key: str,
        lines: list[dict[str, Any]],
        vat_rate: str = "",
        includes_vat: bool = True,
        force_new: bool = False,
    ) -> str:
        """Создаёт счёт на оплату покупателю, реализацию и УПД (счёт-фактуру).

        Аргументы:
            counterparty_key: Ref_Key контрагента (из find_counterparty).
            contract_key: Ref_Key договора (из find_contract/create_contract).
            lines: Список позиций, каждая — словарь:
                name: Наименование номенклатуры (обязательно).
                quantity: Количество (по умолчанию 1).
                price: Цена (обязательно).
                is_service: True — услуга, False — товар.
            vat_rate: Ставка НДС («НДС5», «НДС20», «БезНДС»); пусто — дефолт из конфигурации.
            includes_vat: Сумма включает НДС (True — «в том числе»).
            force_new: True — создать новый счёт, хотя у контрагента уже есть
                непроведённые счёта за сегодня (только после явного подтверждения
                пользователя; обычно вместо этого дорабатывают существующий счёт
                через update_sales_invoice_lines).

        Для каждой позиции номенклатура ищется по наименованию; если её нет —
        создаётся (услуга или товар). Ставка НДС проверяется по $metadata 1С.
        Возвращает созданные документы (счёт, реализация, счёт-фактура/УПД)
        и черновик печатной формы.
        """
        try:
            return await _create_sales_invoice_flow(
                client,
                config,
                counterparty_key=counterparty_key,
                contract_key=contract_key,
                lines=lines,
                vat_rate=vat_rate,
                includes_vat=includes_vat,
                force_new=force_new,
            )
        except Exception as error:
            return tool_error(f"create_sales_invoice: {error}")

    @tool
    async def get_document(document_type: str, ref_key: str) -> str:
        """Читает документ 1С: шапку и строки.

        Аргументы:
            document_type: Тип документа («invoice» — счёт, «realization» — реализация).
            ref_key: Ref_Key документа (из результатов Tools).

        Возвращает человекочитаемую сводку документа.
        """
        try:
            if document_type == "invoice":
                doc = await invoices.read_invoice(client, ref_key)
            elif document_type == "realization":
                doc = await realizations.read_realization(client, ref_key)
            else:
                return tool_error(f"Неизвестный тип документа: {document_type}")
            return tool_success({"summary": doc.summary()})
        except Exception as error:
            return tool_error(f"get_document: {error}")

    @tool
    async def update_sales_invoice_lines(
        invoice_ref_key: str, lines: list[dict[str, Any]], vat_rate: str = ""
    ) -> str:
        """Заменяет строки существующего счёта и обновляет связанную реализацию.

        Используйте для доработки счёта в рамках активной операции
        («добавь позицию», «измени количество»). Не создавайте новый счёт,
        если счёт по операции уже создан — дорабатывайте существующий.

        Аргументы:
            invoice_ref_key: Ref_Key счёта (из результатов create_sales_invoice).
            lines: ПОЛНЫЙ новый список позиций счёта (существующие + новые),
                каждая: name, quantity, price, is_service.
            vat_rate: Ставка НДС; пусто — ставка из существующих строк счёта.

        Изменение допустимо, только если счёт и реализация непроведены
        (проверяется в 1С). Счёт-фактура (УПД) обновления не требует:
        её сумма вычисляется при проведении.
        """
        try:
            rate_default = (vat_rate or "").strip()
            invoice = await invoices.read_invoice(client, invoice_ref_key)
            if invoice.posted:
                return tool_error(f"Счёт №{invoice.number} проведён в 1С — изменение недопустимо.")
            if not invoice.lines and not rate_default:
                return tool_error("Ставка НДС не определена: счёт без строк; передайте vat_rate.")
            rate = rate_default or str(invoice.lines[0].vat_rate)
            allowed = await client.list_enum_values(ENUM_VAT_RATES)
            if rate not in allowed:
                return tool_error(
                    f"Ставка НДС {rate!r} отсутствует в конфигурации 1С. "
                    f"Допустимые: {', '.join(allowed)}. Уточните у пользователя, чем заменить."
                )

            invoice_lines = []
            for line in lines:
                name = str(line.get("name") or "").strip()
                if not name:
                    return tool_error("У каждой позиции должно быть наименование.")
                found = await nomenclature.find_exact_nomenclature(client, name)
                if found is None:
                    found = await nomenclature.create_nomenclature(
                        client, name=name, is_service=bool(line.get("is_service", False))
                    )
                invoice_lines.append(
                    {
                        "nomenclature_key": found.ref_key,
                        "content": name,
                        "quantity": float(line.get("quantity", 1)),
                        "price": float(line.get("price", 0)),
                        "vat_rate": rate,
                    }
                )

            updated_invoice = await invoices.update_invoice_lines(
                client,
                invoice,
                invoice_lines,
                vat_rate=rate,
                includes_vat=invoice.includes_vat,
            )

            realization = await realizations.find_realization_by_invoice(client, invoice.ref_key)
            realization_updated = ""
            if realization is not None and not realization.posted:
                updated = await realizations.update_realization_lines(
                    client,
                    realization,
                    invoice_lines,
                    vat_rate=rate,
                    includes_vat=realization.includes_vat,
                    invoice_key=invoice.ref_key,
                )
                realization_updated = f"{updated.number} на {updated.amount:.2f} ₽"
            elif realization is not None:
                realization_updated = (
                    f"№{realization.number} проведена в 1С — строки не изменены; "
                    "требуется синхронизация с бухгалтером."
                )

            return tool_success(
                {
                    "invoice": {
                        "ref_key": updated_invoice.ref_key,
                        "number": updated_invoice.number,
                        "amount": updated_invoice.amount,
                        "summary": updated_invoice.summary(),
                    },
                    "realization": realization_updated,
                }
            )
        except Exception as error:
            return tool_error(f"update_sales_invoice_lines: {error}")

    @tool
    async def list_allowed_vat_rates() -> str:
        """Возвращает список допустимых ставок НДС из $metadata 1С."""
        try:
            values = await client.list_enum_values(ENUM_VAT_RATES)
            return tool_success({"rates": values})
        except Exception as error:
            return tool_error(f"list_allowed_vat_rates: {error}")

    return [
        find_counterparty,
        create_counterparty,
        find_contract,
        create_contract,
        find_nomenclature,
        create_nomenclature,
        create_sales_invoice,
        get_document,
        list_allowed_vat_rates,
    ]


async def _create_sales_invoice_flow(
    client: OnecClient,
    config: OnecConnectionConfig,
    *,
    counterparty_key: str,
    contract_key: str,
    lines: list[dict[str, Any]],
    vat_rate: str,
    includes_vat: bool,
    force_new: bool = False,
) -> str:
    """Полный сценарий: счёт → реализация → счёт-фактура (УПД).

    1. Номенклатура каждой позиции ищется по наименованию; если её нет —
       создаётся (услуга или товар).
    2. Организация, банковский счёт, валюта — из справочников.
    3. Ставка НДС проверяется по $metadata 1С.
    4. Антидубликат: непроведённые счёта контрагента за сегодня блокируют
       создание (переопределяется только force_new=true).
    5. Создаётся счёт, затем реализация (связанная со счётом),
       затем счёт-фактура (УПД).
    6. Возвращает созданные документы и черновик печатной формы.

    Args:
        force_new: True — создать новый счёт, даже если есть непроведённые
            счёта контрагента за сегодня (после уточнения у пользователя).
    """
    rate = vat.resolve_rate(vat_rate or None, config.defaults.vat_rate)
    allowed = await client.list_enum_values(ENUM_VAT_RATES)
    if rate not in allowed:
        return tool_error(
            f"Ставка НДС {rate!r} отсутствует в конфигурации 1С. "
            f"Допустимые: {', '.join(allowed)}. Уточните у пользователя, чем заменить."
        )
    if not lines:
        return tool_error("Не переданы позиции счёта.")

    # Антидубликат: непроведённые счёта этого контрагента за сегодня.
    today = _today_iso()
    existing = await invoices.find_duplicate_invoices(
        client, counterparty_key, None, since_date=today
    )
    open_duplicates = [doc for doc in existing if not doc.posted]
    if open_duplicates and not force_new:
        listed = "; ".join(
            f"№{doc.number or 'б/н'} от {doc.date[:10]} на {doc.amount:.2f} ₽ "
            f"(Ref_Key {doc.ref_key})"
            for doc in open_duplicates
        )
        return tool_error(
            "Найдены непроведённые счёта этого контрагента за сегодня: " + listed + ". "
            "Не создавайте дубликат: если это тот же заказ — доработайте существующий "
            "счёт инструментом update_sales_invoice_lines (полный список позиций); "
            "если пользователь подтверждает новый отдельный счёт — повторите вызов "
            "с force_new=true."
        )

    # 1. Номенклатура каждой позиции.
    invoice_lines: list[dict[str, Any]] = []
    for line in lines:
        name = str(line.get("name") or "").strip()
        if not name:
            return tool_error("У каждой позиции должно быть наименование.")
        found = await nomenclature.find_exact_nomenclature(client, name)
        if found is None:
            found = await nomenclature.create_nomenclature(
                client, name=name, is_service=bool(line.get("is_service", False))
            )
        invoice_lines.append(
            {
                "nomenclature_key": found.ref_key,
                "content": name,
                "quantity": float(line.get("quantity", 1)),
                "price": float(line.get("price", 0)),
                "vat_rate": rate,
            }
        )

    # 2. Справочники: организация, банковский счёт, валюта.
    org = await reference.get_main_organization(client, inn=config.defaults.organization.inn)
    bank_account = await reference.get_org_bank_account(client, org.ref_key)
    if bank_account is None:
        return tool_error("Не найден банковский счёт организации.")
    currency = await reference.get_currency(client, config.defaults.currency_code)

    # 3. Payload счёта.
    payload = invoices.build_invoice_payload(
        organization_key=org.ref_key,
        counterparty_key=counterparty_key,
        contract_key=contract_key,
        bank_account_key=bank_account.ref_key,
        currency_key=currency.ref_key,
        lines=invoice_lines,
        vat_rate=rate,
        includes_vat=includes_vat,
    )
    invoice = await invoices.create_invoice(client, payload)

    # 5. Реализация (ссылка на счёт в шапке и строках).
    accounts = await realizations.get_accounting_refs(client)
    kind = "Услуги" if all(line.get("is_service", False) for line in lines) else "Товары"
    warehouse_key = ""
    if kind == "Товары":
        warehouse = await reference.get_warehouse(client)
        if warehouse is None:
            return tool_error("Для реализации товаров нужен склад, но он не найден.")
        warehouse_key = warehouse.ref_key
    realization_payload = realizations.build_realization_payload(
        organization_key=org.ref_key,
        counterparty_key=counterparty_key,
        contract_key=contract_key,
        invoice_key=invoice.ref_key,
        bank_account_key=bank_account.ref_key,
        accounts=accounts,
        lines=invoice_lines,
        kind=kind,
        warehouse_key=warehouse_key,
        vat_rate=rate,
        includes_vat=includes_vat,
    )
    realization = await realizations.create_realization(client, realization_payload)

    # 6. Счёт-фактура (УПД).
    facture = await factures.create_facture(client, realization.ref_key)

    # 7. Черновик печатной формы: наименование контрагента — из 1С.
    counterparty = await client.get_entity(
        ENTITY_COUNTERPARTIES, counterparty_key, select="Ref_Key,Description"
    )
    counterparty_name = str(counterparty.get("Description", "") or "")
    draft = render_invoice_draft(
        invoice,
        org_name=org.description,
        org_inn=org.inn,
        counterparty_name=counterparty_name,
    )
    upd_draft = render_upd_draft(
        realization,
        org_name=org.description,
        counterparty_name=counterparty_name,
    )
    return tool_success(
        {
            "invoice": {
                "ref_key": invoice.ref_key,
                "number": invoice.number,
                "date": invoice.date[:10],
                "amount": invoice.amount,
                "summary": invoice.summary(),
            },
            "realization": {
                "ref_key": realization.ref_key,
                "number": realization.number,
                "summary": realization.summary(),
            },
            "facture": {
                "ref_key": facture.ref_key,
                "number": facture.number,
                "summary": facture.summary(),
            },
            "invoice_draft": draft,
            "upd_draft": upd_draft,
        }
    )
