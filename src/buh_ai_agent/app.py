"""Фабрика FastAPI-приложения."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langchain_core.tools import BaseTool

from buh_ai_agent import __version__
from buh_ai_agent.agent.graph import build_chat_graph
from buh_ai_agent.agent.prompt import build_system_prompt
from buh_ai_agent.agent.service import AgentService
from buh_ai_agent.api.router import api_router
from buh_ai_agent.core.settings import get_settings
from buh_ai_agent.integrations.onec.client import OnecClient
from buh_ai_agent.integrations.onec.config import load_onec_config
from buh_ai_agent.llm.factory import create_llm
from buh_ai_agent.operations import OperationService
from buh_ai_agent.skills.loader import SkillLoader
from buh_ai_agent.skills.registry import SkillRegistry
from buh_ai_agent.storage.sqlite import SQLiteStore
from buh_ai_agent.tools.onec import make_onec_tools
from buh_ai_agent.tools.operations import make_operation_tools
from buh_ai_agent.tools.skills import make_skill_tools

logger = logging.getLogger(__name__)


def _discover_skills(settings: object) -> SkillRegistry:
    """Обнаруживает Skills и регистрирует их в реестре.

    Args:
        settings: Настройки приложения (skills_dir).

    Returns:
        Реестр Skills (пустой, если директория недоступна).
    """
    registry = SkillRegistry(SkillLoader(settings.skills_dir))  # type: ignore[attr-defined]
    try:
        registry.register_discovered()
    except Exception as error:
        logger.warning("Skills не загружены: %s", error)
    return registry


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Управление жизненным циклом приложения.

    Создаёт LLM, обнаруживает Skills, подключает Tools 1С и компилирует
    граф один раз при старте: одни и те же экземпляры обслуживают все
    HTTP-запросы. История диалогов и операции хранятся в SQLite и
    переживают перезапуск приложения.
    """
    settings = get_settings()
    llm = create_llm(settings)

    storage = SQLiteStore(settings.storage_sqlite_path)
    operation_service = OperationService(storage)
    onec_database_id = ""
    onec_organization_id = ""
    app.state.storage = storage
    app.state.operation_store = storage
    app.state.operation_service = operation_service

    skill_registry = _discover_skills(settings)
    tools: list[BaseTool] = list(make_skill_tools(skill_registry, storage))
    tools.extend(make_operation_tools(operation_service))

    onec_client: OnecClient | None = None
    try:
        onec_config = load_onec_config(
            settings.onec_config_path,
            database=settings.onec_database,
            base_url_override=settings.odata_base_url,
            username_override=settings.odata_username,
            password_override=settings.odata_password.get_secret_value(),
        )
        onec_client = OnecClient.from_config(
            onec_config,
            timeout=settings.onec_timeout,
            max_retries=settings.onec_max_retries,
        )
        tools.extend(make_onec_tools(onec_client, onec_config))
        app.state.onec_client = onec_client
        app.state.onec_config = onec_config
        onec_database_id = onec_config.database
        onec_organization_id = onec_config.defaults.organization.name
    except Exception as error:
        logger.warning("Инструменты 1С не подключены: %s", error)

    system_prompt = build_system_prompt(skill_registry)
    app.state.skill_registry = skill_registry
    app.state.agent_service = AgentService(
        build_chat_graph(
            llm,
            tools=tools,
            system_prompt=system_prompt,
            max_iterations=settings.agent_max_iterations,
        ),
        store=storage,
        operation_service=operation_service,
        history_limit=settings.agent_history_messages,
        organization_id=onec_organization_id,
        database_id=onec_database_id,
    )
    yield
    if onec_client is not None:
        await onec_client.aclose()
    storage.close()


def create_app() -> FastAPI:
    """Создаёт и настраивает FastAPI-приложение."""
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        debug=settings.debug,
    )
    app.include_router(api_router)
    return app
