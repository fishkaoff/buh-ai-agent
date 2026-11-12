"""Черновики печатных форм (счёт, УПД) — Markdown/HTML предпросмотр.

Правила — Skill onec-print-forms:

- стандартный OData-интерфейс 1С печатные формы не отдаёт: в `$metadata`
  нет сущностей печатных форм; PDF недоступен;
- «похожий на счёт» HTML/PDF допустим только как черновик-предпросмотр
  с явной пометкой «черновик, не заменяет печатную форму 1С»;
- официальную печатную форму печатает человек из 1С;
- проверка корректности: сверяйте номер, дату, реквизиты, каждую строку,
  итоги, ставку и сумму НДС с документом 1С.
"""

from __future__ import annotations

import html

from buh_ai_agent.integrations.onec.models import DocumentInfo

DRAFT_MARK = "ЧЕРНОВИК — не заменяет печатную форму 1С"

_DRAFT_MARK_HTML = "ЧЕРНОВИК — не заменяет печатную форму 1С"


def _amount(value: float) -> str:
    """Форматирует сумму с двумя знаками."""
    return f"{value:,.2f}".replace(",", " ")


def _doc_date(date_iso: str) -> str:
    """Форматирует дату `YYYY-MM-DDT00:00:00` → `ДД.ММ.ГГГГ`."""
    if not date_iso:
        return ""
    year, month, day = date_iso[:10].split("-")
    return f"{day}.{month}.{year}"


def render_invoice_draft(
    document: DocumentInfo,
    *,
    org_name: str,
    org_inn: str = "",
    org_kpp: str = "",
    counterparty_name: str,
    counterparty_inn: str = "",
    counterparty_kpp: str = "",
) -> str:
    """Строит черновик счёта в Markdown.

    Args:
        document: Документ (счёт или реализация) с его строками.
        org_name: Наименование организации.
        org_inn: ИНН организации.
        org_kpp: КПП организации.
        counterparty_name: Наименование контрагента.
        counterparty_inn: ИНН контрагента.
        counterparty_kpp: КПП контрагента.

    Returns:
        Markdown-черновик с пометкой «черновик».
    """
    lines: list[str] = [
        f"**{DRAFT_MARK}**",
        "",
        f"# Счёт на оплату №{document.number or 'б/н'} от {_doc_date(document.date)}",
        "",
        f"**Поставщик:** {org_name}",
    ]
    if org_inn or org_kpp:
        lines.append(f"ИНН {org_inn} / КПП {org_kpp}")
    lines.append("")
    lines.append(f"**Покупатель:** {counterparty_name}")
    if counterparty_inn or counterparty_kpp:
        lines.append(f"ИНН {counterparty_inn} / КПП {counterparty_kpp}")
    lines.append("")
    if document.lines:
        lines.append("| № | Наименование | Кол-во | Цена | Сумма | Ставка НДС | Сумма НДС |")
        lines.append("|---|---|---|---|---|---|---|")
        for index, line in enumerate(document.lines, start=1):
            lines.append(
                f"| {index} | {line.content or 'позиция'} | {line.quantity:g} | "
                f"{_amount(line.price)} | {_amount(line.amount)} | {line.vat_rate} | "
                f"{_amount(line.vat_amount)} |"
            )
        lines.append("")
    lines.append(f"**Итого:** {_amount(document.amount)}")
    return "\n".join(lines)


def render_upd_draft(
    document: DocumentInfo,
    *,
    org_name: str,
    org_inn: str = "",
    org_kpp: str = "",
    counterparty_name: str,
    counterparty_inn: str = "",
    counterparty_kpp: str = "",
) -> str:
    """Строит черновик УПД в Markdown.

    УПД — печатная форма реализации; черновик собирается из данных
    документа реализации.

    Args:
        document: Документ реализации с его строками.
        org_name: Наименование организации.
        org_inn: ИНН организации.
        org_kpp: КПП организации.
        counterparty_name: Наименование контрагента.
        counterparty_inn: ИНН контрагента.
        counterparty_kpp: КПП контрагента.

    Returns:
        Markdown-черновик с пометкой «черновик».
    """
    kind = "УПД" if document.kind == "Товары" else "УПД (акт)"
    lines: list[str] = [
        f"**{DRAFT_MARK}**",
        "",
        f"# УПД №{document.number or 'б/н'} от {_doc_date(document.date)}",
        "",
        f"**Продавец:** {org_name}",
    ]
    if org_inn or org_kpp:
        lines.append(f"ИНН {org_inn} / КПП {org_kpp}")
    lines.append("")
    lines.append(f"**Покупатель:** {counterparty_name}")
    if counterparty_inn or counterparty_kpp:
        lines.append(f"ИНН {counterparty_inn} / КПП {counterparty_kpp}")
    lines.append("")
    lines.append(f"**Вид операции:** {kind}")
    lines.append("")
    if document.lines:
        lines.append("| № | Наименование | Кол-во | Цена | Сумма | Ставка НДС | Сумма НДС |")
        lines.append("|---|---|---|---|---|---|---|")
        for index, line in enumerate(document.lines, start=1):
            lines.append(
                f"| {index} | {line.content or 'позиция'} | {line.quantity:g} | "
                f"{_amount(line.price)} | {_amount(line.amount)} | {line.vat_rate} | "
                f"{_amount(line.vat_amount)} |"
            )
        lines.append("")
    lines.append(f"**Итого:** {_amount(document.amount)}")
    return "\n".join(lines)


def render_document_draft_html(markdown: str) -> str:
    """Оборачивает Markdown-черновик в HTML-предпросмотр.

    Args:
        markdown: Markdown-черновик.

    Returns:
        HTML-страница с черновиком.
    """
    escaped = html.escape(markdown)
    return (
        "<html><head><meta charset='utf-8'>"
        f"<title>{_DRAFT_MARK_HTML}</title>"
        "</head><body><pre>"
        f"{escaped}"
        "</pre></body></html>"
    )
