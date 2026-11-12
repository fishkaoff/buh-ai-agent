"""Конфигурация подключения к 1С.

Приложение собирает конфигурацию только из переменных окружения
(pydantic-settings): ONEC_BASE_URL, ONEC_USERNAME, ONEC_PASSWORD, а также
дефолтов документов и правил безопасности. Файловые конфиги
(config/onec-config.json) относятся к агентскому стеку (скиллы) и
приложением не читаются.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, SecretStr

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
        defaults=OnecDefaults(
            organization=OnecOrganizationDefaults(
                name=settings.onec_organization_name,
                inn=settings.onec_organization_inn,
            ),
            currency_code=settings.onec_currency_code,
            vat_rate=settings.onec_vat_rate,
            sum_includes_vat=settings.onec_sum_includes_vat,
            unit_of_measure=settings.onec_unit_of_measure,
        ),
        safety=OnecSafety(
            allow_write=settings.onec_allow_write,
            allow_post=settings.onec_allow_post,
            allow_unpost=settings.onec_allow_unpost,
            allow_mark_for_deletion=settings.onec_allow_mark_for_deletion,
        ),
    )
