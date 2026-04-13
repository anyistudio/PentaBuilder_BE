from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_auth_service, get_db_session, get_required_user
from app.api.schemas.auth import (
    AuthExchangePayload,
    AuthExchangeRequest,
    PatchMePreferencesRequest,
    UserSchema,
)
from app.api.schemas.common import ApiResponse
from app.db.models import User
from app.services.auth_service import AuthService

router = APIRouter(prefix="/api/v1", tags=["auth"])


@router.post("/auth/exchange")
def exchange_auth_token(
    request: Request,
    payload: AuthExchangeRequest,
    session: Annotated[Session, Depends(get_db_session)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> ApiResponse[AuthExchangePayload]:
    principal = auth_service.exchange_token(
        session,
        provider=payload.provider,
        provider_token=payload.provider_token,
    )
    return ApiResponse[AuthExchangePayload](
        request_id=request.state.request_id,
        data=AuthExchangePayload(
            access_token=principal.access_token or "",
            expires_in=principal.expires_in or 0,
            user=auth_service.to_user_schema(principal.user),
        ),
    )


@router.get("/me")
def get_me(
    request: Request,
    current_user: Annotated[User, Depends(get_required_user)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> ApiResponse[UserSchema]:
    return ApiResponse[UserSchema](
        request_id=request.state.request_id,
        data=auth_service.to_user_schema(current_user),
    )


@router.patch("/me/preferences")
def patch_me_preferences(
    request: Request,
    payload: PatchMePreferencesRequest,
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_required_user)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> ApiResponse[UserSchema]:
    user = auth_service.update_preferences(
        session,
        user=current_user,
        username=payload.username,
        preferred_language=payload.preferred_language.value if payload.preferred_language else None,
        preferred_terminology_style=(
            payload.preferred_terminology_style.value
            if payload.preferred_terminology_style
            else None
        ),
    )
    return ApiResponse[UserSchema](
        request_id=request.state.request_id,
        data=auth_service.to_user_schema(user),
    )


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_required_user)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
    auth_service.delete_user(session, user=current_user)
