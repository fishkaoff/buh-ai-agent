"""Юнит-тесты конфигурации подключения к 1С (сборка из настроек приложения)."""

import json

import pytest

from buh_ai_agent.core.settings import Settings
from buh_ai_agent.integrations.onec.config import (
    onec_config_from_settings,
    onec_configs_from_settings,
)
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


# ------------------------------------------------------------------
# Несколько баз (ONEC_DATABASES)
# ------------------------------------------------------------------


def make_databases_json(*bases: dict) -> str:
    """JSON-строка для ONEC_DATABASES из описаний баз."""
    return json.dumps(bases, ensure_ascii=False)


BASE_MAIN = {
    "name": "osnovnaya",
    "label": "Основная база (ИП Агентов)",
    "base_url": "http://192.168.3.2/InfoBase2/odata/standard.odata/",
    "username": "odata_ai",
    "password": "secret1",
}
BASE_FILIAL = {
    "name": "filial",
    "label": "Филиал (ООО Ромашка)",
    "base_url": "http://192.168.3.2/InfoBase3/odata/standard.odata/",
    "username": "odata_filial",
    "password": "secret2",
    "organization_name": "ООО Ромашка",
    "organization_inn": "7701234567",
}


def test_configs_from_databases_json() -> None:
    """ONEC_DATABASES разбирается в конфигурации всех баз."""
    configs = onec_configs_from_settings(
        make_settings(ONEC_DATABASES=make_databases_json(BASE_MAIN, BASE_FILIAL))
    )
    assert [config.database for config in configs] == ["osnovnaya", "filial"]
    main, filial = configs
    assert main.base_url == "http://192.168.3.2/InfoBase2/odata/standard.odata/"
    assert main.username == "odata_ai"
    assert main.password.get_secret_value() == "secret1"
    assert main.label == "Основная база (ИП Агентов)"
    assert filial.password.get_secret_value() == "secret2"
    assert filial.base_url.endswith("/")


def test_configs_per_base_organization_with_global_fallback() -> None:
    """Организация базы переопределяется; пустые поля берутся из общих ONEC_ORGANIZATION_*."""
    configs = onec_configs_from_settings(
        make_settings(ONEC_DATABASES=make_databases_json(BASE_MAIN, BASE_FILIAL))
    )
    main, filial = configs
    # У основной базы организация не указана — общие дефолты.
    assert main.defaults.organization.name == "Агентов Т. Т. ИП"
    assert main.defaults.organization.inn == "1209328142"
    # У филиала — свои.
    assert filial.defaults.organization.name == "ООО Ромашка"
    assert filial.defaults.organization.inn == "7701234567"
    # Общие дефолты (НДС, валюта, безопасность) применяются к обеим базам.
    assert main.defaults.vat_rate == "НДС5"
    assert filial.defaults.vat_rate == "НДС5"
    assert filial.safety.allow_post is False


def test_configs_empty_databases_falls_back_to_single_env() -> None:
    """Без ONEC_DATABASES работает одиночное подключение из ONEC_*."""
    configs = onec_configs_from_settings(make_settings(ONEC_DATABASES="   "))
    assert len(configs) == 1
    assert configs[0].database == "ai_agent"


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        ("{not json", "некорректный JSON"),
        ('"osnovnaya"', "JSON-массив"),
        ("[]", "JSON-массив"),
        ('[{"name":"x"}]', "base_url"),
        ('[{"name":"","base_url":"http://x/","username":"u","password":"p"}]', "пустое имя"),
        (
            make_databases_json(
                {
                    "name": "osnovnaya",
                    "base_url": "http://x/",
                    "username": "u",
                    "password": "p",
                },
                {
                    "name": "Osnovnaya",
                    "base_url": "http://y/",
                    "username": "u",
                    "password": "p",
                },
            ),
            "дубликат имени",
        ),
        ('[{"name":"x","base_url":"http://x/","username":"u"}]', "password"),
    ],
)
def test_configs_invalid_databases_raises(raw: str, match: str) -> None:
    """Некорректный ONEC_DATABASES даёт понятную ошибку (без записи в 1С)."""
    with pytest.raises(OnecError, match=match):
        onec_configs_from_settings(make_settings(ONEC_DATABASES=raw))


def test_configs_missing_single_connection_setting_raises() -> None:
    """Без ONEC_DATABASES отсутствие обязательных переменных даёт ошибку."""
    with pytest.raises(OnecError, match="ONEC_BASE_URL"):
        onec_configs_from_settings(make_settings(ONEC_BASE_URL=""))


def test_print_service_url_per_base_with_global_fallback() -> None:
    """print_service_url базы главнее; без него берётся общий ONEC_PRINT_SERVICE_URL."""
    configs = onec_configs_from_settings(
        make_settings(
            ONEC_PRINT_SERVICE_URL="http://host/hs/print",
            ONEC_DATABASES=make_databases_json(
                {**BASE_MAIN, "print_service_url": "http://main/hs/print"}, BASE_FILIAL
            ),
        )
    )
    main, filial = configs
    assert main.print_service_url == "http://main/hs/print"
    assert filial.print_service_url == "http://host/hs/print"


def test_single_config_print_service_url_normalized() -> None:
    """Одиночная база: URL сервиса нормализуется (без завершающего слеша)."""
    config = onec_config_from_settings(
        make_settings(ONEC_PRINT_SERVICE_URL="http://host/hs/print/")
    )
    assert config.print_service_url == "http://host/hs/print"
    assert onec_config_from_settings(make_settings()).print_service_url == ""
