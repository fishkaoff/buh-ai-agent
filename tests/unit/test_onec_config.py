"""Юнит-тесты конфигурации подключения к 1С (сборка из настроек приложения)."""

import pytest

from buh_ai_agent.core.settings import Settings
from buh_ai_agent.integrations.onec.config import onec_config_from_settings
from buh_ai_agent.integrations.onec.errors import OnecError


def make_settings(**overrides: str) -> Settings:
    """Настройки с заданными переменными окружения 1С (без чтения .env)."""
    env = {
        "ONEC_BASE_URL": "http://192.168.3.2/InfoBase2/odata/standard.odata/",
        "ONEC_USERNAME": "odata_ai",
        "ONEC_PASSWORD": "secret",
        "ONEC_DATABASE": "ai_agent",
        "ONEC_ORGANIZATION_NAME": "Агентов Т. Т. ИП",
        "ONEC_ORGANIZATION_INN": "1209328142",
        "ONEC_VAT_RATE": "НДС5",
        **overrides,
    }
    return Settings(_env_file=None, **env)


def test_config_from_settings() -> None:
    """Конфигурация собирается из переменных окружения ONEC_*."""
    config = onec_config_from_settings(make_settings())
    assert config.database == "ai_agent"
    assert config.base_url == "http://192.168.3.2/InfoBase2/odata/standard.odata/"
    assert config.username == "odata_ai"
    assert config.password.get_secret_value() == "secret"
    assert config.defaults.organization.name == "Агентов Т. Т. ИП"
    assert config.defaults.organization.inn == "1209328142"
    assert config.defaults.vat_rate == "НДС5"
    assert config.defaults.currency_code == "643"
    assert config.defaults.sum_includes_vat is True
    assert config.defaults.unit_of_measure == "шт"
    assert config.safety.allow_write is True
    assert config.safety.allow_post is False
    assert config.safety.allow_unpost is False
    assert config.safety.allow_mark_for_deletion is False


def test_base_url_trailing_slash_normalized() -> None:
    """Базовый URL нормализуется: оканчивается на «/»."""
    config = onec_config_from_settings(make_settings(ONEC_BASE_URL="http://onec.test/base"))
    assert config.base_url == "http://onec.test/base/"


def test_safety_flags_from_env() -> None:
    """Правила безопасности читаются из ONEC_ALLOW_*."""
    config = onec_config_from_settings(
        make_settings(ONEC_ALLOW_POST="true", ONEC_ALLOW_WRITE="false")
    )
    assert config.safety.allow_post is True
    assert config.safety.allow_write is False


def test_defaults_applied_when_env_empty() -> None:
    """Без переменных дефолтов применяются значения по умолчанию."""
    settings = Settings(_env_file=None)
    assert settings.onec_currency_code == "643"
    assert settings.onec_vat_rate == "НДС20"
    assert settings.onec_sum_includes_vat is True
    assert settings.onec_unit_of_measure == "шт"
    assert settings.onec_allow_write is True
    assert settings.onec_allow_post is False


@pytest.mark.parametrize(
    ("removed", "match"),
    [
        ("ONEC_BASE_URL", "ONEC_BASE_URL"),
        ("ONEC_USERNAME", "ONEC_USERNAME"),
        ("ONEC_PASSWORD", "ONEC_PASSWORD"),
    ],
)
def test_missing_connection_setting_raises(removed: str, match: str) -> None:
    """Отсутствие обязательной переменной подключения даёт понятную ошибку."""
    settings = make_settings(**{removed: ""})
    with pytest.raises(OnecError, match=match):
        onec_config_from_settings(settings)
