"""Юнит-тесты конфигурации подключения к 1С."""

from pathlib import Path

import pytest

from buh_ai_agent.integrations.onec.config import load_onec_config
from buh_ai_agent.integrations.onec.errors import OnecError

CONFIG_JSON = """{
  "defaultDatabase": "ai_agent",
  "databases": {
    "ai_agent": {
      "label": "test base",
      "odataBaseUrl": "http://192.168.3.2/InfoBase2/odata/standard.odata/",
      "auth": {"type": "basic", "username": "odata_ai", "password": "secret"}
    },
    "other": {
      "label": "other",
      "odataBaseUrl": "http://other/odata/standard.odata/",
      "auth": {"username": "u2", "password": "p2"}
    }
  },
  "defaults": {
    "organization": {"name": "Агентов Т. Т. ИП", "inn": "1209328142"},
    "currencyCode": "643",
    "vatRate": "НДС5",
    "sumIncludesVat": true,
    "unitOfMeasure": "шт"
  },
  "safety": {"allowWrite": true, "allowPost": false}
}"""


@pytest.fixture()
def config_file(tmp_path: Path) -> Path:
    """Создаёт файл конфигурации 1С."""
    path = tmp_path / "onec-config.json"
    path.write_text(CONFIG_JSON, encoding="utf-8")
    return path


def test_load_default_database(config_file: Path) -> None:
    """Конфигурация по умолчанию берёт defaultDatabase и значения файла."""
    config = load_onec_config(config_file)
    assert config.database == "ai_agent"
    assert config.base_url == "http://192.168.3.2/InfoBase2/odata/standard.odata/"
    assert config.username == "odata_ai"
    assert config.password.get_secret_value() == "secret"
    assert config.defaults.organization.inn == "1209328142"
    assert config.defaults.vat_rate == "НДС5"
    assert config.defaults.currency_code == "643"
    assert config.defaults.sum_includes_vat is True
    assert config.safety.allow_write is True
    assert config.safety.allow_post is False


def test_env_overrides_take_priority(config_file: Path) -> None:
    """Переменные окружения переопределяют значения файла."""
    config = load_onec_config(
        config_file,
        database="other",
        base_url_override="http://env-host/odata/",
        username_override="env_user",
        password_override="env_password",
    )
    assert config.database == "other"
    assert config.base_url == "http://env-host/odata/"
    assert config.username == "env_user"
    assert config.password.get_secret_value() == "env_password"


def test_missing_config_file_raises(tmp_path: Path) -> None:
    """Отсутствие файла конфигурации даёт понятную ошибку."""
    with pytest.raises(OnecError, match="не найден"):
        load_onec_config(tmp_path / "missing.json")


def test_unknown_database_raises(config_file: Path) -> None:
    """Неизвестное имя базы даёт ошибку со списком доступных."""
    with pytest.raises(OnecError, match="не описана.*other"):
        load_onec_config(config_file, database="nope")


def test_invalid_json_raises(tmp_path: Path) -> None:
    """Невалидный JSON конфигурации даёт понятную ошибку."""
    path = tmp_path / "broken.json"
    path.write_text("{oops", encoding="utf-8")
    with pytest.raises(OnecError, match="не разбирается"):
        load_onec_config(path)
