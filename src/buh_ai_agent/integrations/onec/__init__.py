"""Интеграция с 1С по OData 3.0: клиент, конфигурация, метаданные, ошибки."""

from buh_ai_agent.integrations.onec.client import OnecClient, format_document_date
from buh_ai_agent.integrations.onec.config import (
    OnecConnectionConfig,
    OnecDatabaseEnv,
    OnecDefaults,
    OnecSafety,
    onec_config_from_settings,
    onec_configs_from_settings,
)
from buh_ai_agent.integrations.onec.errors import (
    OnecApiError,
    OnecAuthError,
    OnecConnectionError,
    OnecError,
)
from buh_ai_agent.integrations.onec.registry import OnecClients

__all__ = [
    "OnecApiError",
    "OnecAuthError",
    "OnecClient",
    "OnecClients",
    "OnecConnectionConfig",
    "OnecConnectionError",
    "OnecDatabaseEnv",
    "OnecDefaults",
    "OnecError",
    "OnecSafety",
    "format_document_date",
    "onec_config_from_settings",
    "onec_configs_from_settings",
]
