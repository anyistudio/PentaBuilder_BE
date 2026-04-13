from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_db_session, get_required_user, get_session_service
from app.api.schemas.common import ApiResponse
from app.api.schemas.session import (
    SessionClaimPayload,
    SessionClaimRequest,
    SessionCreatePayload,
    SessionCreateRequest,
    SessionDetailPayload,
    SessionListPayload,
)
from app.core.errors import ApiError
from app.db.models import User
from app.services.session_service import SessionService

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_session(
    request: Request,
    payload: SessionCreateRequest,
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_required_user)],
    session_service: Annotated[SessionService, Depends(get_session_service)],
) -> ApiResponse[SessionCreatePayload]:
    if payload.game != payload.initial_context.game:
        raise ApiError("Session game mismatch.", status_code=409, code="session_game_mismatch")
    if payload.data_version != payload.initial_context.data_version:
        raise ApiError("Invalid context.", status_code=400, code="invalid_context")
    record = session_service.create_session(
        session,
        user=current_user,
        client_session_id=payload.client_session_id,
        initial_context=payload.initial_context,
    )
    request.state.session_id = str(record.id)
    return ApiResponse[SessionCreatePayload](
        request_id=request.state.request_id,
        data=SessionCreatePayload(session=session_service.to_summary_schema(record)),
    )


@router.get("")
def list_sessions(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_required_user)],
    session_service: Annotated[SessionService, Depends(get_session_service)],
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
) -> ApiResponse[SessionListPayload]:
    del cursor
    items = session_service.list_sessions(session, user=current_user, limit=limit)
    payload = SessionListPayload(items=[session_service.to_summary_schema(item) for item in items])
    return ApiResponse[SessionListPayload](request_id=request.state.request_id, data=payload)


@router.get("/{session_id}")
def get_session_detail(
    request: Request,
    session_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_required_user)],
    session_service: Annotated[SessionService, Depends(get_session_service)],
) -> ApiResponse[SessionDetailPayload]:
    request.state.session_id = str(session_id)
    record, transcript = session_service.get_session_detail(
        session,
        user=current_user,
        session_id=session_id,
    )
    return ApiResponse[SessionDetailPayload](
        request_id=request.state.request_id,
        data=SessionDetailPayload(
            session=session_service.to_summary_schema(record),
            transcript=transcript,
        ),
    )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_required_user)],
    session_service: Annotated[SessionService, Depends(get_session_service)],
) -> None:
    session_service.delete_session(session, user=current_user, session_id=session_id)


@router.post("/{session_id}/claim")
def claim_session(
    request: Request,
    session_id: UUID,
    payload: SessionClaimRequest,
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_required_user)],
    session_service: Annotated[SessionService, Depends(get_session_service)],
) -> ApiResponse[SessionClaimPayload]:
    request.state.session_id = str(session_id)
    transcript = session_service.claim_session(
        session,
        user=current_user,
        session_id=session_id,
        client_session_id=payload.client_session_id,
        events=payload.events,
    )
    return ApiResponse[SessionClaimPayload](
        request_id=request.state.request_id,
        data=SessionClaimPayload(
            session_id=str(session_id),
            claimed_event_count=len(transcript.get("events", [])),
        ),
    )
