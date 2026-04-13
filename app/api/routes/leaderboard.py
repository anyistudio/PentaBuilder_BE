from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import (
    get_data_version_service,
    get_db_session,
    get_leaderboard_service,
    get_required_user,
)
from app.api.schemas.common import ApiResponse
from app.api.schemas.leaderboard import (
    LeaderboardEntrySchema,
    LeaderboardListPayload,
    LeaderboardTopUserSchema,
    PaginationSchema,
)
from app.db.models import User
from app.domain.enums import Game
from app.domain.match_context import canonicalize_catalog_slug
from app.services.data_version_service import DataVersionService
from app.services.leaderboard_service import LeaderboardService

router = APIRouter(prefix="/api/v1/leaderboard", tags=["leaderboard"])


@router.get("")
def list_leaderboard(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_required_user)],
    leaderboard_service: Annotated[LeaderboardService, Depends(get_leaderboard_service)],
    data_version_service: Annotated[DataVersionService, Depends(get_data_version_service)],
    game: Game,
    data_version: str | None = None,
    own_champion_slug: str | None = None,
    enemy_champion_slug: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ApiResponse[LeaderboardListPayload]:
    del current_user
    resolved_data_version = (
        data_version_service.get_active_version(session).data_version
        if data_version is None
        else data_version
    )
    own_slug = canonicalize_catalog_slug(game, own_champion_slug) if own_champion_slug else None
    enemy_slug = (
        canonicalize_catalog_slug(game, enemy_champion_slug) if enemy_champion_slug else None
    )
    items = leaderboard_service.list_entries(
        session,
        game=game.value,
        data_version=resolved_data_version,
        own_champion_slug=own_slug,
        enemy_champion_slug=enemy_slug,
        limit=limit,
        offset=offset,
    )
    payload = LeaderboardListPayload(
        game=game,
        data_version=resolved_data_version,
        items=[
            LeaderboardEntrySchema(
                own_champion_slug=item.own_champion_slug,
                enemy_champion_slug=item.enemy_champion_slug,
                top_run_id=str(item.top_run_id),
                top_session_id=str(item.top_session_id) if item.top_session_id else None,
                top_user=LeaderboardTopUserSchema(
                    id=str(item.top_user_id) if item.top_user_id else None,
                    username=item.top_username_snapshot,
                ),
                top_score=item.top_score,
                updated_at=item.updated_at.isoformat() if item.updated_at else None,
            )
            for item in items
        ],
        pagination=PaginationSchema(limit=limit, offset=offset),
    )
    return ApiResponse[LeaderboardListPayload](
        request_id=request.state.request_id,
        data=payload,
    )


@router.get("/{game}/{own_champion_slug}")
def get_champion_leaderboard(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_required_user)],
    leaderboard_service: Annotated[LeaderboardService, Depends(get_leaderboard_service)],
    data_version_service: Annotated[DataVersionService, Depends(get_data_version_service)],
    game: Game,
    own_champion_slug: str,
    data_version: str | None = None,
    enemy_champion_slug: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ApiResponse[LeaderboardListPayload]:
    return list_leaderboard(
        request=request,
        session=session,
        current_user=current_user,
        leaderboard_service=leaderboard_service,
        data_version_service=data_version_service,
        game=game,
        data_version=data_version,
        own_champion_slug=own_champion_slug,
        enemy_champion_slug=enemy_champion_slug,
        limit=limit,
        offset=offset,
    )
