"""Юнит-тесты сервисов документов: счёт, реализация, счёт-фактура, черновики."""

import pytest
from tests.unit.onec_helpers import (
    ACCOUNT_GOODS_REF,
    ACCOUNT_REVENUE_REF,
    ACCOUNT_SETTLEMENT_REF,
    ACCOUNT_VAT_REF,
    ACCOUNTS_ROWS,
    BANK_ACCOUNT_REF,
    CONTRACT_REF,
    CONTRACTOR_REF,
    INVOICE_REF,
    NOMENCLATURE_REF,
    ORG_REF,
    REALIZATION_REF,
    VAT_INVOICE_REF,
    entity_ref,
    facture_row,
    invoice_line_row,
    invoice_row,
    make_client,
    make_transport,
    realization_row,
    realization_service_line_row,
)

from buh_ai_agent.integrations.onec.models import DocumentInfo, DocumentLine
from buh_ai_agent.services import factures, invoices, print_forms, realizations

# ------------------------------------------------------------------
# Счёт: payload
# ------------------------------------------------------------------


def test_build_invoice_payload() -> None:
    """Payload счёта по проверенному шаблону Skill onec-sales-invoices."""
    payload = invoices.build_invoice_payload(
        organization_key=ORG_REF,
        counterparty_key=CONTRACTOR_REF,
        contract_key=CONTRACT_REF,
        bank_account_key=BANK_ACCOUNT_REF,
        currency_key="rub",
        vat_rate="НДС20",
        includes_vat=True,
        document_date="2026-11-10",
        lines=[
            {
                "nomenclature_key": NOMENCLATURE_REF,
                "content": "Консультация",
                "quantity": 8,
                "price": 12500,
            }
        ],
    )
    assert payload["Date"] == "2026-11-10T00:00:00"
    assert payload["Posted"] is False
    assert payload["ВидОперации"] == "ТоварыИУслуги"
    assert payload["Организация_Key"] == ORG_REF
    assert payload["Контрагент_Key"] == CONTRACTOR_REF
    assert payload["ДоговорКонтрагента_Key"] == CONTRACT_REF
    assert payload["СтруктурнаяЕдиница_Key"] == BANK_ACCOUNT_REF
    assert payload["СуммаВключаетНДС"] is True
    assert payload["СуммаДокумента"] == 100000
    line = payload["Товары"][0]
    assert line["LineNumber"] == 1
    assert line["Номенклатура"] == NOMENCLATURE_REF
    assert line["Номенклатура_Type"] == "StandardODATA.Catalog_Номенклатура"
    assert line["Содержание"] == "Консультация"
    assert line["Количество"] == 8
    assert line["Цена"] == 12500
    assert line["Сумма"] == 100000
    assert line["СтавкаНДС"] == "НДС20"
    # 1С через OData не пересчитывает: 100000 × 20/120 = 16666.67
    assert line["СуммаНДС"] == pytest.approx(16666.67)
    assert "Number" not in payload  # 1С нумерует сама


def test_build_invoice_payload_multiple_lines() -> None:
    """`СуммаДокумента` = Σ строк; `СуммаНДС` каждой строки рассчитан."""
    payload = invoices.build_invoice_payload(
        organization_key=ORG_REF,
        counterparty_key=CONTRACTOR_REF,
        contract_key=CONTRACT_REF,
        bank_account_key=BANK_ACCOUNT_REF,
        currency_key="rub",
        vat_rate="НДС20",
        includes_vat=True,
        document_date="2026-11-10",
        lines=[
            {
                "nomenclature_key": NOMENCLATURE_REF,
                "content": "Позиция 1",
                "quantity": 1,
                "price": 60000,
            },
            {
                "nomenclature_key": NOMENCLATURE_REF,
                "content": "Позиция 2",
                "quantity": 2,
                "price": 20000,
            },
        ],
    )
    assert payload["СуммаДокумента"] == 100000
    assert payload["Товары"][1]["LineNumber"] == 2


def test_build_invoice_payload_no_vat() -> None:
    """Счёт «без НДС»: `ДокументБезНДС` + строки `БезНДС` с НДС 0."""
    payload = invoices.build_invoice_payload(
        organization_key=ORG_REF,
        counterparty_key=CONTRACTOR_REF,
        contract_key=CONTRACT_REF,
        bank_account_key=BANK_ACCOUNT_REF,
        currency_key="rub",
        vat_rate="БезНДС",
        includes_vat=False,
        document_date="2026-11-10",
        lines=[
            {
                "nomenclature_key": NOMENCLATURE_REF,
                "content": "Услуга",
                "quantity": 1,
                "price": 5000,
            }
        ],
    )
    assert payload["ДокументБезНДС"] is True
    assert payload["СуммаВключаетНДС"] is False
    assert payload["Товары"][0]["СтавкаНДС"] == "БезНДС"
    assert payload["Товары"][0]["СуммаНДС"] == 0


def test_build_invoice_payload_without_vat() -> None:
    """СуммаВключаетНДС=false: НДС «сверху» (5000 × 20/100 = 1000)."""
    payload = invoices.build_invoice_payload(
        organization_key=ORG_REF,
        counterparty_key=CONTRACTOR_REF,
        contract_key=CONTRACT_REF,
        bank_account_key=BANK_ACCOUNT_REF,
        currency_key="rub",
        vat_rate="НДС20",
        includes_vat=False,
        document_date="2026-11-10",
        lines=[
            {
                "nomenclature_key": NOMENCLATURE_REF,
                "content": "Услуга",
                "quantity": 1,
                "price": 5000,
            }
        ],
    )
    assert payload["Товары"][0]["СуммаНДС"] == pytest.approx(1000.0)


def test_build_invoice_payload_rejects_nan() -> None:
    """NaN/inf запрещены."""
    with pytest.raises(ValueError, match="NaN/inf"):
        invoices.build_invoice_payload(
            organization_key=ORG_REF,
            counterparty_key=CONTRACTOR_REF,
            contract_key=CONTRACT_REF,
            bank_account_key=BANK_ACCOUNT_REF,
            currency_key="rub",
            vat_rate="НДС20",
            includes_vat=True,
            document_date="2026-11-10",
            lines=[
                {
                    "nomenclature_key": NOMENCLATURE_REF,
                    "content": "x",
                    "quantity": float("nan"),
                    "price": 1,
                }
            ],
        )


def test_build_invoice_payload_invalid_rate() -> None:
    """Недопустимая ставка НДС отклоняется."""
    with pytest.raises(ValueError, match="Недопустимая ставка НДС"):
        invoices.build_invoice_payload(
            organization_key=ORG_REF,
            counterparty_key=CONTRACTOR_REF,
            contract_key=CONTRACT_REF,
            bank_account_key=BANK_ACCOUNT_REF,
            currency_key="rub",
            vat_rate="НДС7",
            includes_vat=True,
            document_date="2026-11-10",
            lines=[
                {
                    "nomenclature_key": NOMENCLATURE_REF,
                    "content": "x",
                    "quantity": 1,
                    "price": 1,
                }
            ],
        )


# ------------------------------------------------------------------
# Счёт: создание, чтение, дубликаты
# ------------------------------------------------------------------


async def test_create_invoice_posts_and_reads_back() -> None:
    """POST счёта → перечитаны шапка и строки."""
    transport = make_transport(
        {
            ("POST", "Document_СчетНаОплатуПокупателю"): entity_ref(INVOICE_REF, "0000-0000001"),
            ("GET", "Document_СчетНаОплатуПокупателю(guid'"): invoice_row(),
            ("GET", "Document_СчетНаОплатуПокупателю_Товары"): [
                invoice_line_row(),
                invoice_line_row(LineNumber=2, Содержание="Позиция 2"),
            ],
        }
    )
    async with make_client(transport) as client:
        payload = invoices.build_invoice_payload(
            organization_key=ORG_REF,
            counterparty_key=CONTRACTOR_REF,
            contract_key=CONTRACT_REF,
            bank_account_key=BANK_ACCOUNT_REF,
            currency_key="rub",
            vat_rate="НДС20",
            includes_vat=True,
            document_date="2026-11-10",
            lines=[
                {"nomenclature_key": NOMENCLATURE_REF, "content": "x", "quantity": 1, "price": 1}
            ],
        )
        doc = await invoices.create_invoice(client, payload)
    assert doc.ref_key == INVOICE_REF
    assert doc.number == "0000-0000001"
    assert doc.amount == 100000
    assert len(doc.lines) == 2
    assert doc.lines[0].content == "Консультация"


async def test_find_duplicate_invoices_by_amount() -> None:
    """Антидубликат: поиск счетов контрагента с равной суммой."""
    transport = make_transport(
        {
            ("GET", "Document_СчетНаОплатуПокупателю"): [
                invoice_row(СуммаДокумента=100000),
                invoice_row(СуммаДокумента=5000, Ref_Key="other"),
            ]
        }
    )
    async with make_client(transport) as client:
        found = await invoices.find_duplicate_invoices(
            client, CONTRACTOR_REF, 100000, since_date="2026-11-01"
        )
    assert len(found) == 1
    assert found[0].ref_key == INVOICE_REF


# ------------------------------------------------------------------
# Реализация
# ------------------------------------------------------------------


async def test_get_accounting_refs() -> None:
    """Ref_Key счетов учёта — ТОЛЬКО из плана счетов по коду."""
    transport = make_transport({("GET", "ChartOfAccounts_Хозрасчетный"): ACCOUNTS_ROWS})
    async with make_client(transport) as client:
        accounts = await realizations.get_accounting_refs(client)
    assert accounts["62.01"] == ACCOUNT_SETTLEMENT_REF
    assert accounts["90.01.1"] == ACCOUNT_REVENUE_REF
    assert accounts["90.03"] == ACCOUNT_VAT_REF
    assert accounts["41"] == ACCOUNT_GOODS_REF


def test_build_realization_payload_services() -> None:
    """Payload реализации-услуги: связь со счётом в шапке И в строках."""
    payload = realizations.build_realization_payload(
        organization_key=ORG_REF,
        counterparty_key=CONTRACTOR_REF,
        contract_key=CONTRACT_REF,
        invoice_key=INVOICE_REF,
        bank_account_key=BANK_ACCOUNT_REF,
        accounts={
            "62.01": ACCOUNT_SETTLEMENT_REF,
            "90.01.1": "r",
            "90.02.1": "e",
            "90.03": "v",
            "41": "g",
        },
        lines=[
            {
                "nomenclature_key": NOMENCLATURE_REF,
                "content": "Консультация",
                "quantity": 8,
                "price": 12500,
            }
        ],
        kind="Услуги",
        vat_rate="НДС20",
        includes_vat=True,
        document_date="2026-11-10",
    )
    assert payload["ВидОперации"] == "Услуги"
    assert payload["СчетНаОплатуПокупателю_Key"] == INVOICE_REF
    assert payload["СчетУчетаРасчетовСКонтрагентом_Key"] == ACCOUNT_SETTLEMENT_REF
    assert payload["СуммаДокумента"] == 100000
    assert payload["Услуги"][0]["СчетНаОплатуПокупателю_Key"] == INVOICE_REF
    assert payload["Услуги"][0]["СчетДоходов_Key"] == "r"
    assert payload["Услуги"][0]["СчетРасходов_Key"] == "e"
    assert payload["Услуги"][0]["СчетУчетаНДСПоРеализации_Key"] == "v"
    assert payload["Услуги"][0]["СуммаНДС"] == pytest.approx(16666.67)
    assert "Склад_Key" not in payload  # услуги не требуют склада


def test_build_realization_payload_goods_requires_warehouse() -> None:
    """Реализация товаров требует склад."""
    with pytest.raises(ValueError, match="Склад_Key"):
        realizations.build_realization_payload(
            organization_key=ORG_REF,
            counterparty_key=CONTRACTOR_REF,
            contract_key=CONTRACT_REF,
            invoice_key=INVOICE_REF,
            bank_account_key=BANK_ACCOUNT_REF,
            accounts={"62.01": "s", "90.01.1": "r", "90.02.1": "e", "90.03": "v", "41": "g"},
            lines=[
                {"nomenclature_key": NOMENCLATURE_REF, "content": "x", "quantity": 1, "price": 1}
            ],
            kind="Товары",
            vat_rate="НДС20",
            includes_vat=True,
        )


def test_build_realization_payload_goods() -> None:
    """Реализация товаров: склад и `СчетУчета_Key` (41)."""
    payload = realizations.build_realization_payload(
        organization_key=ORG_REF,
        counterparty_key=CONTRACTOR_REF,
        contract_key=CONTRACT_REF,
        invoice_key=INVOICE_REF,
        bank_account_key=BANK_ACCOUNT_REF,
        accounts={
            "62.01": "s",
            "90.01.1": "r",
            "90.02.1": "e",
            "90.03": "v",
            "41": ACCOUNT_GOODS_REF,
        },
        lines=[
            {
                "nomenclature_key": NOMENCLATURE_REF,
                "content": "Труба ПНД 40",
                "quantity": 1,
                "price": 1000,
            }
        ],
        kind="Товары",
        warehouse_key="wh",
        unit_key="unit",
        vat_rate="НДС20",
        includes_vat=True,
        document_date="2026-11-10",
    )
    assert payload["Склад_Key"] == "wh"
    assert payload["Товары"][0]["СчетУчета_Key"] == ACCOUNT_GOODS_REF
    assert payload["Товары"][0]["Номенклатура_Key"] == NOMENCLATURE_REF  # не составная ссылка


def test_build_realization_payload_invalid_kind() -> None:
    """Неверный вид операции отклоняется."""
    with pytest.raises(ValueError, match="Вид операции"):
        realizations.build_realization_payload(
            organization_key=ORG_REF,
            counterparty_key=CONTRACTOR_REF,
            contract_key=CONTRACT_REF,
            invoice_key=INVOICE_REF,
            bank_account_key=BANK_ACCOUNT_REF,
            accounts={"62.01": "s", "90.01.1": "r", "90.02.1": "e", "90.03": "v", "41": "g"},
            lines=[
                {"nomenclature_key": NOMENCLATURE_REF, "content": "x", "quantity": 1, "price": 1}
            ],
            kind="Прочее",
            vat_rate="НДС20",
            includes_vat=True,
        )


async def test_create_realization_posts_and_reads_back() -> None:
    """POST реализации → перечитаны шапка и строки."""
    transport = make_transport(
        {
            ("POST", "Document_РеализацияТоваровУслуг"): entity_ref(
                REALIZATION_REF, "0000-0000007"
            ),
            ("GET", "Document_РеализацияТоваровУслуг(guid'"): realization_row(),
            ("GET", "Document_РеализацияТоваровУслуг_Услуги"): [realization_service_line_row()],
            ("GET", "Document_РеализацияТоваровУслуг_Товары"): [],
        }
    )
    async with make_client(transport) as client:
        payload = realizations.build_realization_payload(
            organization_key=ORG_REF,
            counterparty_key=CONTRACTOR_REF,
            contract_key=CONTRACT_REF,
            invoice_key=INVOICE_REF,
            bank_account_key=BANK_ACCOUNT_REF,
            accounts={"62.01": "s", "90.01.1": "r", "90.02.1": "e", "90.03": "v", "41": "g"},
            lines=[
                {
                    "nomenclature_key": NOMENCLATURE_REF,
                    "content": "Консультация",
                    "quantity": 8,
                    "price": 12500,
                }
            ],
            kind="Услуги",
            vat_rate="НДС20",
            includes_vat=True,
        )
        doc = await realizations.create_realization(client, payload)
    assert doc.ref_key == REALIZATION_REF
    assert doc.number == "0000-0000001"
    assert len(doc.lines) == 1


async def test_post_document_is_patch() -> None:
    """Проведение — PATCH `{ "Posted": true }`."""
    transport = make_transport({("PATCH", "Document_РеализацияТоваровУслуг(guid'"): None})
    async with make_client(transport) as client:
        assert await realizations.post_document(
            client, "Document_РеализацияТоваровУслуг", REALIZATION_REF
        )
    patches = [r for r in transport.seen_requests if r.method == "PATCH"]  # type: ignore[attr-defined]
    assert len(patches) == 1
    assert patches[0].read().replace(b" ", b"") == b'{"Posted":true}'


# ------------------------------------------------------------------
# Счёт-фактура выданный (УПД)
# ------------------------------------------------------------------


async def test_create_facture_minimal_payload() -> None:
    """СФ записывается минимальным payload — 1С сама наследует реквизиты."""
    transport = make_transport(
        {
            ("POST", "Document_СчетФактураВыданный"): entity_ref(VAT_INVOICE_REF, "0000-0000001"),
            ("GET", "Document_СчетФактураВыданный(guid'"): facture_row(),
        }
    )
    async with make_client(transport) as client:
        doc = await factures.create_facture(client, REALIZATION_REF)
    posts = [r for r in transport.seen_requests if r.method == "POST"]  # type: ignore[attr-defined]
    body = posts[0].read()
    assert "ВидСчетаФактуры".encode() in body
    assert "ДокументОснование".encode() in body
    assert "ДокументыОснования".encode() in body
    assert doc.ref_key == VAT_INVOICE_REF
    assert doc.amount == 100000
    assert doc.counterparty_key == CONTRACTOR_REF


def test_verify_facture_inheritance_ok() -> None:
    """Наследование совпадает — расхождений нет."""
    facture = DocumentInfo(
        entity_set="Document_СчетФактураВыданный",
        ref_key=VAT_INVOICE_REF,
        counterparty_key=CONTRACTOR_REF,
        amount=100000,
    )
    realization = DocumentInfo(
        entity_set="Document_РеализацияТоваровУслуг",
        ref_key=REALIZATION_REF,
        counterparty_key=CONTRACTOR_REF,
        amount=100000,
    )
    assert factures.verify_facture_inheritance(facture, realization) == []


def test_verify_facture_inheritance_mismatch() -> None:
    """Расхождение — список проблем."""
    facture = DocumentInfo(
        entity_set="Document_СчетФактураВыданный",
        ref_key=VAT_INVOICE_REF,
        counterparty_key="other",
        amount=1,
    )
    realization = DocumentInfo(
        entity_set="Document_РеализацияТоваровУслуг",
        ref_key=REALIZATION_REF,
        counterparty_key=CONTRACTOR_REF,
        amount=100000,
    )
    problems = factures.verify_facture_inheritance(facture, realization)
    assert len(problems) == 2


# ------------------------------------------------------------------
# Черновики печатных форм
# ------------------------------------------------------------------


def test_render_invoice_draft() -> None:
    """Черновик счёта: пометка, реквизиты, строки, итоги."""
    doc = DocumentInfo(
        entity_set="Document_СчетНаОплатуПокупателю",
        ref_key=INVOICE_REF,
        number="0000-0000001",
        date="2026-11-10T00:00:00",
        amount=100000,
        lines=[
            DocumentLine(
                line_number=1,
                content="Консультация",
                quantity=8,
                price=12500,
                amount=100000,
                vat_rate="НДС20",
                vat_amount=16666.67,
            )
        ],
    )
    text = print_forms.render_invoice_draft(
        doc,
        org_name="Агентов Т. Т. ИП",
        org_inn="1209328142",
        counterparty_name="ООО Ромашка",
        counterparty_inn="7701234567",
    )
    assert "ЧЕРНОВИК" in text
    assert "0000-0000001" in text
    assert "Агентов Т. Т. ИП" in text
    assert "1209328142" in text
    assert "ООО Ромашка" in text
    assert "Консультация" in text
    assert "16 666.67" in text
    assert "100 000.00" in text


def test_render_document_draft_html() -> None:
    """HTML-черновик с пометкой."""
    text = print_forms.render_invoice_draft(
        DocumentInfo(
            entity_set="Document_СчетНаОплатуПокупателю",
            ref_key=INVOICE_REF,
            number="1",
            date="2026-11-10T00:00:00",
            amount=100,
            counterparty_name="ООО Ромашка",
        ),
        org_name="Агентов Т. Т. ИП",
        counterparty_name="ООО Ромашка",
    )
    html = print_forms.render_document_draft_html(text)
    assert "ЧЕРНОВИК" in html
    assert "<pre>" in html
