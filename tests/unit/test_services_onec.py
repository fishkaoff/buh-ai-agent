"""Юнит-тесты сервисов: контрагенты, договоры, номенклатура, справочники."""

import pytest
from tests.unit.onec_helpers import (
    CONTRACT_REF,
    CONTRACTOR_REF,
    NOMENCLATURE_REF,
    ORG_REF,
    RUB_REF,
    UNIT_REF,
    contract_row,
    counterparty_row,
    entity_ref,
    make_client,
    make_transport,
    nomenclature_row,
    odata_error,
    organization_row,
)

from buh_ai_agent.integrations.onec.errors import OnecApiError
from buh_ai_agent.integrations.onec.models import Contract
from buh_ai_agent.services import contracts, counterparties, nomenclature, reference

# ------------------------------------------------------------------
# Справочники
# ------------------------------------------------------------------


async def test_get_main_organization() -> None:
    """Организация по умолчанию находится."""
    transport = make_transport({("GET", "Catalog_Организации"): [organization_row()]})
    async with make_client(transport) as client:
        org = await reference.get_main_organization(client)
    assert org.ref_key == ORG_REF
    assert org.inn == "1209328142"


async def test_get_main_organization_filters_by_inn() -> None:
    """Фильтр по ИНН выбирает нужную организацию."""
    transport = make_transport(
        {("GET", "Catalog_Организации"): [organization_row(), organization_row(ИНН="9999999999")]}
    )
    async with make_client(transport) as client:
        org = await reference.get_main_organization(client, inn="1209328142")
    assert org.inn == "1209328142"


async def test_get_main_organization_ambiguous() -> None:
    """Несколько организаций без ИНН — неоднозначность."""
    transport = make_transport(
        {("GET", "Catalog_Организации"): [organization_row(), organization_row(ИНН="9999999999")]}
    )
    async with make_client(transport) as client:
        with pytest.raises(LookupError, match="несколько организаций"):
            await reference.get_main_organization(client)


async def test_get_main_organization_not_found() -> None:
    """Нет организаций — LookupError."""
    transport = make_transport({("GET", "Catalog_Организации"): []})
    async with make_client(transport) as client:
        with pytest.raises(LookupError, match="не найдена"):
            await reference.get_main_organization(client)


async def test_get_currency_by_code() -> None:
    """Валюта по коду 643."""
    transport = make_transport(
        {("GET", "Catalog_Валюты"): [{"Ref_Key": RUB_REF, "Code": "643", "Description": "руб."}]}
    )
    async with make_client(transport) as client:
        currency = await reference.get_currency(client, "643")
    assert currency.ref_key == RUB_REF
    assert currency.code == "643"


async def test_get_currency_not_found() -> None:
    """Валюта не найдена — LookupError."""
    transport = make_transport({("GET", "Catalog_Валюты"): []})
    async with make_client(transport) as client:
        with pytest.raises(LookupError, match="не найдена"):
            await reference.get_currency(client, "999")


async def test_get_unit_exact() -> None:
    """Единица «шт» находится точным совпадением."""
    transport = make_transport(
        {("GET", "КлассификаторЕдиницИзмерения"): [{"Ref_Key": UNIT_REF, "Description": "шт"}]}
    )
    async with make_client(transport) as client:
        unit = await reference.get_unit(client, "шт")
    assert unit is not None
    assert unit.ref_key == UNIT_REF


async def test_get_unit_missing() -> None:
    """Единицы нет — None (не создаём через OData)."""
    transport = make_transport({("GET", "КлассификаторЕдиницИзмерения"): []})
    async with make_client(transport) as client:
        assert await reference.get_unit(client, "кг") is None


async def test_get_org_bank_account() -> None:
    """Банковский счёт по владельцу (полиморфное поле Owner)."""
    transport = make_transport(
        {
            ("GET", "Catalog_БанковскиеСчета"): [
                {"Ref_Key": "a1", "Description": "Счёт 1", "Owner": ORG_REF},
                {
                    "Ref_Key": "a2",
                    "Description": "Счёт 2",
                    "Owner": "99999999-9999-9999-9999-999999999999",
                },
            ]
        }
    )
    async with make_client(transport) as client:
        account = await reference.get_org_bank_account(client, ORG_REF)
    assert account is not None
    assert account.ref_key == "a1"
    assert account.owner_key == ORG_REF


# ------------------------------------------------------------------
# Контрагенты
# ------------------------------------------------------------------


async def test_find_counterparty_by_inn() -> None:
    """Поиск по ИНН."""
    transport = make_transport({("GET", "Catalog_Контрагенты"): [counterparty_row()]})
    async with make_client(transport) as client:
        found = await counterparties.find_by_inn(client, "7701234567")
    assert found is not None
    assert found.inn == "7701234567"


async def test_find_counterparty_by_inn_missing() -> None:
    """По ИНН не найден — None."""
    transport = make_transport({("GET", "Catalog_Контрагенты"): []})
    async with make_client(transport) as client:
        assert await counterparties.find_by_inn(client, "7701234567") is None


async def test_find_counterparty_by_name() -> None:
    """Поиск по подстроке наименования, локальный фильтр."""
    transport = make_transport(
        {
            ("GET", "Catalog_Контрагенты"): [
                counterparty_row(),
                counterparty_row(Description="ООО Лукоморье"),
            ]
        }
    )
    async with make_client(transport) as client:
        found = await counterparties.find_by_name(client, "ромашка")
    assert len(found) == 1
    assert found[0].description == "ООО Ромашка"


async def test_find_by_name_tolerates_spaces() -> None:
    """«Логистик Плюс» находит «ЛогистикПлюс» — пробелы не важны."""
    transport = make_transport(
        {
            ("GET", "Catalog_Контрагенты"): [
                counterparty_row(Description="ЛогистикПлюс"),
                counterparty_row(Description="ООО Лукоморье"),
            ]
        }
    )
    async with make_client(transport) as client:
        found = await counterparties.find_by_name(client, "Логистик Плюс")
    assert len(found) == 1
    assert found[0].description == "ЛогистикПлюс"


async def test_find_by_name_ignores_quotes() -> None:
    """Кавычки и пунктуация в запросе не мешают поиску."""
    transport = make_transport({("GET", "Catalog_Контрагенты"): [counterparty_row()]})
    async with make_client(transport) as client:
        found = await counterparties.find_by_name(client, "ООО «Ромашка»!")
    assert len(found) == 1
    assert found[0].description == "ООО Ромашка"


async def test_find_by_name_extra_words_do_not_match() -> None:
    """Слово, которого нет в наименовании, отсекает кандидата (строгий AND)."""
    transport = make_transport({("GET", "Catalog_Контрагенты"): [counterparty_row()]})
    async with make_client(transport) as client:
        found = await counterparties.find_by_name(client, "Ромашка Лукоморье")
    assert found == []


async def test_find_by_name_retries_without_legal_form() -> None:
    """Если в базе нет «ООО», второй проход ищет по значимым словам."""
    transport = make_transport(
        {("GET", "Catalog_Контрагенты"): [counterparty_row(Description="ЛогистикПлюс")]}
    )
    async with make_client(transport) as client:
        found = await counterparties.find_by_name(client, "ООО «Логистик Плюс»")
    assert len(found) == 1
    assert found[0].description == "ЛогистикПлюс"


async def test_find_by_name_shortest_match_first() -> None:
    """Более короткие (точные) совпадения — первыми в списке."""
    transport = make_transport(
        {
            ("GET", "Catalog_Контрагенты"): [
                counterparty_row(Description="ЛогистикПлюс Восток"),
                counterparty_row(Description="ЛогистикПлюс"),
            ]
        }
    )
    async with make_client(transport) as client:
        found = await counterparties.find_by_name(client, "Логистик Плюс")
    assert [c.description for c in found] == ["ЛогистикПлюс", "ЛогистикПлюс Восток"]


async def test_find_counterparty_requires_query() -> None:
    """Без ИНН и наименования — ValueError."""
    transport = make_transport({})
    async with make_client(transport) as client:
        with pytest.raises(ValueError, match="Нужно задать"):
            await counterparties.find_counterparty(client)


async def test_find_counterparty_inn_wins() -> None:
    """ИНН имеет приоритет над наименованием."""
    transport = make_transport({("GET", "Catalog_Контрагенты"): [counterparty_row()]})
    async with make_client(transport) as client:
        found = await counterparties.find_counterparty(client, name="Лукоморье", inn="7701234567")
    assert len(found) == 1
    assert found[0].inn == "7701234567"


async def test_create_counterparty_sends_minimal_payload() -> None:
    """Создание отправляет проверенный минимум реквизитов."""
    transport = make_transport(
        {
            ("GET", "Catalog_Контрагенты"): [],
            ("POST", "Catalog_Контрагенты"): entity_ref(
                "bb1b1b1b-1111-1111-1111-111111111111", "00-000005"
            ),
            (
                "GET",
                "Catalog_Контрагенты(guid'bb1b1b1b-1111-1111-1111-111111111111')",
            ): counterparty_row(Ref_Key="bb1b1b1b-1111-1111-1111-111111111111"),
        }
    )
    async with make_client(transport) as client:
        created = await counterparties.create_counterparty(
            client, name="ООО Ромашка", inn="7701234567", kpp="770101001"
        )
    assert created.inn == "7701234567"
    post = [r for r in transport.seen_requests if r.method == "POST"]  # type: ignore[attr-defined]
    assert len(post) == 1
    body = post[0].read()
    assert body.count(b"Description") == 1
    assert "ООО Ромашка".encode() in body


async def test_create_counterparty_duplicate_by_inn() -> None:
    """Создание с существующим ИНН — дубликат."""
    transport = make_transport({("GET", "Catalog_Контрагенты"): [counterparty_row()]})
    async with make_client(transport) as client:
        with pytest.raises(LookupError, match="уже существует"):
            await counterparties.create_counterparty(client, name="ООО Ромашка", inn="7701234567")


async def test_create_counterparty_duplicate_by_name() -> None:
    """Создание с существующим наименованием — дубликат."""
    transport = make_transport({("GET", "Catalog_Контрагенты"): [counterparty_row()]})
    async with make_client(transport) as client:
        with pytest.raises(LookupError, match="уже существует"):
            await counterparties.create_counterparty(client, name="ООО Ромашка", inn="0000000000")


async def test_create_counterparty_requires_name() -> None:
    """Создание без наименования — ValueError."""
    transport = make_transport({})
    async with make_client(transport) as client:
        with pytest.raises(ValueError, match="Наименование"):
            await counterparties.create_counterparty(client, name="")


async def test_create_counterparty_1c_error_propagates() -> None:
    """Ошибка записи от 1С пробрасывается."""
    transport = make_transport(
        {
            ("GET", "Catalog_Контрагенты"): [],
            ("POST", "Catalog_Контрагенты"): odata_error(
                400, "0", "Ошибка 1С при записи: элемент не создан"
            ),
        }
    )
    async with make_client(transport) as client:
        with pytest.raises(OnecApiError, match="Ошибка 1С"):
            await counterparties.create_counterparty(client, name="ООО Ромашка", inn="7701234567")


async def test_update_counterparty_reads_back() -> None:
    """PATCH — только явно указанные поля, затем перечитать."""
    transport = make_transport(
        {
            ("PATCH", "Catalog_Контрагенты(guid'"): None,
            ("GET", "Catalog_Контрагенты(guid'"): counterparty_row(ИНН="7701234567"),
        }
    )
    async with make_client(transport) as client:
        updated = await counterparties.update_counterparty(
            client, CONTRACTOR_REF, {"ИНН": "7701234567"}
        )
    assert updated.inn == "7701234567"


# ------------------------------------------------------------------
# Договоры
# ------------------------------------------------------------------


async def test_find_contracts_by_owner() -> None:
    """Фильтр по Owner_Key и виду."""
    transport = make_transport(
        {
            ("GET", "Catalog_ДоговорыКонтрагентов"): [
                contract_row(),
                contract_row(ВидДоговора="СПоставщиком"),
                contract_row(DeletionMark=True),
            ]
        }
    )
    async with make_client(transport) as client:
        found = await contracts.find_contracts(client, CONTRACTOR_REF, kind="СПокупателем")
    assert len(found) == 1
    assert found[0].kind == "СПокупателем"


async def test_pick_latest_contract() -> None:
    """Выбирается максимум пары (Дата, Номер) среди открытых."""
    oldest = contract_row(Дата="2026-01-10T00:00:00", Номер="1")
    newest = contract_row(Дата="2026-11-10T00:00:00", Номер="4")
    closed = contract_row(Дата="2026-12-10T00:00:00", Номер="5", ДоговорЗакрыт=True)
    chosen = contracts.pick_latest_contract(
        [Contract.from_row(c) for c in (oldest, newest, closed)], kind="СПокупателем"
    )
    assert chosen is not None
    assert chosen.ref_key == Contract.from_row(newest).ref_key


async def test_pick_latest_contract_none() -> None:
    """Нет подходящих — None."""
    closed = contract_row(ДоговорЗакрыт=True)
    assert contracts.pick_latest_contract([Contract.from_row(closed)], kind="СПокупателем") is None


async def test_pick_latest_contract_kind_filter() -> None:
    """Вид договора фильтруется."""
    purchase = contract_row(ВидДоговора="СПоставщиком")
    assert (
        contracts.pick_latest_contract([Contract.from_row(purchase)], kind="СПокупателем") is None
    )


def test_next_contract_number() -> None:
    """Кандидат = max(числовых Номер) + 1."""
    contracts_rows = [
        contract_row(Номер="1"),
        contract_row(Номер="3"),
        contract_row(Номер="4"),
    ]
    assert contracts.next_contract_number([Contract.from_row(c) for c in contracts_rows]) == "5"


def test_next_contract_number_skips_non_numeric() -> None:
    """Нечисловые номера игнорируются."""
    contracts_rows = [contract_row(Номер="АБВ"), contract_row(Номер="2")]
    assert contracts.next_contract_number([Contract.from_row(c) for c in contracts_rows]) == "3"


def test_next_contract_number_undeterminable() -> None:
    """Все номера нечисловые — None (номер нужно спросить у пользователя)."""
    contracts_rows = [contract_row(Номер="АБВ")]
    assert contracts.next_contract_number([Contract.from_row(c) for c in contracts_rows]) is None


def test_contract_description() -> None:
    """Description по образцу данных: «Номер от ДД.ММ.ГГГГ»."""
    assert contracts.contract_description("4", "2026-11-10") == "4 от 10.11.2026"


async def test_create_contract_sends_minimal_payload() -> None:
    """Создание отправляет проверенный минимум: Owner_Key, вид, организация, валюта."""
    transport = make_transport(
        {
            ("POST", "Catalog_ДоговорыКонтрагентов"): entity_ref(CONTRACT_REF, "00-000005"),
            ("GET", "Catalog_ДоговорыКонтрагентов(guid'"): contract_row(),
        }
    )
    async with make_client(transport) as client:
        created = await contracts.create_contract(
            client,
            counterparty_key=CONTRACTOR_REF,
            organization_key=ORG_REF,
            currency_key=RUB_REF,
            kind="СПокупателем",
            number="4",
            document_date="2026-11-10",
        )
    assert created.ref_key == CONTRACT_REF
    assert created.kind == "СПокупателем"
    post = [r for r in transport.seen_requests if r.method == "POST"]  # type: ignore[attr-defined]
    body = post[0].read()
    assert b"Description" in body
    assert b"Owner_Key" in body
    assert "ВидДоговора".encode() in body
    assert "Номер".encode() in body


async def test_create_contract_requires_kind() -> None:
    """Вид договора обязателен."""
    transport = make_transport({})
    async with make_client(transport) as client:
        with pytest.raises(ValueError, match="ВидДоговора"):
            await contracts.create_contract(
                client,
                counterparty_key=CONTRACTOR_REF,
                organization_key=ORG_REF,
                currency_key=RUB_REF,
                kind="",
                number="1",
            )


async def test_create_contract_requires_counterparty() -> None:
    """Контрагент обязателен."""
    transport = make_transport({})
    async with make_client(transport) as client:
        with pytest.raises(ValueError, match="контрагент"):
            await contracts.create_contract(
                client,
                counterparty_key="",
                organization_key=ORG_REF,
                currency_key=RUB_REF,
                number="1",
            )


# ------------------------------------------------------------------
# Номенклатура
# ------------------------------------------------------------------


async def test_find_nomenclature_local_filter() -> None:
    """Поиск по подстроке наименования."""
    transport = make_transport(
        {
            ("GET", "Catalog_Номенклатура"): [
                nomenclature_row(),
                nomenclature_row(Description="Труба ПНД 40"),
                nomenclature_row(IsFolder=True),
                nomenclature_row(DeletionMark=True),
            ]
        }
    )
    async with make_client(transport) as client:
        found = await nomenclature.find_nomenclature(client, "консультация")
    assert len(found) == 1
    assert found[0].description == "Консультация"


async def test_find_exact_nomenclature() -> None:
    """Точное совпадение наименования без регистра."""
    transport = make_transport({("GET", "Catalog_Номенклатура"): [nomenclature_row()]})
    async with make_client(transport) as client:
        found = await nomenclature.find_exact_nomenclature(client, "консультация")
    assert found is not None
    assert found.ref_key == NOMENCLATURE_REF


async def test_find_exact_nomenclature_missing() -> None:
    """Нет точного совпадения — None."""
    transport = make_transport({("GET", "Catalog_Номенклатура"): [nomenclature_row()]})
    async with make_client(transport) as client:
        assert await nomenclature.find_exact_nomenclature(client, "Услуга") is None


async def test_create_nomenclature_sends_minimal_payload() -> None:
    """Создание отправляет минимум: Description + Услуга."""
    transport = make_transport(
        {
            ("GET", "Catalog_Номенклатура"): [],
            ("POST", "Catalog_Номенклатура"): entity_ref(NOMENCLATURE_REF, "00-000005"),
            ("GET", "Catalog_Номенклатура(guid'"): nomenclature_row(),
        }
    )
    async with make_client(transport) as client:
        created = await nomenclature.create_nomenclature(
            client, name="Консультация", is_service=True
        )
    assert created.ref_key == NOMENCLATURE_REF
    assert created.is_service is True
    post = [r for r in transport.seen_requests if r.method == "POST"]  # type: ignore[attr-defined]
    body = post[0].read()
    assert "Услуга".encode() in body
    assert "Консультация".encode() in body


async def test_create_nomenclature_duplicate() -> None:
    """Существующая позиция главнее новой."""
    transport = make_transport({("GET", "Catalog_Номенклатура"): [nomenclature_row()]})
    async with make_client(transport) as client:
        with pytest.raises(LookupError, match="уже"):
            await nomenclature.create_nomenclature(client, name="Консультация", is_service=True)


async def test_find_all_contracts_spans_counterparties() -> None:
    """find_all_contracts читает договоры всей базы (без фильтра по владельцу)."""
    transport = make_transport(
        {
            ("GET", "Catalog_ДоговорыКонтрагентов"): [
                contract_row(Номер="7", Owner_Key="owner-a"),
                contract_row(Номер="9", Owner_Key="owner-b", ВидДоговора="СПоставщиком"),
                contract_row(DeletionMark=True),
            ]
        }
    )
    async with make_client(transport) as client:
        found = await contracts.find_all_contracts(client)
    assert len(found) == 2
    assert {c.owner_key for c in found} == {"owner-a", "owner-b"}
    assert contracts.next_contract_number(found) == "10"


async def test_create_contract_requires_number() -> None:
    """Договор без номера («б/н») не создаётся."""
    transport = make_transport({})
    async with make_client(transport) as client:
        with pytest.raises(ValueError, match="без номера"):
            await contracts.create_contract(
                client,
                counterparty_key=CONTRACTOR_REF,
                organization_key=ORG_REF,
                currency_key=RUB_REF,
                number="  ",
            )
    posts = [r for r in transport.seen_requests if r.method == "POST"]  # type: ignore[attr-defined]
    assert not posts
