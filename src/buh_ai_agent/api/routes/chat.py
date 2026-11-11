"""Маршруты чата с AI-агентом."""

from fastapi import APIRouter, Request, status

from buh_ai_agent.agent.service import AgentService
from buh_ai_agent.api.schemas.chat import ChatRequest, ChatResponse

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post(
    "",
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Некорректное сообщение."},
    },
)
async def chat(request: ChatRequest, http_request: Request) -> ChatResponse:
    """Обрабатывает сообщение пользователя через граф агента.

    Args:
        request: Валидированное сообщение пользователя.
        http_request: HTTP-запрос, из которого берётся сервис агента.

    Returns:
        Ответ агента.
    """
    agent_service: AgentService = http_request.app.state.agent_service
    reply = await agent_service.run(request.message)
    return ChatResponse(reply=reply)
