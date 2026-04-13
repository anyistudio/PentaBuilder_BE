import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.ai.graphs.online_run_graph import OnlineRunGraph
from app.ai.providers.factory import create_llm_client
from app.ai.tools.catalog_tools import CatalogToolset
from app.api.schemas.ai_run import AIRunSummarySchema
from app.catalog.registry import GameDataRegistry
from app.core.config import Settings
from app.core.errors import ApiError
from app.db.models import AIRun, BaselineBuild, ModelCalibration, SessionRecord, User
from app.domain.enums import RunStatus, RunType
from app.domain.match_context import (
    MatchContext,
    ResponsePreferences,
    build_response_variant_hash,
    build_semantic_context_hash,
)
from app.services.cache_service import CACHEABLE_RUN_TYPES, CacheService
from app.services.catalog_service import CatalogService
from app.services.data_version_service import DataVersionService
from app.services.event_stream_service import EventStreamService
from app.services.leaderboard_service import LeaderboardService
from app.services.metrics_service import MetricsService
from app.services.session_service import SessionService
from app.services.storage_service import StorageService

LOGGER = logging.getLogger(__name__)
STREAMABLE_RUN_TYPES = {RunType.EXPLAIN_SLOT, RunType.CHAT_FOLLOWUP}


class AIRunService:
    def __init__(
        self,
        *,
        settings: Settings,
        storage_service: StorageService,
        data_version_service: DataVersionService,
        catalog_service: CatalogService,
        registry: GameDataRegistry,
        cache_service: CacheService,
        leaderboard_service: LeaderboardService,
        session_service: SessionService,
        event_stream_service: EventStreamService,
        metrics_service: MetricsService,
    ) -> None:
        self.settings = settings
        self.storage_service = storage_service
        self.data_version_service = data_version_service
        self.catalog_service = catalog_service
        self.registry = registry
        self.cache_service = cache_service
        self.leaderboard_service = leaderboard_service
        self.session_service = session_service
        self.event_stream_service = event_stream_service
        self.metrics_service = metrics_service
        self.catalog_tools = CatalogToolset(catalog_service)

    def create_run(
        self,
        session: Session,
        *,
        user: User | None,
        session_id: UUID | None,
        run_type: RunType,
        context: MatchContext,
        response_preferences: ResponsePreferences,
        operation_context: dict[str, Any],
        stream: bool,
        use_cache: bool = True,
    ) -> tuple[AIRun, dict[str, Any] | None]:
        if stream and run_type not in STREAMABLE_RUN_TYPES:
            raise ApiError(
                "Streaming is not supported for this run type.",
                status_code=400,
                code="stream_not_supported_for_run_type",
            )
        self._validate_operation_context(
            run_type=run_type,
            operation_context=operation_context,
        )
        bound_session = self._resolve_bound_session(
            session,
            user=user,
            session_id=session_id,
            context=context,
        )
        semantic_context_hash = build_semantic_context_hash(
            context,
            operation_context=operation_context,
        )
        response_variant_hash = build_response_variant_hash(
            context,
            run_type=run_type,
            response_preferences=response_preferences,
            operation_context=operation_context,
        )
        cache_resolution = "bypass"
        result = None

        cache_entry = None
        if use_cache and run_type.value in CACHEABLE_RUN_TYPES:
            if not context.environment.free_text:
                cache_entry = self.cache_service.lookup_strong_cache(
                    session,
                    run_type=run_type.value,
                    response_variant_hash=response_variant_hash,
                )
                if cache_entry is not None:
                    cache_entry.hit_count += 1
                    cache_entry.last_hit_at = datetime.now(tz=timezone.utc)
                    session.add(cache_entry)
                    session.commit()
                    cache_resolution = "strong_hit"
                    result = cache_entry.structured_result
            else:
                cache_entry = self.cache_service.lookup_reference_cache(
                    session,
                    run_type=run_type.value,
                    semantic_context_hash=semantic_context_hash,
                )
                if cache_entry is not None:
                    cache_resolution = "reference_used"
        if result is None and cache_resolution == "bypass":
            cache_resolution = "miss"
        if not use_cache:
            cache_resolution = "bypass"

        run = AIRun(
            session_id=bound_session.id if bound_session else None,
            user_id=user.id if user else None,
            run_type=run_type.value,
            status=RunStatus.ACCEPTED.value if stream else RunStatus.COMPLETED.value,
            game=context.game.value,
            data_version=context.data_version,
            own_champion_slug=context.own_champion_slug,
            enemy_comp_key=context.enemy_comp_key,
            normalized_environment_key=context.normalized_environment_key,
            has_free_text_environment=bool(context.environment.free_text),
            operation_context=operation_context,
            semantic_context_hash=semantic_context_hash,
            response_variant_hash=response_variant_hash,
            cache_resolution=cache_resolution,
            cached_entry_id=cache_entry.id if cache_entry is not None else None,
        )
        if result is not None:
            run.structured_result = result
            run.score_value = result.get("score")
        session.add(run)
        session.commit()
        session.refresh(run)
        if result is not None:
            self._finalize_cached_run(
                session,
                run=run,
                context=context,
                response_preferences=response_preferences,
                result=result,
            )
        return run, result

    def execute_run(
        self,
        session: Session,
        *,
        run: AIRun,
        context: MatchContext,
        response_preferences: ResponsePreferences,
        operation_context: dict[str, Any],
        provider_name_override: str | None = None,
        model_name_override: str | None = None,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        version = self.data_version_service.get_version(session, data_version=context.data_version)
        if version is None:
            raise ApiError("Unknown data version.", status_code=404, code="invalid_context")
        snapshot = self.registry.get_or_load(
            data_version=version.data_version,
            source_root=version.source_root,
        )
        baseline = self._load_baseline(session, context=context)
        calibration = self._load_calibration(
            session,
            context=context,
            provider_name=provider_name_override or self.settings.calibration_provider,
            model_name=model_name_override or self.settings.calibration_model,
        )
        reference_summary = None
        if run.cache_resolution == "reference_used":
            reference_entry = self.cache_service.lookup_reference_cache(
                session,
                run_type=run.run_type,
                semantic_context_hash=run.semantic_context_hash or "",
            )
            if reference_entry is not None:
                reference_summary = reference_entry.structured_result.get("summary")

        provider_name = provider_name_override or self.settings.primary_reasoning_provider
        model_name = model_name_override or self.settings.primary_reasoning_model

        llm_client = create_llm_client(
            settings=self.settings,
            provider_name=provider_name,
            model_name=model_name,
        )
        graph = OnlineRunGraph(
            run_type=RunType(run.run_type),
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
            baseline=baseline,
            reference_summary=reference_summary,
            calibration_summary=calibration.summary_excerpt if calibration else None,
            llm_client=llm_client,
        )
        graph_result = graph.invoke(
            {
                "context": context.model_dump(mode="json"),
                "operation_context": operation_context,
            }
        )
        result = graph_result["result"]
        provider_usage = result.pop("_provider_usage", {})
        run.status = RunStatus.COMPLETED.value
        run.provider_name = provider_usage.get("provider_name") or provider_name
        run.model_name = provider_usage.get("model_name") or model_name
        run.tokens_input = provider_usage.get("tokens_input")
        run.tokens_output = provider_usage.get("tokens_output")
        run.cost_usd = provider_usage.get("cost_usd")
        run.latency_ms = provider_usage.get("latency_ms") or round(
            (time.perf_counter() - started_at) * 1000
        )
        run.score_value = result.get("score")
        run.structured_result = result
        run.artifact_object_key = f"runs/{run.id}.json"
        self.storage_service.write_json(
            run.artifact_object_key,
            {
                "run_id": str(run.id),
                "run_type": run.run_type,
                "context": context.model_dump(mode="json"),
                "payload": operation_context,
                "result": result,
                "prompt": graph_result.get("prompt"),
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        if (
            run.run_type in CACHEABLE_RUN_TYPES
            and not context.environment.free_text
            and run.cache_resolution != "bypass"
        ):
            self.cache_service.save_cache_entry(
                session,
                run_type=run.run_type,
                game=run.game,
                data_version=run.data_version,
                own_champion_slug=run.own_champion_slug or "",
                enemy_comp_key=run.enemy_comp_key or "_none",
                enemy_count=(
                    0
                    if run.enemy_comp_key in {None, "_none"}
                    else len((run.enemy_comp_key or "").split("|"))
                ),
                normalized_environment_key=run.normalized_environment_key or "_none",
                semantic_context_hash=run.semantic_context_hash or "",
                response_variant_hash=run.response_variant_hash or "",
                language=response_preferences.language.value,
                terminology_style=response_preferences.terminology_style.value,
                structured_result=result,
                artifact_object_key=run.artifact_object_key,
                source_run_id=run.id,
            )
        if run.run_type == "evaluate_build":
            self.leaderboard_service.update_from_run(
                session, run=run, result=result, username_snapshot=None
            )
        if run.session_id:
            session_record = session.get(SessionRecord, run.session_id)
            if session_record:
                self.session_service.append_run_event(
                    session,
                    session_record=session_record,
                    run_id=run.id,
                    run_type=run.run_type,
                    summary=result.get("summary", ""),
                    result=result,
                )
        self.metrics_service.record_run(
            run_type=run.run_type,
            model_name=run.model_name,
            latency_ms=run.latency_ms,
            cost_usd=float(run.cost_usd) if run.cost_usd is not None else None,
            cache_resolution=run.cache_resolution,
        )
        LOGGER.info(
            "ai_run_completed",
            extra={
                "run_id": str(run.id),
                "session_id": str(run.session_id) if run.session_id else None,
                "user_id": str(run.user_id) if run.user_id else None,
                "model_name": run.model_name,
                "latency_ms": run.latency_ms,
                "cost_usd": float(run.cost_usd) if run.cost_usd is not None else None,
                "cache_resolution": run.cache_resolution,
            },
        )
        return result

    def execute_streaming_run(
        self,
        session_factory,
        *,
        run_id: UUID,
        context: MatchContext,
        response_preferences: ResponsePreferences,
        operation_context: dict[str, Any],
        provider_name_override: str | None = None,
        model_name_override: str | None = None,
    ) -> None:
        session = session_factory()
        try:
            run = session.get(AIRun, run_id)
            if run is None:
                return
            run.status = RunStatus.STREAMING.value
            session.add(run)
            session.commit()
            self.event_stream_service.publish(
                str(run.id),
                "run_started",
                {"run_id": str(run.id), "run_type": run.run_type},
            )
            self.event_stream_service.publish(
                str(run.id),
                "tool_event",
                {"tool": "prepare_context", "status": "completed"},
            )
            result = self.execute_run(
                session,
                run=run,
                context=context,
                response_preferences=response_preferences,
                operation_context=operation_context,
                provider_name_override=provider_name_override,
                model_name_override=model_name_override,
            )
            self.event_stream_service.publish(
                str(run.id),
                "tool_event",
                {"tool": "generate_result", "status": "completed"},
            )
            for chunk in self._stream_text(result.get("summary", "")):
                self.event_stream_service.publish(
                    str(run.id),
                    "message_delta",
                    {
                        "channel": "answer",
                        "language": response_preferences.language.value,
                        "delta": chunk,
                    },
                )
                time.sleep(0.02)
            self.event_stream_service.publish(
                str(run.id),
                "run_completed",
                {
                    "run_id": str(run.id),
                    "status": run.status,
                    "cache_resolution": run.cache_resolution,
                    "result": result,
                },
            )
        except Exception as exc:
            if run_id:
                run = session.get(AIRun, run_id)
                if run:
                    run.status = RunStatus.FAILED.value
                    run.error_code = getattr(exc, "code", "provider_error")
                    run.error_message = str(exc)
                    session.add(run)
                    session.commit()
                self.event_stream_service.publish(
                    str(run_id),
                    "run_failed",
                    {
                        "run_id": str(run_id),
                        "status": RunStatus.FAILED.value,
                        "error": {
                            "code": getattr(exc, "code", "provider_error"),
                            "message": str(exc),
                        },
                    },
                )
        finally:
            session.close()

    def get_run(self, session: Session, *, run_id: UUID, user: User | None = None) -> AIRun:
        run = session.get(AIRun, run_id)
        if run is None:
            raise ApiError("Run not found.", status_code=404, code="run_not_found")
        if run.user_id is not None and (user is None or run.user_id != user.id):
            raise ApiError("Unauthorized run.", status_code=401, code="unauthorized_session")
        return run

    def to_summary_schema(self, run: AIRun) -> AIRunSummarySchema:
        return AIRunSummarySchema(
            id=str(run.id),
            session_id=str(run.session_id) if run.session_id else None,
            run_type=RunType(run.run_type),
            status=RunStatus(run.status),
            cache_resolution=run.cache_resolution,
            provider_name=run.provider_name,
            model_name=run.model_name,
            latency_ms=run.latency_ms,
            score_value=run.score_value,
            created_at=run.created_at.isoformat() if run.created_at else None,
        )

    def _validate_operation_context(
        self, *, run_type: RunType, operation_context: dict[str, Any]
    ) -> None:
        if run_type in {RunType.RECOMMEND_SLOT, RunType.EXPLAIN_SLOT}:
            slot_index = operation_context.get("slot_index")
            if not isinstance(slot_index, int) or not 0 <= slot_index <= 5:
                raise ApiError("Invalid payload.", code="invalid_payload", status_code=400)
        if run_type == RunType.COMPARE_BUILDS and "comparison_context" not in operation_context:
            raise ApiError("Invalid payload.", code="invalid_payload", status_code=400)
        if run_type == RunType.CHAT_FOLLOWUP:
            user_message = operation_context.get("user_message")
            if not isinstance(user_message, str):
                raise ApiError("Invalid payload.", code="invalid_payload", status_code=400)
            cleaned_message = " ".join(user_message.split())[:500]
            if not cleaned_message:
                raise ApiError("Invalid payload.", code="invalid_payload", status_code=400)
            operation_context["user_message"] = cleaned_message

    def _resolve_bound_session(
        self,
        session: Session,
        *,
        user: User | None,
        session_id: UUID | None,
        context: MatchContext,
    ) -> SessionRecord | None:
        if session_id is None:
            return None
        record = session.get(SessionRecord, session_id)
        if record is None:
            raise ApiError("Session not found.", status_code=404, code="session_not_found")
        if user is None or record.user_id != user.id:
            raise ApiError("Unauthorized session.", status_code=401, code="unauthorized_session")
        if record.game != context.game.value:
            raise ApiError("Session game mismatch.", status_code=409, code="session_game_mismatch")
        return record

    def _load_baseline(self, session: Session, *, context: MatchContext) -> dict[str, Any] | None:
        stmt = sa.select(BaselineBuild).where(
            BaselineBuild.game == context.game.value,
            BaselineBuild.data_version == context.data_version,
            BaselineBuild.own_champion_slug == context.own_champion_slug,
        )
        record = session.scalar(stmt)
        if record is None:
            return None
        return {
            "recommended_build": record.recommended_build,
            "recommended_runes": record.recommended_runes,
            "summary": "Loaded precomputed baseline build.",
        }

    def _load_calibration(
        self,
        session: Session,
        *,
        context: MatchContext,
        provider_name: str,
        model_name: str,
    ) -> ModelCalibration | None:
        stmt = (
            sa.select(ModelCalibration)
            .where(
                ModelCalibration.provider_name == provider_name,
                ModelCalibration.model_name == model_name,
                ModelCalibration.game == context.game.value,
                ModelCalibration.data_version == context.data_version,
                ModelCalibration.status == "completed",
            )
            .order_by(ModelCalibration.created_at.desc())
            .limit(1)
        )
        return session.scalar(stmt)

    def _finalize_cached_run(
        self,
        session: Session,
        *,
        run: AIRun,
        context: MatchContext,
        response_preferences: ResponsePreferences,
        result: dict[str, Any],
    ) -> None:
        if run.run_type == RunType.EVALUATE_BUILD.value:
            self.leaderboard_service.update_from_run(
                session,
                run=run,
                result=result,
                username_snapshot=None,
            )
        if run.session_id:
            session_record = session.get(SessionRecord, run.session_id)
            if session_record is not None:
                self.session_service.append_run_event(
                    session,
                    session_record=session_record,
                    run_id=run.id,
                    run_type=run.run_type,
                    summary=result.get("summary", ""),
                    result=result,
                )
        self.metrics_service.record_run(
            run_type=run.run_type,
            model_name=run.model_name,
            latency_ms=run.latency_ms,
            cost_usd=float(run.cost_usd) if run.cost_usd is not None else None,
            cache_resolution=run.cache_resolution,
        )

    def _stream_text(self, text: str) -> list[str]:
        if not text:
            return []
        chunks: list[str] = []
        remaining = text
        while remaining:
            chunks.append(remaining[:12])
            remaining = remaining[12:]
        return chunks
