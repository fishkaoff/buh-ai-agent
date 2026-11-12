"""Инструменты 1С: контрагенты, договоры, номенклатура, документы.

Каждый Tool — типизированная операция над сервисами 1С. Tools возвращают
JSON-строку `{"ok": true, "data": ...}` или `{"ok": false, "error": ...}`,
понятную для агента. Ошибки не содержат stack traces.

Мультибазность: каждый Tool принимает аргумент `database` — имя базы 1С.
Если баз несколько, агент обязан выбирать базу по запросу пользователя
(неясно — уточнить у пользователя); при одной базе аргумент не нужен.

Официальные PDF печатных форм: при создании счёта приложение само забирает
PDF счёта и УПД у HTTP-сервиса печати 1С и прикладывает к ответу через
side-channel (`AgentFile` в контексте диалога) — файлы не хранятся и не
попадают в контекст LLM; в результате Tools видны только метаданные.

Ограничения:
- Tool не выполняет произвольный код/SQL/скрипты из LLM;
- идентификаторы объектов 1С (Ref_Key) — только из результатов Tools;
- read-операции не изменяют данные; write-операции создают объекты
  через сервисы 1С (с проверкой на дубликаты).
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, tool

from buh_ai_agent.agent.context import (
    AgentFile,
    MissingDialogContextError,
    get_dialog_context,
)
from buh_ai_agent.integrations.onec.client import OnecClient
from buh_ai_agent.integrations.onec.config import OnecConnectionConfig
from buh_ai_agent.integrations.onec.entities import (
    ENTITY_COUNTERPARTIES,
    ENTITY_REALIZATION,
    ENTITY_SALES_INVOICE,
    ENUM_VAT_RATES,
)
from buh_ai_agent.integrations.onec.registry import OnecClients
from buh_ai_agent.services import (
    contracts,
    counterparties,
    factures,
    invoices,
    nomenclature,
    print_pdf,
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


def _attach_pdf(name: str, data: bytes, kind: str) -> bool:
    """Прикладывает PDF к ответу текущего хода диалога (без сохранения).

    Файл уходит клиенту через side-channel (AgentFile) и не попадает в
    контекст LLM. Вне диалога (юнит-тесты) файла некуда приложить — False.

    Args:
        name: Имя файла.
        data: Содержимое PDF.
        kind: Тип («invoice», «upd»).

    Returns:
        True — файл приложен к контексту диалога.
    """
    try:
        context = get_dialog_context()
    except MissingDialogContextError:
        return False
    context.attach_file(AgentFile(name=name, content_type="application/pdf", data=data, kind=kind))
    return True


def make_onec_tools(
    clients: OnecClients,
    print_transport: Any | None = None,
) -> list[BaseTool]:
    """Создаёт инструменты 1С: контрагенты, договоры, номенклатура, документы.

    Args:
        clients: Реестр подключений к базам 1С (одна или несколько баз).
        print_transport: httpx-транспорт HTTP-сервиса печати (для тестов);
            None — обычный сетевой.

    Returns:
        Список LangChain-инструментов.
    """

    @tool
    async def find_counterparty(name: str = "", inn: str = "", database: str = "") -> str:
        """Ищет контрагента по наименованию и/или ИНН.

        ИНН главнее наименования. Поиск по наименованию устойчив к формату:
        передавайте как сказал пользователь — пробелы, кавычки, регистр и
        юридическая форма (ООО, ИП) не важны («Логистик Плюс» найдёт и
        «ЛогистикПлюс»). Возвращает список найденных контрагентов
        (Ref_Key, наименование, ИНН), точные совпадения — первыми.
        Пустой список — контрагент не найден; уточните у пользователя,
        создать ли нового.

        Args:
            name: Наименование (как сказал пользователь).
            inn: ИНН (главнее наименования).
            database: Имя базы 1С (обязательно при нескольких базах).
        """
        try:
            client, _ = clients.resolve(database)
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
        name: str, inn: str = "", kpp: str = "", full_name: str = "", database: str = ""
    ) -> str:
        """Создаёт контрагента. Перед созданием проверяет дубликаты (по ИНН и наименованию).

        Если контрагент уже существует — вернётся ошибка с его Ref_Key;
        в этом случае используйте существующего контрагента вместо создания.

        Args:
            name: Наименование (как сказал пользователь).
            inn: ИНН.
            kpp: КПП.
            full_name: Полное наименование.
            database: Имя базы 1С (обязательно при нескольких базах).
        """
        try:
            client, _ = clients.resolve(database)
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
    async def find_contract(counterparty_key: str, kind: str = "", database: str = "") -> str:
        """Ищет договоры контрагента по виду (например «СПокупателем»).

        Возвращает список договоров (Ref_Key, наименование, номер, дата).
        Пустой список — договоров нет; уточните у пользователя, создать ли новый.

        Args:
            counterparty_key: Ref_Key контрагента (из find_counterparty).
            kind: Вид договора («СПокупателем» — продажа; «СПоставщиком» — закупка).
            database: Имя базы 1С (обязательно при нескольких базах).
        """
        try:
            client, _ = clients.resolve(database)
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
        counterparty_key: str,
        kind: str = "СПокупателем",
        number: str = "",
        date: str = "",
        database: str = "",
    ) -> str:
        """Создаёт договор контрагента. Номер обязателен — сквозная нумерация по всем контрагентам.

        Аргументы:
            counterparty_key: Ref_Key контрагента (из find_counterparty).
            kind: Вид договора («СПокупателем» — продажа; «СПоставщиком» — закупка).
            number: Номер (пусто — определяется автоматически: max числовых
                номеров по ВСЕМ договорам базы + 1).
            date: Дата «YYYY-MM-DD» (пусто — сегодня).
            database: Имя базы 1С (обязательно при нескольких базах).

        Договор без номера («б/н») не создаётся: если номер определить нельзя,
        вернётся ошибка — запросите номер у пользователя. Если номер занят
        договором другого контрагента (или этого контрагента, но другого вида) —
        ошибка: попросите у пользователя другой номер. Если договор с таким
        номером, видом и контрагентом уже существует — вернётся он
        (already_exists=true), используйте его.
        """
        try:
            client, config = clients.resolve(database)
            # Нумерация сквозная: кандидат и занятость проверяются по всем
            # договорам базы, а не по договорам одного контрагента.
            all_contracts = await contracts.find_all_contracts(client)
            wanted = number.strip() or contracts.next_contract_number(all_contracts) or ""
            if not wanted:
                return tool_error(
                    "create_contract: не удалось определить номер автоматически "
                    "(в базе нет числовых номеров договоров). Уточните номер договора "
                    "у пользователя — договор без номера не создаётся."
                )
            same_owner = [
                c
                for c in all_contracts
                if c.owner_key == counterparty_key and c.number == wanted and c.kind == kind
            ]
            if same_owner:
                return tool_success(
                    {
                        "ref_key": same_owner[0].ref_key,
                        "description": same_owner[0].description,
                        "number": same_owner[0].number,
                        "already_exists": True,
                    }
                )
            taken = [c for c in all_contracts if c.number == wanted]
            if taken:
                holder = taken[0]
                return tool_error(
                    f"create_contract: номер {wanted} уже занят договором "
                    f"«{holder.description}» (Ref_Key {holder.ref_key}). Договор не создан: "
                    "номера договоров общие на всех контрагентов — уточните у "
                    "пользователя другой номер."
                )
            org = await reference.get_main_organization(
                client, inn=config.defaults.organization.inn
            )
            currency = await reference.get_currency(client, config.defaults.currency_code)
            created = await contracts.create_contract(
                client,
                counterparty_key=counterparty_key,
                organization_key=org.ref_key,
                currency_key=currency.ref_key,
                kind=kind,
                number=wanted,
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
    async def find_nomenclature(query: str, database: str = "") -> str:
        """Ищет позиции номенклатуры по подстроке наименования.

        Возвращает список найденных позиций (Ref_Key, наименование, услуга/товар).
        Пустой список — позиции нет; уточните у пользователя, создать ли новую
        (услуга или товар).

        Args:
            query: Подстрока наименования.
            database: Имя базы 1С (обязательно при нескольких базах).
        """
        try:
            client, _ = clients.resolve(database)
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
    async def create_nomenclature(name: str, is_service: bool, database: str = "") -> str:
        """Создаёт позицию номенклатуры (услуга или товар).

        Аргументы:
            name: Наименование (как назвал пользователь).
            is_service: True — услуга, False — товар.
            database: Имя базы 1С (обязательно при нескольких базах).

        Перед созданием проверяет дубликаты по наименованию; если позиция
        уже существует — вернётся ошибка с её Ref_Key.
        """
        try:
            client, _ = clients.resolve(database)
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
        database: str = "",
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
            database: Имя базы 1С (обязательно при нескольких базах).

        Для каждой позиции номенклатура ищется по наименованию; если её нет —
        создаётся (услуга или товар). Ставка НДС проверяется по $metadata 1С.
        Возвращает созданные документы (счёт, реализация, счёт-фактура/УПД).
        Официальные PDF счёта и УПД прикладываются к ответу автоматически
        (HTTP-сервис печати 1С); если они недоступны — черновики печатных форм.
        """
        try:
            client, config = clients.resolve(database)
            return await _create_sales_invoice_flow(
                client,
                config,
                counterparty_key=counterparty_key,
                contract_key=contract_key,
                lines=lines,
                vat_rate=vat_rate,
                includes_vat=includes_vat,
                force_new=force_new,
                print_transport=print_transport,
            )
        except Exception as error:
            return tool_error(f"create_sales_invoice: {error}")

    @tool
    async def get_document(document_type: str, ref_key: str, database: str = "") -> str:
        """Читает документ 1С: шапку и строки.

        Аргументы:
            document_type: Тип документа («invoice» — счёт, «realization» — реализация).
            ref_key: Ref_Key документа (из результатов Tools).
            database: Имя базы 1С (обязательно при нескольких базах).

        Возвращает человекочитаемую сводку документа.
        """
        try:
            client, _ = clients.resolve(database)
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
        invoice_ref_key: str, lines: list[dict[str, Any]], vat_rate: str = "", database: str = ""
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
            database: Имя базы 1С (обязательно при нескольких базах).

        Изменение допустимо, только если счёт и реализация непроведены
        (проверяется в 1С). Счёт-фактура (УПД) обновления не требует:
        её сумма вычисляется при проведении.
        """
        try:
            client, _ = clients.resolve(database)
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
    async def list_allowed_vat_rates(database: str = "") -> str:
        """Возвращает список допустимых ставок НДС из $metadata 1С.

        Args:
            database: Имя базы 1С (обязательно при нескольких базах).
        """
        try:
            client, _ = clients.resolve(database)
            values = await client.list_enum_values(ENUM_VAT_RATES)
            return tool_success({"rates": values})
        except Exception as error:
            return tool_error(f"list_allowed_vat_rates: {error}")

    @tool
    async def export_document_pdf(document_type: str, ref_key: str, database: str = "") -> str:
        """Возвращает официальную печатную форму документа в PDF (счёт, УПД).

        PDF формирует сама 1С (HTTP-сервис печати в расширении) и прикладывается
        к ответу пользователю — файлы не сохраняются. Это официальная печатная
        форма, а не черновик.

        Аргументы:
            document_type: Тип документа: «invoice» — счёт на оплату,
                «realization» — УПД (печатная форма УПД формируется из
                реализации товаров и услуг; нужен Ref_Key реализации).
            ref_key: Ref_Key документа (из результатов Tools).
            database: Имя базы 1С (обязательно при нескольких базах).

        Если сервис печати не настроен — вернётся ошибка с инструкцией;
        тогда предложите пользователю черновик печатной формы (он есть
        в результатах create_sales_invoice) или печать из 1С вручную.
        """
        try:
            client, config = clients.resolve(database)
            pdf_bytes = await print_pdf.download_print_form_pdf(
                config, document_type, ref_key, transport=print_transport
            )
            number = ""
            prefix = "schet"
            kind = document_type
            if document_type == "invoice":
                entity = ENTITY_SALES_INVOICE
                prefix = "schet"
            elif document_type == "realization":
                entity = ENTITY_REALIZATION
                prefix = "upd"
                kind = "upd"
            else:
                return tool_error(
                    f"Неизвестный тип документа: {document_type} (доступны: invoice, realization)."
                )
            try:
                header = await client.get_entity(entity, ref_key, select="Number")
                number = str(header.get("Number", "") or "")
            except Exception:
                number = ""
            name = print_pdf.pdf_filename(prefix, number=number, ref_key=ref_key)
            attached = _attach_pdf(name, pdf_bytes, kind)
            return tool_success(
                {
                    "name": name,
                    "size": len(pdf_bytes),
                    "number": number,
                    "document": document_type,
                    "attached_to_reply": attached,
                    "source": "HTTP-сервис печати 1С (официальная печатная форма)",
                }
            )
        except Exception as error:
            return tool_error(f"export_document_pdf: {error}")

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
        export_document_pdf,
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
    print_transport: Any | None = None,
) -> str:
    """Полный сценарий: счёт → реализация → счёт-фактура (УПД) → PDF.

    1. Номенклатура каждой позиции ищется по наименованию; если её нет —
       создаётся (услуга или товар).
    2. Организация, банковский счёт, валюта — из справочников.
    3. Ставка НДС проверяется по $metadata 1С.
    4. Антидубликат: непроведённые счёта контрагента за сегодня блокируют
       создание (переопределяется только force_new=true).
    5. Создаётся счёт, затем реализация (связанная со счётом),
       затем счёт-фактура (УПД).
    6. Официальные PDF счёта и УПД скачиваются у HTTP-сервиса печати 1С
       и прикладываются к ответу (не сохраняются); черновики — fallback.
    7. Возвращает созданные документы и метаданные PDF.

    Args:
        force_new: True — создать новый счёт, даже если есть непроведённые
            счёта контрагента за сегодня (после уточнения у пользователя).
        print_transport: httpx-транспорт HTTP-сервиса печати (для тестов).
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

    # 7. Официальные PDF (счёт и УПД) — формирует HTTP-сервис печати 1С,
    #    прикладываются к ответу через side-channel, не сохраняются.
    invoice_pdf, upd_pdf, pdf_errors = await _fetch_print_forms(
        config,
        invoice_ref_key=invoice.ref_key,
        invoice_number=invoice.number,
        realization_ref_key=realization.ref_key,
        realization_number=realization.number,
        transport=print_transport,
    )

    # 8. Черновики печатных форм — только если официальные PDF не получены:
    #    наименование контрагента — из 1С.
    counterparty = await client.get_entity(
        ENTITY_COUNTERPARTIES, counterparty_key, select="Ref_Key,Description"
    )
    counterparty_name = str(counterparty.get("Description", "") or "")
    result: dict[str, Any] = {
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
    }
    if invoice_pdf is not None:
        result["invoice_pdf"] = invoice_pdf
    if upd_pdf is not None:
        result["upd_pdf"] = upd_pdf
    if pdf_errors:
        result["pdf_errors"] = pdf_errors
    if invoice_pdf is None:
        result["invoice_draft"] = render_invoice_draft(
            invoice,
            org_name=org.description,
            org_inn=org.inn,
            counterparty_name=counterparty_name,
        )
    if upd_pdf is None:
        result["upd_draft"] = render_upd_draft(
            realization,
            org_name=org.description,
            counterparty_name=counterparty_name,
        )
    return tool_success(result)


async def _fetch_print_forms(
    config: OnecConnectionConfig,
    *,
    invoice_ref_key: str,
    invoice_number: str,
    realization_ref_key: str,
    realization_number: str,
    transport: Any | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str]:
    """Скачивает официальные PDF счёта и УПД и прикладывает их к ответу.

    УПД печатается из реализации товаров и услуг (шаблон `realization`
    HTTP-сервиса печати). Скачивания независимы и best-effort: ошибка PDF
    не отменяет созданные документы, а возвращается текстом (`pdf_errors`).

    Args:
        config: Конфигурация базы (print_service_url).
        invoice_ref_key: Ref_Key счёта.
        invoice_number: Номер счёта (для имени файла).
        realization_ref_key: Ref_Key реализации (для УПД).
        realization_number: Номер реализации (для имени файла УПД).
        transport: httpx-транспорт (для тестов).

    Returns:
        Тройка (метаданные PDF счёта | None, метаданные PDF УПД | None,
        текст ошибок через «;» или пустая строка).
    """
    if not config.print_service_url:
        return None, None, ""
    invoice_meta: dict[str, Any] | None = None
    upd_meta: dict[str, Any] | None = None
    errors: list[str] = []
    try:
        pdf = await print_pdf.download_print_form_pdf(
            config, "invoice", invoice_ref_key, transport=transport
        )
        name = print_pdf.pdf_filename("schet", number=invoice_number, ref_key=invoice_ref_key)
        _attach_pdf(name, pdf, "invoice")
        invoice_meta = {"name": name, "size": len(pdf)}
    except Exception as error:  # noqa: BLE001 — PDF не должен ломать создание счёта
        errors.append(f"PDF счёта: {error}")
    try:
        pdf = await print_pdf.download_print_form_pdf(
            config, "realization", realization_ref_key, transport=transport
        )
        name = print_pdf.pdf_filename("upd", number=realization_number, ref_key=realization_ref_key)
        _attach_pdf(name, pdf, "upd")
        upd_meta = {"name": name, "size": len(pdf)}
    except Exception as error:  # noqa: BLE001 — PDF не должен ломать создание счёта
        errors.append(f"PDF УПД: {error}")
    return invoice_meta, upd_meta, "; ".join(errors)
