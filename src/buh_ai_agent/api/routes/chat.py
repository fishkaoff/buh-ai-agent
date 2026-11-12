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

    Диалог идентифицируется `chat_id`: агент загружает историю и активные
    операции этого чата, контекст других чатов не используется.

    Args:
        request: Валидированное сообщение (chat_id, user_id, message).
        http_request: HTTP-запрос, из которого берётся сервис агента.

    Returns:
        Ответ агента и данные активной операции (если есть).
    """
    agent_service: AgentService = http_request.app.state.agent_service
    result = await agent_service.run(request.chat_id, request.user_id, request.message)
    return ChatResponse(
        reply=result.reply,
        operation_id=result.operation_id,
        operation_status=result.operation_status,
    )
