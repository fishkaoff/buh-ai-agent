"""Конфигурация подключения к 1С.

Приложение собирает конфигурацию только из переменных окружения
(pydantic-settings): либо одну базу (ONEC_BASE_URL, ONEC_USERNAME,
ONEC_PASSWORD, ONEC_DATABASE), либо несколько — JSON-массивом в
ONEC_DATABASES. Дефолты документов и правила безопасности общие
(ONEC_*), у базы можно переопределить организацию. Файловые конфиги
(config/onec-config.json) относятся к агентскому стеку (скиллы) и
приложением не читаются.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field, SecretStr, ValidationError

from buh_ai_agent.core.settings import Settings
from buh_ai_agent.integrations.onec.errors import OnecError


class OnecOrganizationDefaults(BaseModel):
    """Организация по умолчанию (настройки ONEC_ORGANIZATION_*)."""

    name: str = ""
    inn: str = ""


class OnecDefaults(BaseModel):
    """Значения по умолчанию для документов (настройки ONEC_*)."""

    organization: OnecOrganizationDefaults = Field(default_factory=OnecOrganizationDefaults)
    currency_code: str = "643"
    vat_rate: str = "НДС20"
    sum_includes_vat: bool = True
    unit_of_measure: str = "шт"


class OnecSafety(BaseModel):
    """Правила безопасности записи (настройки ONEC_ALLOW_*)."""

    allow_write: bool = True
    allow_post: bool = False
    allow_unpost: bool = False
    allow_mark_for_deletion: bool = False


class OnecConnectionConfig(BaseModel):
    """Итоговая конфигурация подключения к базе 1С и её доменные настройки."""

    database: str
    base_url: str
    username: str
    password: SecretStr
    defaults: OnecDefaults
    safety: OnecSafety
    label: str = ""
    # HTTP-сервис печати (расширение 1С) этой базы; пусто — не настроен.
    print_service_url: str = ""


class OnecDatabaseEnv(BaseModel):
    """Описание одной базы 1С в переменной ONEC_DATABASES (JSON-массив)."""

    name: str
    label: str = ""
    base_url: str
    username: str
    password: str
    organization_name: str = ""
    organization_inn: str = ""
    print_service_url: str = ""


def _onec_defaults(
    settings: Settings, *, organization_name: str, organization_inn: str
) -> OnecDefaults:
    """Собирает дефолты документов из настроек (организация может быть своей у базы)."""
    return OnecDefaults(
        organization=OnecOrganizationDefaults(
            name=organization_name,
            inn=organization_inn,
        ),
        currency_code=settings.onec_currency_code,
        vat_rate=settings.onec_vat_rate,
        sum_includes_vat=settings.onec_sum_includes_vat,
        unit_of_measure=settings.onec_unit_of_measure,
    )


def _onec_safety(settings: Settings) -> OnecSafety:
    """Собирает правила безопасности записи из настроек."""
    return OnecSafety(
        allow_write=settings.onec_allow_write,
        allow_post=settings.onec_allow_post,
        allow_unpost=settings.onec_allow_unpost,
        allow_mark_for_deletion=settings.onec_allow_mark_for_deletion,
    )


def onec_config_from_settings(settings: Settings) -> OnecConnectionConfig:
    """Собирает конфигурацию подключения к 1С из настроек приложения.

    Args:
        settings: Настройки приложения (переменные окружения ONEC_*).

    Returns:
        Конфигурация подключения к выбранной базе.

    Raises:
        OnecError: Не заданы обязательные переменные подключения.
    """
    base_url = settings.onec_base_url.strip()
    username = settings.onec_username.strip()
    password = settings.onec_password.get_secret_value()
    if not base_url:
        raise OnecError("Не задан ONEC_BASE_URL — URL OData-интерфейса 1С.")
    if not username:
        raise OnecError("Не задан ONEC_USERNAME — логин пользователя 1С.")
    if not password:
        raise OnecError("Не задан ONEC_PASSWORD — пароль пользователя 1С.")

    return OnecConnectionConfig(
        database=settings.onec_database,
        base_url=base_url.rstrip("/") + "/",
        username=username,
        password=SecretStr(password),
        print_service_url=settings.onec_print_service_url.strip().rstrip("/"),
        defaults=_onec_defaults(
            settings,
            organization_name=settings.onec_organization_name,
            organization_inn=settings.onec_organization_inn,
        ),
        safety=_onec_safety(settings),
    )


def onec_configs_from_settings(settings: Settings) -> list[OnecConnectionConfig]:
    """Собирает конфигурации всех баз 1С из настроек приложения.

    Если задан ONEC_DATABASES (JSON-массив баз) — подключений столько,
    сколько элементов массива; иначе используется одиночное подключение
    из ONEC_BASE_URL/ONEC_USERNAME/ONEC_PASSWORD.

    Args:
        settings: Настройки приложения (переменные окружения ONEC_*).

    Returns:
        Список конфигураций подключений (минимум одна).

    Raises:
        OnecError: Некорректный ONEC_DATABASES или не заданы обязательные
            переменные одиночного подключения.
    """
    raw = settings.onec_databases.strip()
    if not raw:
        return [onec_config_from_settings(settings)]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise OnecError(f"ONEC_DATABASES: некорректный JSON ({error}).") from error
    if not isinstance(data, list) or not data:
        raise OnecError("ONEC_DATABASES: ожидается непустой JSON-массив баз.")

    configs: list[OnecConnectionConfig] = []
    seen: set[str] = set()
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise OnecError(f"ONEC_DATABASES: элемент #{index} — не объект (словарь).")
        try:
            base = OnecDatabaseEnv.model_validate(item)
        except ValidationError as error:
            detail = "; ".join(
                f"{'.'.join(str(part) for part in item_error['loc'])}: {item_error['msg']}"
                for item_error in error.errors()
            )
            raise OnecError(f"ONEC_DATABASES: элемент #{index} — {detail}.") from error

        name = base.name.strip()
        if not name:
            raise OnecError(f"ONEC_DATABASES: элемент #{index} — пустое имя (name).")
        if name.casefold() in seen:
            raise OnecError(f"ONEC_DATABASES: дубликат имени базы «{name}».")
        seen.add(name.casefold())

        base_url = base.base_url.strip()
        if not base_url:
            raise OnecError(f"ONEC_DATABASES: база «{name}» — не заполнен base_url.")
        username = base.username.strip()
        if not username:
            raise OnecError(f"ONEC_DATABASES: база «{name}» — не заполнен username.")
        if not base.password.strip():
            raise OnecError(f"ONEC_DATABASES: база «{name}» — не заполнен password.")

        configs.append(
            OnecConnectionConfig(
                database=name,
                label=base.label.strip(),
                base_url=base_url.rstrip("/") + "/",
                username=username,
                password=SecretStr(base.password),
                print_service_url=(
                    base.print_service_url.strip() or settings.onec_print_service_url.strip()
                ).rstrip("/"),
                defaults=_onec_defaults(
                    settings,
                    organization_name=base.organization_name or settings.onec_organization_name,
                    organization_inn=base.organization_inn or settings.onec_organization_inn,
                ),
                safety=_onec_safety(settings),
            )
        )
    return configs
