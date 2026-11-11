"""Фабрика FastAPI-приложения."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from buh_ai_agent import __version__
from buh_ai_agent.agent.graph import build_chat_graph
from buh_ai_agent.agent.service import AgentService
from buh_ai_agent.api.router import api_router
from buh_ai_agent.core.settings import get_settings
from buh_ai_agent.llm.factory import create_llm


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Управление жизненным циклом приложения.

    Создаёт LLM и компилирует граф один раз при старте: одни и те же
    экземпляры обслуживают все HTTP-запросы. Память диалогов и 1С OData
    будут подключены на следующих этапах.
    """
    llm = create_llm(get_settings())
    app.state.agent_service = AgentService(build_chat_graph(llm))
    yield


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
