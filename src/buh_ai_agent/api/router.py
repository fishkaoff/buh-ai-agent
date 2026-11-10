"""Общий API Router приложения."""

from fastapi import APIRouter

from buh_ai_agent.api.routes import chat, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(chat.router)
