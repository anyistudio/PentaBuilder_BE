from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_ai_run_service, get_current_user, get_db_session
from app.api.schemas.ai_run import (
    AIRunCreateRequest,
    AIRunPayload,
    AIRunStreamingPayload,
    LLMLogClearPayload,
)
from app.api.schemas.common import ApiResponse
from app.core.errors import ApiError
from app.core.llm_debug import clear_llm_debug_log
from app.db.models import User
from app.services.ai_run_service import AIRunService

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


@router.post("/runs")
def create_ai_run(
    request: Request,
    payload: AIRunCreateRequest,
    background_tasks: BackgroundTasks,
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[User | None, Depends(get_current_user)],
    ai_run_service: Annotated[AIRunService, Depends(get_ai_run_service)],
):
    request.state.session_id = payload.session_id
    run, cached_result = ai_run_service.create_run(
        session,
        user=current_user,
        session_id=UUID(payload.session_id) if payload.session_id else None,
        run_type=payload.run_type,
        context=payload.context,
        response_preferences=payload.response_preferences,
        operation_context=payload.payload,
        stream=payload.stream,
    )
    request.state.run_id = str(run.id)
    if cached_result is not None and not payload.stream:
        return ApiResponse[AIRunPayload](
            request_id=request.state.request_id,
            data=AIRunPayload(run=ai_run_service.to_summary_schema(run), result=cached_result),
        )
    if payload.stream:
        ai_run_service.event_stream_service.init_run(str(run.id))
        background_tasks.add_task(
            ai_run_service.execute_streaming_run,
            request.app.state.session_factory,
            run_id=run.id,
            context=payload.context,
            response_preferences=payload.response_preferences,
            operation_context=payload.payload,
        )
        return JSONResponse(
            status_code=202,
            content=ApiResponse[AIRunStreamingPayload](
                request_id=request.state.request_id,
                data=AIRunStreamingPayload(
                    run=ai_run_service.to_summary_schema(run),
                    stream_url=f"/api/v1/ai/runs/{run.id}/events",
                ),
            ).model_dump(mode="json"),
        )

    result = ai_run_service.execute_run(
        session,
        run=run,
        context=payload.context,
        response_preferences=payload.response_preferences,
        operation_context=payload.payload,
    )
    return ApiResponse[AIRunPayload](
        request_id=request.state.request_id,
        data=AIRunPayload(run=ai_run_service.to_summary_schema(run), result=result),
    )


@router.get("/runs/{run_id}")
def get_ai_run(
    request: Request,
    run_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[User | None, Depends(get_current_user)],
    ai_run_service: Annotated[AIRunService, Depends(get_ai_run_service)],
) -> ApiResponse[AIRunPayload]:
    request.state.run_id = str(run_id)
    run = ai_run_service.get_run(session, run_id=run_id, user=current_user)
    return ApiResponse[AIRunPayload](
        request_id=request.state.request_id,
        data=AIRunPayload(
            run=ai_run_service.to_summary_schema(run),
            result=run.structured_result,
        ),
    )


@router.get("/runs/{run_id}/events")
def stream_ai_run_events(
    request: Request,
    run_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[User | None, Depends(get_current_user)],
    ai_run_service: Annotated[AIRunService, Depends(get_ai_run_service)],
) -> StreamingResponse:
    request.state.run_id = str(run_id)
    ai_run_service.get_run(session, run_id=run_id, user=current_user)
    return StreamingResponse(
        ai_run_service.event_stream_service.stream(str(run_id)),
        media_type="text/event-stream",
    )


@router.post("/debug/llm-log/clear")
def clear_debug_llm_log(request: Request) -> ApiResponse[LLMLogClearPayload]:
    settings = request.app.state.settings
    if not settings.debug_llm:
        raise ApiError(
            "LLM debug logging is disabled for this environment.",
            status_code=404,
            code="llm_debug_disabled",
        )

    payload = LLMLogClearPayload.model_validate(clear_llm_debug_log())
    return ApiResponse[LLMLogClearPayload](
        request_id=request.state.request_id,
        data=payload,
    )
