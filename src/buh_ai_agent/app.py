"""Фабрика FastAPI-приложения."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from buh_ai_agent import __version__
from buh_ai_agent.api.router import api_router
from buh_ai_agent.core.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Управление жизненным циклом приложения.

    Пока здесь нет долгоживущих ресурсов (LLM, LangGraph, 1С OData).
    Они будут подключены на следующих этапах.
    """
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
