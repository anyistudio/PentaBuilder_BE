from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
)
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models import User
from app.db.session import managed_session
from app.services.admin_job_service import AdminJobService
from app.services.ai_run_service import AIRunService
from app.services.auth_service import AuthService
from app.services.benchmark_service import BenchmarkService
from app.services.cache_service import CacheService
from app.services.asset_cache_service import AssetCacheService
from app.services.catalog_service import CatalogService
from app.services.data_version_service import DataVersionService
from app.services.event_stream_service import EventStreamService
from app.services.leaderboard_service import LeaderboardService
from app.services.metrics_service import MetricsService
from app.services.session_service import SessionService
from app.services.storage_service import StorageService

bearer_scheme = HTTPBearer(auto_error=False)
basic_scheme = HTTPBasic(auto_error=False)


def get_db_session(request: Request) -> Generator[Session, None, None]:
    yield from managed_session(request.app.state.session_factory)


def get_storage_service(request: Request) -> StorageService:
    return request.app.state.storage_service


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


def get_data_version_service(request: Request) -> DataVersionService:
    return request.app.state.data_version_service


def get_catalog_service(request: Request) -> CatalogService:
    return request.app.state.catalog_service


def get_session_service(request: Request) -> SessionService:
    return request.app.state.session_service


def get_cache_service(request: Request) -> CacheService:
    return request.app.state.cache_service


def get_asset_cache_service(request: Request) -> AssetCacheService:
    return request.app.state.asset_cache_service


def get_leaderboard_service(request: Request) -> LeaderboardService:
    return request.app.state.leaderboard_service


def get_event_stream_service(request: Request) -> EventStreamService:
    return request.app.state.event_stream_service


def get_metrics_service(request: Request) -> MetricsService:
    return request.app.state.metrics_service


def get_benchmark_service(request: Request) -> BenchmarkService:
    return request.app.state.benchmark_service


def get_ai_run_service(request: Request) -> AIRunService:
    return request.app.state.ai_run_service


def get_admin_job_service(request: Request) -> AdminJobService:
    return request.app.state.admin_job_service


def get_current_user(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> User | None:
    if credentials is None:
        return None
    user = auth_service.authenticate_access_token(session, credentials.credentials)
    request.state.user_id = str(user.id)
    return user


def get_required_user(
    current_user: Annotated[User | None, Depends(get_current_user)],
) -> User:
    if current_user is None:
        raise ApiError(
            "Authentication required.",
            status_code=401,
            code="unauthorized",
        )
    return current_user


def get_admin_user(
    request: Request,
    credentials: Annotated[HTTPBasicCredentials | None, Depends(basic_scheme)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> str:
    if credentials is None or not auth_service.is_valid_admin_credentials(
        credentials.username,
        credentials.password,
    ):
        raise ApiError(
            "Admin authentication required.",
            status_code=401,
            code="admin_only",
        )
    request.state.user_id = credentials.username
    return credentials.username
