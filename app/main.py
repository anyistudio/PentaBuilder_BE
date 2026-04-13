import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.catalog.registry import GameDataRegistry
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware
from app.db.session import create_session_factory
from app.services.admin_job_service import AdminJobService
from app.services.ai_run_service import AIRunService
from app.services.auth_service import AuthService
from app.services.benchmark_service import BenchmarkService
from app.services.cache_service import CacheService
from app.services.catalog_service import CatalogService
from app.services.data_version_service import DataVersionService
from app.services.event_stream_service import EventStreamService
from app.services.leaderboard_service import LeaderboardService
from app.services.metrics_service import MetricsService
from app.services.session_service import SessionService
from app.services.storage_service import StorageService


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    application = FastAPI(
        title="PentaBuilder Backend",
        version="0.1.0",
    )
    application.state.settings = settings
    application.state.session_factory = create_session_factory(settings.database_url)
    application.state.metrics_service = MetricsService()
    application.state.storage_service = StorageService(settings)
    application.state.game_data_registry = GameDataRegistry(
        application.state.storage_service,
        settings.game_localization_root,
    )
    application.state.data_version_service = DataVersionService(
        settings,
        application.state.storage_service,
    )
    application.state.catalog_service = CatalogService(
        data_version_service=application.state.data_version_service,
        registry=application.state.game_data_registry,
    )
    application.state.cache_service = CacheService()
    application.state.leaderboard_service = LeaderboardService()
    application.state.session_service = SessionService(application.state.storage_service)
    application.state.auth_service = AuthService(
        settings,
        storage_service=application.state.storage_service,
        leaderboard_service=application.state.leaderboard_service,
    )
    application.state.event_stream_service = EventStreamService()
    application.state.benchmark_service = BenchmarkService(
        settings,
        application.state.storage_service,
    )
    application.state.ai_run_service = AIRunService(
        settings=settings,
        storage_service=application.state.storage_service,
        data_version_service=application.state.data_version_service,
        catalog_service=application.state.catalog_service,
        registry=application.state.game_data_registry,
        cache_service=application.state.cache_service,
        leaderboard_service=application.state.leaderboard_service,
        session_service=application.state.session_service,
        event_stream_service=application.state.event_stream_service,
        metrics_service=application.state.metrics_service,
    )
    application.state.admin_job_service = AdminJobService(
        session_factory=application.state.session_factory,
        storage_service=application.state.storage_service,
        data_version_service=application.state.data_version_service,
        registry=application.state.game_data_registry,
        cache_service=application.state.cache_service,
        benchmark_service=application.state.benchmark_service,
        ai_run_service=application.state.ai_run_service,
    )

    allowed_origins = list(settings.cors_allowed_origins)
    if settings.is_local and not allowed_origins:
        allowed_origins = [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    if allowed_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    application.add_middleware(RequestIDMiddleware)
    application.include_router(api_router)
    register_exception_handlers(application)

    return application


app = create_app()


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.is_local,
    )
