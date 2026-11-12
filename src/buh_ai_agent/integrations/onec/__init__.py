"""Интеграция с 1С по OData 3.0: клиент, конфигурация, метаданные, ошибки."""

from buh_ai_agent.integrations.onec.client import OnecClient, format_document_date
from buh_ai_agent.integrations.onec.config import (
    OnecConnectionConfig,
    OnecDefaults,
    OnecSafety,
    load_onec_config,
)
from buh_ai_agent.integrations.onec.errors import (
    OnecApiError,
    OnecAuthError,
    OnecConnectionError,
    OnecError,
)

__all__ = [
    "OnecApiError",
    "OnecAuthError",
    "OnecClient",
    "OnecConnectionConfig",
    "OnecConnectionError",
    "OnecDefaults",
    "OnecError",
    "OnecSafety",
    "format_document_date",
    "load_onec_config",
]
