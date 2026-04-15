import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.ai.graphs.online_run_graph import OnlineRunGraph
from app.ai.orchestration.result_contracts import get_result_response_schema
from app.ai.providers.base import BaseLLMClient, LLMUsage
from app.ai.providers.factory import create_llm_client
from app.ai.tools.catalog_tools import CatalogToolset
from app.api.schemas.ai_run import AIRunSummarySchema
from app.catalog.registry import CatalogSnapshot, GameDataRegistry
from app.core.config import Settings
from app.core.errors import ApiError
from app.db.models import AIRun, BaselineBuild, ModelCalibration, SessionRecord, User
from app.domain.enums import RunStatus, RunType
from app.domain.match_context import (
    MatchContext,
    ResponsePreferences,
    RuneSelection,
    build_response_variant_hash,
    build_semantic_context_hash,
    build_slot_count_for_game,
    validate_slug_for_game,
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
DISPLAY_OPEN_TAG = "<display>"
DISPLAY_CLOSE_TAG = "</display>"
JSON_OPEN_TAG = "<json>"
JSON_CLOSE_TAG = "</json>"
STREAMABLE_RUN_TYPES = {
    RunType.RECOMMEND_FULL_BUILD,
    RunType.EXPLAIN_SLOT,
    RunType.CHAT_FOLLOWUP,
}


@dataclass
class PreparedRun:
    snapshot: CatalogSnapshot
    baseline: dict[str, Any] | None
    calibration_summary: str | None
    reference_summary: str | None
    session_memory_summary: str | None
    reply_to_run_summary: str | None
    provider_name: str
    model_name: str
    llm_client: BaseLLMClient
    graph: OnlineRunGraph


@dataclass
class SectionedStreamResult:
    display_text: str
    structured_result: dict[str, Any]
    usage: LLMUsage | None


class _SectionedStreamParser:
    def __init__(self) -> None:
        self.mode = "seek_display"
        self.buffer = ""
        self.display_parts: list[str] = []
        self.json_parts: list[str] = []

    @property
    def display_text(self) -> str:
        return "".join(self.display_parts).strip()

    @property
    def json_text(self) -> str:
        return "".join(self.json_parts).strip()

    def push(self, chunk: str) -> str:
        self.buffer += chunk
        visible_parts: list[str] = []
        while True:
            if self.mode == "seek_display":
                index = self.buffer.find(DISPLAY_OPEN_TAG)
                if index < 0:
                    self.buffer = self.buffer[-(len(DISPLAY_OPEN_TAG) - 1) :]
                    break
                self.buffer = self.buffer[index + len(DISPLAY_OPEN_TAG) :]
                self.mode = "in_display"
                continue

            if self.mode == "in_display":
                index = self.buffer.find(DISPLAY_CLOSE_TAG)
                if index < 0:
                    safe_length = max(0, len(self.buffer) - (len(DISPLAY_CLOSE_TAG) - 1))
                    if safe_length == 0:
                        break
                    visible = self.buffer[:safe_length]
                    visible_parts.append(visible)
                    self.display_parts.append(visible)
                    self.buffer = self.buffer[safe_length:]
                    break
                visible = self.buffer[:index]
                if visible:
                    visible_parts.append(visible)
                    self.display_parts.append(visible)
                self.buffer = self.buffer[index + len(DISPLAY_CLOSE_TAG) :]
                self.mode = "seek_json"
                continue

            if self.mode == "seek_json":
                index = self.buffer.find(JSON_OPEN_TAG)
                if index < 0:
                    self.buffer = self.buffer[-(len(JSON_OPEN_TAG) - 1) :]
                    break
                self.buffer = self.buffer[index + len(JSON_OPEN_TAG) :]
                self.mode = "in_json"
                continue

            if self.mode == "in_json":
                index = self.buffer.find(JSON_CLOSE_TAG)
                if index < 0:
                    safe_length = max(0, len(self.buffer) - (len(JSON_CLOSE_TAG) - 1))
                    if safe_length == 0:
                        break
                    self.json_parts.append(self.buffer[:safe_length])
                    self.buffer = self.buffer[safe_length:]
                    break
                json_chunk = self.buffer[:index]
                if json_chunk:
                    self.json_parts.append(json_chunk)
                self.buffer = self.buffer[index + len(JSON_CLOSE_TAG) :]
                self.mode = "done"
                self.buffer = ""
                break

            self.buffer = ""
            break
        return "".join(visible_parts)

    def finish(self) -> None:
        if self.mode != "done":
            raise ApiError(
                "Streaming output did not contain the required <display> and <json> sections.",
                code="provider_error",
                status_code=502,
            )


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
            context=context,
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
        cached_result = None
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
                    cached_result = cache_entry.structured_result
            else:
                cache_entry = self.cache_service.lookup_reference_cache(
                    session,
                    run_type=run_type.value,
                    semantic_context_hash=semantic_context_hash,
                )
                if cache_entry is not None:
                    cache_resolution = "reference_used"
        if cached_result is None and cache_resolution == "bypass":
            cache_resolution = "miss"
        if not use_cache:
            cache_resolution = "bypass"

        initial_status = (
            RunStatus.COMPLETED.value
            if cached_result is not None and not stream
            else RunStatus.ACCEPTED.value
        )
        run = AIRun(
            session_id=bound_session.id if bound_session else None,
            user_id=user.id if user else None,
            run_type=run_type.value,
            status=initial_status,
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
            structured_result=cached_result,
            score_value=cached_result.get("score") if cached_result else None,
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        if cached_result is not None and not stream:
            self._finalize_cached_run(
                session,
                run=run,
                context=context,
                response_preferences=response_preferences,
                result=cached_result,
            )
        return run, cached_result

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
        streamed_text: str | None = None,
        additional_usage: LLMUsage | None = None,
        initial_graph_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        if run.cache_resolution == "strong_hit" and run.structured_result is not None:
            run.status = RunStatus.COMPLETED.value
            session.add(run)
            session.commit()
            session.refresh(run)
            return run.structured_result

        try:
            prepared = self._prepare_run(
                session,
                run=run,
                context=context,
                response_preferences=response_preferences,
                operation_context=operation_context,
                provider_name_override=provider_name_override,
                model_name_override=model_name_override,
            )
            graph_input = dict(initial_graph_state or {})
            if "context" not in graph_input:
                graph_input["context"] = context.model_dump(mode="json")
            if "operation_context" not in graph_input:
                graph_input["operation_context"] = operation_context
            if streamed_text is not None:
                graph_input["streamed_text"] = streamed_text
            graph_result = prepared.graph.invoke(graph_input)
            result = graph_result["result"]
            provider_usage = self._merge_usage_payloads(
                primary=result.pop("_provider_usage", {}),
                additional=additional_usage,
                provider_name=prepared.provider_name,
                model_name=prepared.model_name,
            )
            self._complete_run(
                session,
                run=run,
                context=context,
                response_preferences=response_preferences,
                operation_context=operation_context,
                result=result,
                provider_usage=provider_usage,
                tool_trace=graph_result.get("tool_trace") or [],
                tool_facts=graph_result.get("tool_facts") or {},
                prompt_artifact=graph_result.get("prompt"),
                started_at=started_at,
            )
            return result
        except Exception as exc:
            self._mark_run_failed(session, run=run, exc=exc)
            raise

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
        run: AIRun | None = None
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
            if run.cache_resolution == "strong_hit" and run.structured_result is not None:
                self._finalize_cached_run(
                    session,
                    run=run,
                    context=context,
                    response_preferences=response_preferences,
                    result=run.structured_result,
                )
                self._publish_cached_stream(
                    run=run,
                    response_preferences=response_preferences,
                )
                return

            prepared = self._prepare_run(
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
                {
                    "phase": "planning",
                    "status": "started",
                    "summary": (
                        "Inspecting the current context and deciding whether "
                        "extra grounded data is needed."
                    ),
                },
            )
            graph_state = prepared.graph.collect_tool_context(
                {
                    "context": context.model_dump(mode="json"),
                    "operation_context": operation_context,
                }
            )
            tool_trace = list(graph_state.get("tool_trace", []))
            if not tool_trace:
                tool_trace = [
                    {
                        "phase": "planning",
                        "status": "completed",
                        "summary": "Injected context was sufficient, so no tool calls were needed.",
                    }
                ]
            for tool_event in tool_trace:
                self.event_stream_service.publish(
                    str(run.id),
                    "tool_event",
                    tool_event,
                )
            self.event_stream_service.publish(
                str(run.id),
                "tool_event",
                {
                    "phase": "drafting",
                    "status": "started",
                    "summary": "Tool context is ready. Streaming the user-visible draft now.",
                },
            )
            response_schema = get_result_response_schema(
                run_type=RunType(run.run_type),
                context=context,
            )
            preview_prompt = prepared.graph.build_prompt_package(
                operation_context=operation_context,
                output_mode="stream_sections",
                response_schema=response_schema,
                tool_facts=graph_state.get("tool_facts"),
            )
            try:
                stream_result = self._stream_sectioned_result(
                    run_id=run.id,
                    llm_client=prepared.llm_client,
                    prompt_package=preview_prompt,
                    response_preferences=response_preferences,
                )
                finalized_state = prepared.graph.finalize_existing_result(
                    {
                        **graph_state,
                        "operation_context": operation_context,
                        "streamed_text": stream_result.display_text,
                        "result": stream_result.structured_result,
                        "model_result": stream_result.structured_result,
                        "provider_usage_payloads": [
                            *list(graph_state.get("provider_usage_payloads", [])),
                            {
                                "provider_name": prepared.provider_name,
                                "model_name": prepared.model_name,
                                "tokens_input": (
                                    stream_result.usage.input_tokens
                                    if stream_result.usage
                                    else None
                                ),
                                "tokens_output": (
                                    stream_result.usage.output_tokens
                                    if stream_result.usage
                                    else None
                                ),
                                "latency_ms": (
                                    stream_result.usage.latency_ms
                                    if stream_result.usage
                                    else None
                                ),
                                "cost_usd": (
                                    stream_result.usage.cost_usd
                                    if stream_result.usage
                                    else None
                                ),
                            },
                        ],
                    }
                )
                result = finalized_state["result"]
                provider_usage = result.pop("_provider_usage", {})
                self.event_stream_service.publish(
                    str(run.id),
                    "tool_event",
                    {
                        "phase": "drafting",
                        "status": "completed",
                        "summary": (
                            "Draft stream completed. Structured result extracted successfully."
                        ),
                    },
                )
                self._complete_run(
                    session,
                    run=run,
                    context=context,
                    response_preferences=response_preferences,
                    operation_context=operation_context,
                    result=result,
                    provider_usage=provider_usage,
                    tool_trace=finalized_state.get("tool_trace") or [],
                    tool_facts=finalized_state.get("tool_facts") or {},
                    prompt_artifact={
                        "system_prompt": preview_prompt.system_prompt,
                        "user_prompt": preview_prompt.user_prompt,
                        "response_schema": response_schema,
                        "output_mode": "stream_sections",
                    },
                    started_at=None,
                )
            except Exception:
                self.event_stream_service.publish(
                    str(run.id),
                    "tool_event",
                    {
                        "phase": "drafting",
                        "status": "fallback",
                        "summary": (
                            "Sectioned streaming output could not be finalized cleanly. "
                            "Falling back to structured generation."
                        ),
                    },
                )
                result = self.execute_run(
                    session,
                    run=run,
                    context=context,
                    response_preferences=response_preferences,
                    operation_context=operation_context,
                    provider_name_override=prepared.provider_name,
                    model_name_override=prepared.model_name,
                    initial_graph_state=graph_state,
                )
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
            if run is not None:
                self._mark_run_failed(session, run=run, exc=exc)
                self.event_stream_service.publish(
                    str(run.id),
                    "run_failed",
                    {
                        "run_id": str(run.id),
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
            tokens_input=run.tokens_input,
            tokens_output=run.tokens_output,
            cost_usd=float(run.cost_usd) if run.cost_usd is not None else None,
            latency_ms=run.latency_ms,
            score_value=run.score_value,
            created_at=run.created_at.isoformat() if run.created_at else None,
        )

    def _validate_operation_context(
        self,
        *,
        run_type: RunType,
        context: MatchContext,
        operation_context: dict[str, Any],
    ) -> None:
        build_slot_count = build_slot_count_for_game(context.game)
        if run_type in {RunType.RECOMMEND_SLOT, RunType.EXPLAIN_SLOT}:
            slot_index = operation_context.get("slot_index")
            if not isinstance(slot_index, int) or not 0 <= slot_index < build_slot_count:
                raise ApiError("Invalid payload.", code="invalid_payload", status_code=400)
        if run_type == RunType.COMPARE_BUILDS:
            comparison_context = operation_context.get("comparison_context")
            if not isinstance(comparison_context, dict):
                raise ApiError("Invalid payload.", code="invalid_payload", status_code=400)
            own_build = comparison_context.get("own_build")
            own_runes = comparison_context.get("own_runes")
            if not isinstance(own_build, list) or len(own_build) != build_slot_count:
                raise ApiError("Invalid payload.", code="invalid_payload", status_code=400)
            if not isinstance(own_runes, dict):
                raise ApiError("Invalid payload.", code="invalid_payload", status_code=400)
            for slot in own_build:
                if slot is not None:
                    validate_slug_for_game(context.game, slot)
            try:
                comparison_runes = RuneSelection.model_validate(own_runes)
            except Exception as exc:
                raise ApiError("Invalid payload.", code="invalid_payload", status_code=400) from exc
            comparison_runes.primary = [
                validate_slug_for_game(context.game, rune_slug)
                for rune_slug in comparison_runes.primary
            ]
            comparison_runes.secondary = [
                validate_slug_for_game(context.game, rune_slug)
                for rune_slug in comparison_runes.secondary
            ]
            comparison_context["own_runes"] = comparison_runes.model_dump(mode="json")
        if run_type == RunType.CHAT_FOLLOWUP:
            user_message = operation_context.get("user_message")
            if not isinstance(user_message, str):
                raise ApiError("Invalid payload.", code="invalid_payload", status_code=400)
            cleaned_message = " ".join(user_message.split())[:500]
            if not cleaned_message:
                raise ApiError("Invalid payload.", code="invalid_payload", status_code=400)
            operation_context["user_message"] = cleaned_message
            reply_to_run_id = operation_context.get("reply_to_run_id")
            if reply_to_run_id is not None:
                try:
                    UUID(str(reply_to_run_id))
                except ValueError as exc:
                    raise ApiError(
                        "Invalid payload.",
                        code="invalid_payload",
                        status_code=400,
                    ) from exc

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

    def _prepare_run(
        self,
        session: Session,
        *,
        run: AIRun,
        context: MatchContext,
        response_preferences: ResponsePreferences,
        operation_context: dict[str, Any],
        provider_name_override: str | None,
        model_name_override: str | None,
    ) -> PreparedRun:
        version = self.data_version_service.get_version(session, data_version=context.data_version)
        if version is None:
            raise ApiError("Unknown data version.", status_code=404, code="invalid_context")
        snapshot = self.registry.get_or_load(
            data_version=version.data_version,
            source_root=version.source_root,
        )
        baseline = self._load_baseline(session, context=context)
        provider_name, model_name = self._resolve_model_ref(
            run_type=RunType(run.run_type),
            provider_name_override=provider_name_override,
            model_name_override=model_name_override,
        )
        calibration = self._load_calibration(
            session,
            context=context,
            provider_name=provider_name,
            model_name=model_name,
        )
        reference_summary = self._load_reference_summary(session, run=run)
        session_memory_summary = self._load_session_memory_summary(session, run=run)
        reply_to_run_summary = self._load_reply_to_run_summary(
            session,
            run=run,
            operation_context=operation_context,
        )
        llm_client = create_llm_client(
            settings=self.settings,
            provider_name=provider_name,
            model_name=model_name,
        )
        if llm_client is None:
            raise ApiError(
                "No LLM client is configured for the requested provider/model.",
                code="provider_not_configured",
                status_code=503,
            )
        selector_llm_client = create_llm_client(
            settings=self.settings,
            provider_name=self.settings.fast_reasoning_provider,
            model_name=self.settings.fast_reasoning_model,
        )
        graph = OnlineRunGraph(
            run_type=RunType(run.run_type),
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
            baseline=baseline,
            reference_summary=reference_summary,
            calibration_summary=calibration.summary_excerpt if calibration else None,
            session_memory_summary=session_memory_summary,
            reply_to_run_summary=reply_to_run_summary,
            llm_client=llm_client,
            session=session,
            toolset=CatalogToolset(
                catalog_service=self.catalog_service,
                selector_llm_client=selector_llm_client or llm_client,
            ),
        )
        return PreparedRun(
            snapshot=snapshot,
            baseline=baseline,
            calibration_summary=calibration.summary_excerpt if calibration else None,
            reference_summary=reference_summary,
            session_memory_summary=session_memory_summary,
            reply_to_run_summary=reply_to_run_summary,
            provider_name=provider_name,
            model_name=model_name,
            llm_client=llm_client,
            graph=graph,
        )

    def _resolve_model_ref(
        self,
        *,
        run_type: RunType,
        provider_name_override: str | None,
        model_name_override: str | None,
    ) -> tuple[str, str]:
        if provider_name_override or model_name_override:
            return (
                provider_name_override or self.settings.primary_reasoning_provider,
                model_name_override or self.settings.primary_reasoning_model,
            )
        if run_type == RunType.CHAT_FOLLOWUP:
            return self.settings.fast_reasoning_provider, self.settings.fast_reasoning_model
        return self.settings.primary_reasoning_provider, self.settings.primary_reasoning_model

    def _load_baseline(self, session: Session, *, context: MatchContext) -> dict[str, Any] | None:
        stmt = sa.select(BaselineBuild).where(
            BaselineBuild.game == context.game.value,
            BaselineBuild.data_version == context.data_version,
            BaselineBuild.own_champion_slug == context.own_champion_slug,
        )
        record = session.scalar(stmt)
        if record is None:
            return None
        build_order = record.recommended_build
        return {
            "recommended_build_order": build_order,
            "recommended_build": build_order,
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

    def _load_reference_summary(self, session: Session, *, run: AIRun) -> str | None:
        if run.cache_resolution != "reference_used":
            return None
        reference_entry = self.cache_service.lookup_reference_cache(
            session,
            run_type=run.run_type,
            semantic_context_hash=run.semantic_context_hash or "",
        )
        if reference_entry is None:
            return None
        return reference_entry.structured_result.get("summary")

    def _load_session_memory_summary(self, session: Session, *, run: AIRun) -> str | None:
        if run.run_type != RunType.CHAT_FOLLOWUP.value or run.session_id is None:
            return None
        session_record = session.get(SessionRecord, run.session_id)
        if session_record is None:
            return None
        transcript = self.storage_service.read_json_object(session_record.transcript_object_key)
        events = transcript.get("events", [])[-6:]
        lines: list[str] = []
        for event in events:
            payload = event.get("payload", {})
            if event.get("type") == "ai_run":
                lines.append(
                    f"- {payload.get('run_type', 'ai_run')}: "
                    f"{str(payload.get('summary') or '')[:220]}"
                )
            elif event.get("type") == "user_action":
                lines.append(
                    f"- user_action/{payload.get('action', 'unknown')}: "
                    f"{str(payload)[:160]}"
                )
        return "\n".join(lines) if lines else None

    def _load_reply_to_run_summary(
        self,
        session: Session,
        *,
        run: AIRun,
        operation_context: dict[str, Any],
    ) -> str | None:
        reply_to_run_id = operation_context.get("reply_to_run_id")
        if not reply_to_run_id:
            return None
        reply_run = session.get(AIRun, UUID(str(reply_to_run_id)))
        if reply_run is None:
            return None
        if run.session_id is not None and reply_run.session_id != run.session_id:
            return None
        summary = (reply_run.structured_result or {}).get("summary")
        if not summary:
            return None
        return f"Run type: {reply_run.run_type}\nSummary: {summary}"

    def _publish_cached_stream(
        self,
        *,
        run: AIRun,
        response_preferences: ResponsePreferences,
    ) -> None:
        result = run.structured_result or {}
        channel = "answer" if run.run_type == RunType.CHAT_FOLLOWUP.value else "summary"
        self.event_stream_service.publish(
            str(run.id),
            "tool_event",
            {
                "phase": "planning",
                "status": "cached",
                "summary": (
                    "Served from strong cache. No new tool calls or "
                    "model planning were needed."
                ),
            },
        )
        self.event_stream_service.publish(
            str(run.id),
            "tool_event",
            {
                "phase": "drafting",
                "status": "cached",
                "summary": "Replaying the cached user-visible text stream.",
            },
        )
        preview_text = str(result.get(channel) or result.get("summary") or "")
        for chunk in self._chunk_text(preview_text):
            self.event_stream_service.publish(
                str(run.id),
                "message_delta",
                {
                    "channel": channel,
                    "language": response_preferences.language.value,
                    "delta": chunk,
                },
            )
        self.event_stream_service.publish(
            str(run.id),
            "run_completed",
            {
                "run_id": str(run.id),
                "status": RunStatus.COMPLETED.value,
                "cache_resolution": run.cache_resolution,
                "result": result,
            },
        )

    def _stream_sectioned_result(
        self,
        *,
        run_id: UUID,
        llm_client: BaseLLMClient,
        prompt_package,
        response_preferences: ResponsePreferences,
    ) -> SectionedStreamResult:
        parser = _SectionedStreamParser()
        final_usage: LLMUsage | None = None
        for event in llm_client.stream_text(
            prompt=prompt_package.user_prompt,
            system_prompt=prompt_package.system_prompt,
            temperature=0.35,
        ):
            if event.event_type == "text_delta" and event.delta:
                visible_delta = parser.push(event.delta)
                if visible_delta:
                    self.event_stream_service.publish(
                        str(run_id),
                        "message_delta",
                        {
                            "channel": prompt_package.stream_channel or "summary",
                            "language": response_preferences.language.value,
                            "delta": visible_delta,
                        },
                    )
            elif event.event_type == "completed":
                final_usage = event.usage

        parser.finish()
        try:
            structured_result = json.loads(parser.json_text)
        except json.JSONDecodeError as exc:
            raise ApiError(
                "Streaming JSON section was invalid.",
                code="provider_error",
                status_code=502,
            ) from exc
        return SectionedStreamResult(
            display_text=parser.display_text,
            structured_result=structured_result,
            usage=final_usage,
        )

    def _finalize_cached_run(
        self,
        session: Session,
        *,
        run: AIRun,
        context: MatchContext,
        response_preferences: ResponsePreferences,
        result: dict[str, Any],
    ) -> None:
        run.status = RunStatus.COMPLETED.value
        session.add(run)
        session.commit()
        session.refresh(run)
        self._finalize_completed_run(
            session,
            run=run,
            context=context,
            response_preferences=response_preferences,
            result=result,
        )

    def _complete_run(
        self,
        session: Session,
        *,
        run: AIRun,
        context: MatchContext,
        response_preferences: ResponsePreferences,
        operation_context: dict[str, Any],
        result: dict[str, Any],
        provider_usage: dict[str, Any],
        tool_trace: list[dict[str, Any]],
        tool_facts: dict[str, Any],
        prompt_artifact: dict[str, Any] | None,
        started_at: float | None,
    ) -> None:
        run.status = RunStatus.COMPLETED.value
        run.provider_name = provider_usage.get("provider_name") or run.provider_name
        run.model_name = provider_usage.get("model_name") or run.model_name
        run.tokens_input = provider_usage.get("tokens_input")
        run.tokens_output = provider_usage.get("tokens_output")
        run.cost_usd = provider_usage.get("cost_usd")
        run.latency_ms = provider_usage.get("latency_ms") or (
            round((time.perf_counter() - started_at) * 1000) if started_at is not None else None
        )
        run.score_value = result.get("score")
        run.structured_result = result
        run.artifact_object_key = f"runs/{run.id}.json"
        run.error_code = None
        run.error_message = None
        self.storage_service.write_json(
            run.artifact_object_key,
            {
                "run_id": str(run.id),
                "run_type": run.run_type,
                "context": context.model_dump(mode="json"),
                "payload": operation_context,
                "tool_trace": tool_trace,
                "tool_facts": tool_facts,
                "result": result,
                "prompt": prompt_artifact,
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
        self._finalize_completed_run(
            session,
            run=run,
            context=context,
            response_preferences=response_preferences,
            result=result,
        )

    def _finalize_completed_run(
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

    def _mark_run_failed(self, session: Session, *, run: AIRun, exc: Exception) -> None:
        run.status = RunStatus.FAILED.value
        run.error_code = getattr(exc, "code", "provider_error")
        run.error_message = str(exc)
        session.add(run)
        session.commit()

    def _merge_usage_payloads(
        self,
        *,
        primary: dict[str, Any],
        additional: LLMUsage | None,
        provider_name: str,
        model_name: str,
    ) -> dict[str, Any]:
        merged = {
            "provider_name": primary.get("provider_name") or provider_name,
            "model_name": primary.get("model_name") or model_name,
            "tokens_input": primary.get("tokens_input"),
            "tokens_output": primary.get("tokens_output"),
            "latency_ms": primary.get("latency_ms"),
            "cost_usd": primary.get("cost_usd"),
        }
        if additional is None:
            return merged
        if additional.input_tokens is not None:
            merged["tokens_input"] = (merged["tokens_input"] or 0) + additional.input_tokens
        if additional.output_tokens is not None:
            merged["tokens_output"] = (merged["tokens_output"] or 0) + additional.output_tokens
        if additional.latency_ms is not None:
            merged["latency_ms"] = (merged["latency_ms"] or 0) + additional.latency_ms
        if additional.cost_usd is not None:
            merged["cost_usd"] = (merged["cost_usd"] or 0) + additional.cost_usd
        return merged

    def _chunk_text(self, text: str, size: int = 24) -> list[str]:
        if not text:
            return []
        return [text[index : index + size] for index in range(0, len(text), size)]
