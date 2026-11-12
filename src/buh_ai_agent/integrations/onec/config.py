"""Загрузка конфигурации подключения к 1С.

Использует общий файл `config/onec-config.json` — тот же, что и
`config/onec/odata-client.js` (Skill onec-odata). Значения из переменных
окружения (ODATA_BASE_URL, ODATA_USERNAME, ODATA_PASSWORD, ONEC_DATABASE)
имеют приоритет над значениями из файла.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from buh_ai_agent.integrations.onec.errors import OnecError


class OnecOrganizationDefaults(BaseModel):
    """Организация по умолчанию из конфигурации 1С."""

    name: str = ""
    inn: str = ""


class OnecDefaults(BaseModel):
    """Значения по умолчанию для документов (файл onec-config.json)."""

    organization: OnecOrganizationDefaults = Field(default_factory=OnecOrganizationDefaults)
    currency_code: str = Field(default="643", alias="currencyCode")
    vat_rate: str = Field(default="НДС20", alias="vatRate")
    sum_includes_vat: bool = Field(default=True, alias="sumIncludesVat")
    unit_of_measure: str = Field(default="шт", alias="unitOfMeasure")

    model_config = ConfigDict(populate_by_name=True)


class OnecSafety(BaseModel):
    """Правила безопасности записи из конфигурации 1С."""

    allow_write: bool = Field(default=True, alias="allowWrite")
    allow_post: bool = Field(default=True, alias="allowPost")
    allow_unpost: bool = Field(default=False, alias="allowUnpost")
    allow_mark_for_deletion: bool = Field(default=False, alias="allowMarkForDeletion")

    model_config = ConfigDict(populate_by_name=True)


class OnecAuth(BaseModel):
    """Учётные данные базы 1С в файле конфигурации."""

    username: str = ""
    password: SecretStr = SecretStr("")


class OnecDatabase(BaseModel):
    """Описание одной базы 1С в файле конфигурации."""

    label: str = ""
    odata_base_url: str = Field(default="", alias="odataBaseUrl")
    auth: OnecAuth = Field(default_factory=OnecAuth)

    model_config = ConfigDict(populate_by_name=True)

    @property
    def username(self) -> str:
        """Логин из вложенного блока auth."""
        return self.auth.username

    @property
    def password(self) -> SecretStr:
        """Пароль из вложенного блока auth."""
        return self.auth.password


class OnecConnectionConfig(BaseModel):
    """Итоговая конфигурация подключения к одной базе 1С.

    Собирается из файла onec-config.json с наложением переопределений
    из переменных окружения.
    """

    database: str
    base_url: str
    username: str
    password: SecretStr
    defaults: OnecDefaults
    safety: OnecSafety


def load_onec_config(
    config_path: Path | str,
    *,
    database: str = "",
    base_url_override: str = "",
    username_override: str = "",
    password_override: str = "",
) -> OnecConnectionConfig:
    """Загружает и собирает конфигурацию подключения к 1С.

    Args:
        config_path: Путь к файлу onec-config.json.
        database: Имя базы; пусто — defaultDatabase из файла.
        base_url_override: Переопределение URL из переменной ODATA_BASE_URL.
        username_override: Переопределение логина из ODATA_USERNAME.
        password_override: Переопределение пароля из ODATA_PASSWORD.

    Returns:
        Конфигурация подключения к выбранной базе.

    Raises:
        OnecError: Файл не найден, JSON не разбирается или база не описана.
    """
    path = Path(config_path)
    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise OnecError(f"Файл конфигурации 1С не найден: {path}") from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise OnecError(f"Файл конфигурации 1С не разбирается: {path}: {error}") from error

    database_name = database or raw.get("defaultDatabase", "")
    databases: dict[str, Any] = raw.get("databases") or {}
    if database_name not in databases:
        available = ", ".join(databases) or "нет"
        raise OnecError(f"База «{database_name}» не описана в {path} (доступны: {available})")

    try:
        db = OnecDatabase.model_validate(databases[database_name])
        defaults = OnecDefaults.model_validate(raw.get("defaults") or {})
        safety = OnecSafety.model_validate(raw.get("safety") or {})
    except ValidationError as error:
        raise OnecError(f"Некорректная конфигурация 1С {path}: {error}") from error

    base_url = (base_url_override or db.odata_base_url).rstrip("/") + "/"
    username = username_override or db.username
    password = password_override or db.password.get_secret_value()
    if not base_url or base_url == "/":
        raise OnecError(f"Не задан odataBaseUrl для базы «{database_name}»")
    if not username:
        raise OnecError(f"Не задан username для базы «{database_name}»")
    if not password:
        raise OnecError(f"Не задан пароль для базы «{database_name}»")

    return OnecConnectionConfig(
        database=database_name,
        base_url=base_url,
        username=username,
        password=SecretStr(password),
        defaults=defaults,
        safety=safety,
    )
