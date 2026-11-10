"""Маршруты чата с AI-агентом."""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from buh_ai_agent.api.schemas.chat import ChatNotImplementedResponse, ChatRequest

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post(
    "",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    responses={
        status.HTTP_501_NOT_IMPLEMENTED: {"model": ChatNotImplementedResponse},
    },
)
async def chat(request: ChatRequest) -> JSONResponse:
    """Обработка сообщения пользователя.

    Обработка сообщений ещё не реализована: LangGraph и LLM-интеграция
    будут подключены на следующих этапах.
    """
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content=ChatNotImplementedResponse(
            detail=(
                "Обработка сообщений ещё не реализована: "
                "LangGraph и LLM-интеграция будут подключены позже."
            ),
        ).model_dump(),
    )
