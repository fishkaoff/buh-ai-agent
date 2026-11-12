"""Маршруты операций: подтверждение и отклонение.

Telegram Adapter отправляет отдельные команды с `operation_id` и
`chat_id`. Подтверждение переводит операцию `awaiting_confirmation` →
`confirmed`, отклонение — `awaiting_confirmation` → `rejected`.
На этом этапе смена статуса не выполняет отправку по ЭДО.

Проверки: операция существует (404), принадлежит указанному чату (403),
статус допускает смену (409) — повторное подтверждение/отклонение
запрещены.
"""

from fastapi import APIRouter, HTTPException, Request, status

from buh_ai_agent.api.schemas.chat import OperationActionRequest, OperationStatusResponse
from buh_ai_agent.operations import OperationError, OperationService

router = APIRouter(prefix="/operations", tags=["operations"])


def _change_status(
    request: Request,
    operation_id: str,
    body: OperationActionRequest,
    action: str,
) -> OperationStatusResponse:
    """Общая логика смены статуса операции (confirm/reject).

    Args:
        request: HTTP-запрос (для доступа к состоянию приложения).
        operation_id: Идентификатор операции.
        body: Команда с идентификатором чата.
        action: Действие («confirm» или «reject»).

    Returns:
        Ответ с идентификатором и новым статусом операции.

    Raises:
        HTTPException: 404 — не найдена; 403 — чужой диалог; 409 —
            недопустимый переход статуса.
    """
    operation_service: OperationService = request.app.state.operation_service
    operation = operation_service.get(operation_id)
    if operation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Операция {operation_id} не найдена.",
        )
    if operation.chat_id != body.chat_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Операция принадлежит другому диалогу.",
        )
    try:
        if action == "confirm":
            updated = operation_service.confirm(operation_id, chat_id=body.chat_id)
        else:
            updated = operation_service.reject(operation_id, chat_id=body.chat_id)
    except OperationError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    request.app.state.storage.append_message(
        body.chat_id,
        operation.user_id,
        "event",
        f"Операция {operation_id} {'подтверждена' if action == 'confirm' else 'отклонена'} "
        f"(статус {updated.status}).",
        operation_id=operation_id,
    )
    return OperationStatusResponse(operation_id=updated.id, status=updated.status.value)


@router.post("/{operation_id}/confirm", status_code=status.HTTP_200_OK)
async def confirm_operation(
    operation_id: str, body: OperationActionRequest, request: Request
) -> OperationStatusResponse:
    """Подтверждает операцию (awaiting_confirmation → confirmed).

    Args:
        operation_id: Идентификатор операции.
        body: Команда с идентификатором чата.
        request: HTTP-запрос.

    Returns:
        Новый статус операции.
    """
    return _change_status(request, operation_id, body, "confirm")


@router.post("/{operation_id}/reject", status_code=status.HTTP_200_OK)
async def reject_operation(
    operation_id: str, body: OperationActionRequest, request: Request
) -> OperationStatusResponse:
    """Отклоняет операцию (awaiting_confirmation → rejected).

    Args:
        operation_id: Идентификатор операции.
        body: Команда с идентификатором чата.
        request: HTTP-запрос.

    Returns:
        Новый статус операции.
    """
    return _change_status(request, operation_id, body, "reject")
