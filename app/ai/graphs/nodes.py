import json
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.ai.orchestration.prompt_builder import build_prompt_package
from app.ai.orchestration.result_contracts import get_result_response_schema, validate_run_result
from app.ai.orchestration.tool_plans import (
    ToolSelectionResult,
    get_tool_plan_response_schema,
    validate_tool_plan,
)
from app.ai.providers.base import BaseLLMClient
from app.ai.tools.catalog_tools import CatalogToolset
from app.catalog.registry import CatalogSnapshot
from app.core.errors import ApiError
from app.core.llm_debug import llm_debug_scope
from app.domain.enums import RunType
from app.domain.match_context import MatchContext, ResponsePreferences, validate_slug_for_game

TOOL_ROUND_LIMITS = {
    RunType.EVALUATE_BUILD: 2,
    RunType.RECOMMEND_FULL_BUILD: 4,
    RunType.RECOMMEND_SLOT: 3,
    RunType.EXPLAIN_SLOT: 3,
    RunType.COMPARE_BUILDS: 3,
    RunType.GAME_STATUS: 1,
    RunType.CHAT_FOLLOWUP: 4,
}
TOTAL_TOOL_CALL_LIMIT = 8
MAX_REPAIR_ATTEMPTS = 1


def prepare_context_node(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "context": state["context"],
        "operation_context": state.get("operation_context", {}),
        "streamed_text": state.get("streamed_text"),
        "tool_round_count": state.get("tool_round_count", 0),
        "total_tool_calls": state.get("total_tool_calls", 0),
        "tool_trace": list(state.get("tool_trace", [])),
        "tool_facts": dict(state.get("tool_facts", {})),
        "seen_tool_call_keys": list(state.get("seen_tool_call_keys", [])),
        "pending_tool_calls": list(state.get("pending_tool_calls", [])),
        "tool_context_ready": bool(state.get("tool_context_ready", False)),
        "retry_tool_planning": bool(state.get("retry_tool_planning", False)),
        "provider_usage_payloads": list(state.get("provider_usage_payloads", [])),
        "repair_attempt_count": state.get("repair_attempt_count", 0),
        "validation_errors": list(state.get("validation_errors", [])),
    }


def decide_tool_need_node(
    *,
    run_type: RunType,
    context: MatchContext,
    baseline: dict[str, Any] | None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _node(state: dict[str, Any]) -> dict[str, Any]:
        if state.get("tool_context_ready"):
            return {
                "need_tools": False,
                "tool_decision_reason": "tool_context_ready",
            }
        if state.get("tool_round_count", 0) >= TOOL_ROUND_LIMITS[run_type]:
            return {
                "need_tools": False,
                "tool_context_ready": True,
                "tool_decision_reason": "tool_round_limit_reached",
            }
        if state.get("total_tool_calls", 0) >= TOTAL_TOOL_CALL_LIMIT:
            return {
                "need_tools": False,
                "tool_context_ready": True,
                "tool_decision_reason": "tool_call_limit_reached",
            }
        if state.get("retry_tool_planning"):
            return {
                "need_tools": True,
                "tool_context_ready": False,
                "tool_decision_reason": "retry_after_invalid_tool_plan",
                "retry_tool_planning": False,
            }
        need_tools, reason = _default_tool_need(
            run_type=run_type,
            context=context,
            operation_context=state.get("operation_context", {}),
            baseline=baseline,
        )
        if need_tools:
            return {"need_tools": True, "tool_decision_reason": reason}
        tool_trace = list(state.get("tool_trace", []))
        tool_trace.append(
            {
                "phase": "planning",
                "status": "skipped",
                "summary": _tool_decision_summary(reason),
                "decision_reason": reason,
                "tool_calls": [],
            }
        )
        return {
            "need_tools": False,
            "tool_decision_reason": reason,
            "tool_trace": tool_trace,
        }

    return _node


def tool_select_node(
    *,
    run_type: RunType,
    context: MatchContext,
    response_preferences: ResponsePreferences,
    snapshot: CatalogSnapshot,
    baseline: dict[str, Any] | None,
    reference_summary: str | None,
    calibration_summary: str | None,
    session_memory_summary: str | None,
    reply_to_run_summary: str | None,
    llm_client: BaseLLMClient | None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _node(state: dict[str, Any]) -> dict[str, Any]:
        if not state.get("need_tools"):
            return {"pending_tool_calls": [], "tool_context_ready": True}
        if llm_client is None:
            raise ApiError(
                "No LLM client is configured.",
                code="provider_not_configured",
                status_code=503,
            )
        prompt_package = build_prompt_package(
            run_type=run_type,
            context=context,
            response_preferences=response_preferences,
            operation_context=state.get("operation_context", {}),
            baseline=baseline,
            reference_summary=reference_summary,
            calibration_summary=calibration_summary,
            session_memory_summary=session_memory_summary,
            reply_to_run_summary=reply_to_run_summary,
            snapshot=snapshot,
            tool_facts=state.get("tool_facts"),
            output_mode="tool_plan",
        )
        tool_plan, usage_payload = _call_tool_plan_model(
            llm_client=llm_client,
            prompt=prompt_package.user_prompt,
            system_prompt=prompt_package.system_prompt,
            response_schema=get_tool_plan_response_schema(),
            temperature=0.05,
            error_message="Model returned an invalid tool plan.",
            graph_node="tool_select",
        )
        planned_calls = list(tool_plan.tool_calls)
        sanitized_calls = _sanitize_tool_calls(
            plan=tool_plan.model_dump(mode="json"),
            seen_tool_call_keys=state.get("seen_tool_call_keys", []),
            context=context,
            snapshot=snapshot,
            remaining_capacity=TOTAL_TOOL_CALL_LIMIT - state.get("total_tool_calls", 0),
        )
        provider_usage_payloads = list(state.get("provider_usage_payloads", []))
        provider_usage_payloads.append(usage_payload)
        tool_trace = list(state.get("tool_trace", []))
        tool_trace.append(
            {
                "phase": "planning",
                "status": "ready" if sanitized_calls else "done",
                "summary": _tool_plan_summary(
                    reasoning_summary=tool_plan.reasoning_summary,
                    tool_calls=sanitized_calls,
                    done=tool_plan.done or not sanitized_calls,
                ),
                "tool_calls": [
                    {
                        "tool_name": tool_call["tool_name"],
                        "arguments": dict(tool_call["arguments"]),
                    }
                    for tool_call in sanitized_calls
                ],
                "done": bool(tool_plan.done or not sanitized_calls),
            }
        )
        if not tool_plan.done and planned_calls and not sanitized_calls:
            tool_trace[-1]["status"] = "blocked"
            tool_trace[-1]["done"] = False
            tool_trace[-1]["summary"] = (
                "The previous tool plan used unresolved or invalid arguments. "
                "Retry planning with `resolve_catalog_slug` or a filtered candidate listing."
            )
            return {
                "pending_tool_calls": [],
                "tool_context_ready": False,
                "provider_usage_payloads": provider_usage_payloads,
                "tool_trace": tool_trace,
                "retry_tool_planning": True,
                "tool_round_count": state.get("tool_round_count", 0) + 1,
            }
        if tool_plan.done or not sanitized_calls:
            return {
                "pending_tool_calls": [],
                "tool_context_ready": True,
                "provider_usage_payloads": provider_usage_payloads,
                "tool_trace": tool_trace,
                "retry_tool_planning": False,
            }
        return {
            "pending_tool_calls": sanitized_calls,
            "tool_context_ready": False,
            "provider_usage_payloads": provider_usage_payloads,
            "tool_trace": tool_trace,
            "retry_tool_planning": False,
        }

    return _node


def tool_execute_node(
    *,
    context: MatchContext,
    response_preferences: ResponsePreferences,
    snapshot: CatalogSnapshot,
    session: Session,
    toolset: CatalogToolset,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _node(state: dict[str, Any]) -> dict[str, Any]:
        pending_tool_calls = list(state.get("pending_tool_calls", []))
        if not pending_tool_calls:
            return {"tool_context_ready": True}

        tool_trace = list(state.get("tool_trace", []))
        tool_facts = {
            tool_name: list(entries)
            for tool_name, entries in dict(state.get("tool_facts", {})).items()
        }
        seen_tool_call_keys = list(state.get("seen_tool_call_keys", []))
        provider_usage_payloads = list(state.get("provider_usage_payloads", []))
        executed_calls = 0
        for tool_call in pending_tool_calls:
            with llm_debug_scope(graph_node="tool_execute", tool_name=tool_call["tool_name"]):
                result, trace_entry, usage_payloads = _execute_tool_call(
                    session=session,
                    context=context,
                    response_preferences=response_preferences,
                    snapshot=snapshot,
                    toolset=toolset,
                    tool_call=tool_call,
                )
            tool_trace.append(trace_entry)
            tool_facts.setdefault(tool_call["tool_name"], []).append(result)
            seen_tool_call_keys.append(tool_call["call_key"])
            provider_usage_payloads.extend(usage_payloads)
            executed_calls += 1

        return {
            "pending_tool_calls": [],
            "tool_round_count": state.get("tool_round_count", 0) + 1,
            "total_tool_calls": state.get("total_tool_calls", 0) + executed_calls,
            "tool_trace": tool_trace,
            "tool_facts": tool_facts,
            "seen_tool_call_keys": seen_tool_call_keys,
            "tool_context_ready": False,
            "provider_usage_payloads": provider_usage_payloads,
        }

    return _node


def generate_result_node(
    *,
    run_type: RunType,
    context: MatchContext,
    response_preferences: ResponsePreferences,
    snapshot: CatalogSnapshot,
    baseline: dict[str, Any] | None,
    reference_summary: str | None,
    calibration_summary: str | None,
    session_memory_summary: str | None,
    reply_to_run_summary: str | None,
    llm_client: BaseLLMClient | None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _node(state: dict[str, Any]) -> dict[str, Any]:
        if llm_client is None:
            raise ApiError(
                "No LLM client is configured.",
                code="provider_not_configured",
                status_code=503,
            )

        operation_context = state.get("operation_context", {})
        prompt_package = build_prompt_package(
            run_type=run_type,
            context=context,
            response_preferences=response_preferences,
            operation_context=operation_context,
            baseline=baseline,
            reference_summary=reference_summary,
            calibration_summary=calibration_summary,
            session_memory_summary=session_memory_summary,
            reply_to_run_summary=reply_to_run_summary,
            snapshot=snapshot,
            tool_facts=state.get("tool_facts"),
            streamed_text=state.get("streamed_text"),
        )
        response_schema = get_result_response_schema(
            run_type=run_type,
            context=context,
            operation_context=operation_context,
        )
        raw_result, usage_payload = _call_json_model(
            llm_client=llm_client,
            prompt=prompt_package.user_prompt,
            system_prompt=prompt_package.system_prompt,
            response_schema=response_schema,
            temperature=_temperature_for_run_type(run_type),
            error_message="Model returned invalid JSON.",
            graph_node="generate_result",
        )
        provider_usage_payloads = list(state.get("provider_usage_payloads", []))
        provider_usage_payloads.append(usage_payload)
        return {
            "prompt": {
                "system_prompt": prompt_package.system_prompt,
                "user_prompt": prompt_package.user_prompt,
                "response_schema": response_schema,
            },
            "model_result": raw_result,
            "result": raw_result,
            "provider_usage_payloads": provider_usage_payloads,
            "repair_requested": False,
            "validation_errors": [],
        }

    return _node


def validate_result_node(
    *,
    run_type: RunType,
    context: MatchContext,
    snapshot: CatalogSnapshot,
    toolset: CatalogToolset,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _node(state: dict[str, Any]) -> dict[str, Any]:
        provider_usage_payloads = list(state.get("provider_usage_payloads", []))
        try:
            validated = validate_run_result(
                run_type=run_type,
                raw_result=dict(state["result"]),
                context=context,
                operation_context=state.get("operation_context", {}),
                snapshot=snapshot,
                slug_resolution_toolset=toolset,
                provider_usage_payloads=provider_usage_payloads,
            )
        except ApiError as exc:
            if (
                exc.code == "provider_error"
                and exc.status_code == 502
                and state.get("repair_attempt_count", 0) < MAX_REPAIR_ATTEMPTS
            ):
                return {
                    "provider_usage_payloads": provider_usage_payloads,
                    "repair_requested": True,
                    "validation_errors": _extract_validation_errors(exc),
                }
            raise

        validated["_provider_usage"] = _aggregate_provider_usage(
            provider_usage_payloads
        )
        return {
            "result": validated,
            "final_result": validated,
            "provider_usage_payloads": provider_usage_payloads,
            "repair_requested": False,
            "validation_errors": [],
        }

    return _node


def repair_result_node(
    *,
    run_type: RunType,
    context: MatchContext,
    response_preferences: ResponsePreferences,
    snapshot: CatalogSnapshot,
    baseline: dict[str, Any] | None,
    reference_summary: str | None,
    calibration_summary: str | None,
    session_memory_summary: str | None,
    reply_to_run_summary: str | None,
    llm_client: BaseLLMClient | None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _node(state: dict[str, Any]) -> dict[str, Any]:
        if llm_client is None:
            raise ApiError(
                "No LLM client is configured.",
                code="provider_not_configured",
                status_code=503,
            )
        prompt_package = build_prompt_package(
            run_type=run_type,
            context=context,
            response_preferences=response_preferences,
            operation_context=state.get("operation_context", {}),
            baseline=baseline,
            reference_summary=reference_summary,
            calibration_summary=calibration_summary,
            session_memory_summary=session_memory_summary,
            reply_to_run_summary=reply_to_run_summary,
            snapshot=snapshot,
            tool_facts=state.get("tool_facts"),
            output_mode="repair_json",
            streamed_text=state.get("streamed_text"),
            validation_errors=state.get("validation_errors"),
            candidate_result=state.get("model_result"),
        )
        response_schema = get_result_response_schema(
            run_type=run_type,
            context=context,
            operation_context=state.get("operation_context", {}),
        )
        raw_result, usage_payload = _call_json_model(
            llm_client=llm_client,
            prompt=prompt_package.user_prompt,
            system_prompt=prompt_package.system_prompt,
            response_schema=response_schema,
            temperature=0.05,
            error_message="Model returned invalid repair JSON.",
            graph_node="repair_result",
        )
        provider_usage_payloads = list(state.get("provider_usage_payloads", []))
        provider_usage_payloads.append(usage_payload)
        return {
            "result": raw_result,
            "model_result": raw_result,
            "provider_usage_payloads": provider_usage_payloads,
            "repair_attempt_count": state.get("repair_attempt_count", 0) + 1,
            "repair_requested": False,
        }

    return _node


def _default_tool_need(
    *,
    run_type: RunType,
    context: MatchContext,
    operation_context: dict[str, Any],
    baseline: dict[str, Any] | None,
) -> tuple[bool, str]:
    if run_type == RunType.RECOMMEND_FULL_BUILD:
        if baseline and len(context.enemy_team) <= 1 and not context.environment.free_text:
            return False, "baseline_is_sufficient"
        return True, "need_candidate_comparison"
    if run_type == RunType.RECOMMEND_SLOT:
        return True, "slot_recommendation_allows_tools"
    if run_type == RunType.EXPLAIN_SLOT:
        return True, "slot_explanation_allows_tools"
    if run_type == RunType.COMPARE_BUILDS:
        diff_count = _comparison_diff_count(context=context, operation_context=operation_context)
        return diff_count > 2, "many_build_differences" if diff_count > 2 else "few_differences"
    if run_type == RunType.GAME_STATUS:
        return False, "detailed_context_appendix_is_sufficient"
    if run_type == RunType.CHAT_FOLLOWUP:
        return True, "chat_followup_allows_tools"
    if run_type == RunType.EVALUATE_BUILD:
        filled_slots = len([slot for slot in context.own_build if slot])
        if filled_slots < 3 and context.enemy_team:
            return True, "current_build_is_sparse"
        return False, "injected_context_is_sufficient"
    return False, "no_tools_needed"


def _comparison_diff_count(*, context: MatchContext, operation_context: dict[str, Any]) -> int:
    comparison_context = operation_context.get("comparison_context", {})
    build_b = list(comparison_context.get("own_build") or [])
    diff_count = 0
    for index, item_slug in enumerate(context.own_build):
        other = build_b[index] if index < len(build_b) else None
        if item_slug != other:
            diff_count += 1
    runes_b = comparison_context.get("own_runes") or {}
    if (context.own_runes.primary or []) != list(runes_b.get("primary") or []):
        diff_count += 1
    if (context.own_runes.secondary or []) != list(runes_b.get("secondary") or []):
        diff_count += 1
    return diff_count


def _call_json_model(
    *,
    llm_client: BaseLLMClient,
    prompt: str,
    system_prompt: str,
    response_schema: dict[str, Any],
    temperature: float,
    error_message: str,
    graph_node: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    with llm_debug_scope(graph_node=graph_node):
        llm_result = llm_client.generate_text(
            prompt=prompt,
            system_prompt=system_prompt,
            response_mime_type="application/json",
            response_schema=response_schema,
            temperature=temperature,
        )
    try:
        raw_result = json.loads(llm_result.text)
    except json.JSONDecodeError as exc:
        raise ApiError(
            error_message,
            code="provider_error",
            status_code=502,
        ) from exc
    if not isinstance(raw_result, dict):
        raise ApiError(
            error_message,
            code="provider_error",
            status_code=502,
        )
    usage_payload = {
        "provider_name": llm_result.provider_name,
        "model_name": llm_result.model_name,
        "tokens_input": llm_result.usage.input_tokens,
        "tokens_output": llm_result.usage.output_tokens,
        "latency_ms": llm_result.usage.latency_ms,
        "cost_usd": llm_result.usage.cost_usd,
    }
    return raw_result, usage_payload


def _call_tool_plan_model(
    *,
    llm_client: BaseLLMClient,
    prompt: str,
    system_prompt: str,
    response_schema: dict[str, Any],
    temperature: float,
    error_message: str,
    graph_node: str,
) -> tuple[ToolSelectionResult, dict[str, Any]]:
    with llm_debug_scope(graph_node=graph_node):
        llm_result = llm_client.generate_text(
            prompt=prompt,
            system_prompt=system_prompt,
            response_mime_type="application/json",
            response_schema=response_schema,
            temperature=temperature,
        )

    usage_payload = {
        "provider_name": llm_result.provider_name,
        "model_name": llm_result.model_name,
        "tokens_input": llm_result.usage.input_tokens,
        "tokens_output": llm_result.usage.output_tokens,
        "latency_ms": llm_result.usage.latency_ms,
        "cost_usd": llm_result.usage.cost_usd,
    }

    raw_text = llm_result.text.strip()
    candidates = _extract_json_dict_candidates(raw_text)
    if not candidates:
        raise ApiError(
            error_message,
            code="provider_error",
            status_code=502,
        )

    for candidate in candidates:
        try:
            return validate_tool_plan(candidate), usage_payload
        except ApiError:
            continue

    raise ApiError(
        error_message,
        code="provider_error",
        status_code=502,
        details={"candidate_count": len(candidates)},
    )


def _extract_json_dict_candidates(text: str) -> list[dict[str, Any]]:
    stripped = text.strip()
    if not stripped:
        return []

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return [parsed]

    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    index = 0
    while index < len(stripped):
        while index < len(stripped) and stripped[index].isspace():
            index += 1
        if index >= len(stripped):
            break
        try:
            parsed_candidate, next_index = decoder.raw_decode(stripped, index)
        except json.JSONDecodeError:
            break
        if isinstance(parsed_candidate, dict):
            candidates.append(parsed_candidate)
        index = next_index
    return candidates


def _sanitize_tool_calls(
    *,
    plan: dict[str, Any],
    seen_tool_call_keys: list[str],
    context: MatchContext,
    snapshot: CatalogSnapshot,
    remaining_capacity: int,
) -> list[dict[str, Any]]:
    seen = set(seen_tool_call_keys)
    sanitized_calls: list[dict[str, Any]] = []
    for tool_call in plan.get("tool_calls", [])[: max(0, remaining_capacity)]:
        sanitized = _sanitize_tool_call(
            tool_call=tool_call,
            context=context,
            snapshot=snapshot,
        )
        if sanitized is None:
            continue
        call_key = _tool_call_key(sanitized["tool_name"], sanitized["arguments"])
        if call_key in seen or any(item["call_key"] == call_key for item in sanitized_calls):
            continue
        sanitized["call_key"] = call_key
        sanitized_calls.append(sanitized)
    return sanitized_calls


def _sanitize_tool_call(
    *,
    tool_call: dict[str, Any],
    context: MatchContext,
    snapshot: CatalogSnapshot,
) -> dict[str, Any] | None:
    tool_name = tool_call.get("tool_name")
    arguments = tool_call.get("arguments") or {}
    if not isinstance(arguments, dict):
        return None

    if tool_name in {"get_champion", "get_item", "get_rune"}:
        slug = arguments.get("slug")
        if not isinstance(slug, str):
            return None
        try:
            validated_slug = validate_slug_for_game(context.game, slug)
        except ValueError:
            return None
        if not _entity_exists(
            tool_name=tool_name,
            slug=validated_slug,
            context=context,
            snapshot=snapshot,
        ):
            return None
        return {"tool_name": tool_name, "arguments": {"slug": validated_slug}}

    if tool_name == "batch_get_entities":
        entity_type = arguments.get("entity_type")
        slugs = arguments.get("slugs")
        if entity_type not in {"champion", "item", "rune"} or not isinstance(slugs, list):
            return None
        validated_slugs: list[str] = []
        for raw_slug in slugs[:12]:
            if not isinstance(raw_slug, str):
                continue
            try:
                validated_slug = validate_slug_for_game(context.game, raw_slug)
            except ValueError:
                continue
            if not _entity_exists_for_type(
                entity_type=entity_type,
                slug=validated_slug,
                context=context,
                snapshot=snapshot,
            ):
                continue
            validated_slugs.append(validated_slug)
        if not validated_slugs:
            return None
        return {
            "tool_name": tool_name,
            "arguments": {
                "entity_type": entity_type,
                "slugs": validated_slugs,
            },
        }

    if tool_name == "list_catalog_candidates":
        game = arguments.get("game") or context.game.value
        entity_type = arguments.get("entity_type")
        filters = _extract_candidate_filters(arguments)
        if game != context.game.value or entity_type not in {"champion", "item", "rune"}:
            return None
        if not filters:
            return None
        return {
            "tool_name": tool_name,
            "arguments": {
                "game": game,
                "entity_type": entity_type,
                "filters": filters,
            },
        }

    if tool_name == "list_item_ids":
        game = arguments.get("game") or context.game.value
        raw_category = arguments.get("category")
        if raw_category is None:
            raw_category = arguments.get("categories")
        if raw_category is None:
            raw_category = arguments.get("kind")
        if game != context.game.value:
            return None
        return {
            "tool_name": tool_name,
            "arguments": {
                "game": game,
                "category": _clean_tool_text_or_list(raw_category),
            },
        }

    if tool_name == "resolve_catalog_slug":
        game = arguments.get("game") or context.game.value
        entity_type = arguments.get("entity_type")
        raw_name = arguments.get("raw_name")
        if game != context.game.value or entity_type not in {"champion", "item", "rune"}:
            return None
        if not isinstance(raw_name, str):
            return None
        cleaned_name = " ".join(raw_name.split())[:120]
        if not cleaned_name:
            return None
        return {
            "tool_name": tool_name,
            "arguments": {
                "game": game,
                "entity_type": entity_type,
                "raw_name": cleaned_name,
                "filters": _extract_candidate_filters(arguments),
            },
        }

    if tool_name == "search_catalog":
        entity_type = arguments.get("entity_type")
        query = arguments.get("query")
        limit = arguments.get("limit", 5)
        if entity_type not in {"champion", "item", "rune"} or not isinstance(query, str):
            return None
        cleaned_query = " ".join(query.split())[:120]
        if not cleaned_query:
            return None
        bounded_limit = 5
        if isinstance(limit, int):
            bounded_limit = max(1, min(limit, 8))
        return {
            "tool_name": tool_name,
            "arguments": {
                "entity_type": entity_type,
                "query": cleaned_query,
                "limit": bounded_limit,
            },
        }
    return None


def _execute_tool_call(
    *,
    session: Session,
    context: MatchContext,
    response_preferences: ResponsePreferences,
    snapshot: CatalogSnapshot,
    toolset: CatalogToolset,
    tool_call: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    tool_name = tool_call["tool_name"]
    arguments = dict(tool_call["arguments"])

    if tool_name == "get_champion":
        result = toolset.get_champion(snapshot, arguments["slug"])
        summary = _loaded_single_entity_summary(
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
            entity_type="champion",
            slug=arguments["slug"],
        )
        return result, {
            "phase": "execution",
            "tool": tool_name,
            "status": "completed",
            "summary": summary,
            "arguments": {"slug": arguments["slug"]},
            "champion_slug": arguments["slug"],
        }, []
    if tool_name == "get_item":
        result = toolset.get_item(snapshot, arguments["slug"])
        summary = _loaded_single_entity_summary(
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
            entity_type="item",
            slug=arguments["slug"],
        )
        return result, {
            "phase": "execution",
            "tool": tool_name,
            "status": "completed",
            "summary": summary,
            "arguments": {"slug": arguments["slug"]},
            "item_slug": arguments["slug"],
        }, []
    if tool_name == "get_rune":
        result = toolset.get_rune(snapshot, arguments["slug"])
        summary = _loaded_single_entity_summary(
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
            entity_type="rune",
            slug=arguments["slug"],
        )
        return result, {
            "phase": "execution",
            "tool": tool_name,
            "status": "completed",
            "summary": summary,
            "arguments": {"slug": arguments["slug"]},
            "rune_slug": arguments["slug"],
        }, []
    if tool_name == "batch_get_entities":
        result = toolset.batch_get_entities(
            snapshot,
            entity_type=arguments["entity_type"],
            slugs=arguments["slugs"],
        )
        summary = _loaded_batch_entities_summary(
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
            entity_type=arguments["entity_type"],
            slugs=[
                entity.get("slug")
                for entity in result.get("entities") or []
                if isinstance(entity, dict) and isinstance(entity.get("slug"), str)
            ],
            missing_slugs=result.get("missing_slugs") or [],
        )
        return result, {
            "phase": "execution",
            "tool": tool_name,
            "status": "completed",
            "summary": summary,
            "arguments": {
                "entity_type": arguments["entity_type"],
                "slugs": list(arguments["slugs"]),
            },
            "entity_type": arguments["entity_type"],
            "slug_count": len(arguments["slugs"]),
            "resolved_slugs": [
                entity.get("slug")
                for entity in result.get("entities") or []
                if isinstance(entity, dict) and entity.get("slug")
            ],
            "missing_slugs": result.get("missing_slugs") or [],
        }, []
    if tool_name == "list_catalog_candidates":
        result = toolset.list_catalog_candidates(
            snapshot,
            game=context.game,
            entity_type=arguments["entity_type"],
            filters=arguments.get("filters"),
        )
        summary = _listed_candidates_summary(
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
            entity_type=arguments["entity_type"],
            filters=arguments.get("filters") or {},
            candidate_slugs=[
                candidate.get("slug")
                for candidate in result.get("candidates") or []
                if isinstance(candidate, dict) and isinstance(candidate.get("slug"), str)
            ],
            candidate_count=int(result.get("candidate_count", 0) or 0),
        )
        return result, {
            "phase": "execution",
            "tool": tool_name,
            "status": "completed",
            "summary": summary,
            "arguments": {
                "game": arguments["game"],
                "entity_type": arguments["entity_type"],
                "filters": dict(arguments.get("filters") or {}),
            },
            "entity_type": arguments["entity_type"],
            "candidate_count": result.get("candidate_count", 0),
            "candidate_slugs": [
                candidate.get("slug")
                for candidate in result.get("candidates") or []
                if isinstance(candidate, dict) and candidate.get("slug")
            ][:20],
        }, []
    if tool_name == "list_item_ids":
        result = toolset.list_item_ids(
            snapshot,
            game=context.game,
            category=arguments.get("category"),
        )
        summary = _listed_item_ids_summary(
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
            requested_categories=list(result.get("requested_categories") or []),
            item_slugs=[
                item.get("slug")
                for item in result.get("items") or []
                if isinstance(item, dict) and isinstance(item.get("slug"), str)
            ],
        )
        return result, {
            "phase": "execution",
            "tool": tool_name,
            "status": "completed",
            "summary": summary,
            "arguments": {
                "game": arguments["game"],
                "category": arguments.get("category"),
            },
            "entity_type": "item",
            "item_count": result.get("item_count", 0),
            "item_slugs": [
                item.get("slug")
                for item in result.get("items") or []
                if isinstance(item, dict) and item.get("slug")
            ],
        }, []
    if tool_name == "resolve_catalog_slug":
        result, usage_payloads = toolset.resolve_catalog_slug(
            snapshot,
            game=context.game,
            entity_type=arguments["entity_type"],
            raw_name=arguments["raw_name"],
            filters=arguments.get("filters"),
        )
        summary = _resolved_slug_summary(
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
            entity_type=arguments["entity_type"],
            raw_name=arguments["raw_name"],
            resolved_slug=result.get("resolved_slug"),
            resolution_status=result.get("resolution_status"),
            candidate_slugs=[
                candidate.get("slug")
                for candidate in result.get("candidates") or []
                if isinstance(candidate, dict) and isinstance(candidate.get("slug"), str)
            ],
        )
        return result, {
            "phase": "execution",
            "tool": tool_name,
            "status": "completed",
            "summary": summary,
            "arguments": {
                "game": arguments["game"],
                "entity_type": arguments["entity_type"],
                "raw_name": arguments["raw_name"],
                "filters": dict(arguments.get("filters") or {}),
            },
            "entity_type": arguments["entity_type"],
            "resolution_status": result.get("resolution_status"),
            "resolved_slug": result.get("resolved_slug"),
            "candidate_count": result.get("candidate_count", 0),
            "candidate_slugs": [
                candidate.get("slug")
                for candidate in result.get("candidates") or []
                if isinstance(candidate, dict) and candidate.get("slug")
            ],
        }, usage_payloads
    result = toolset.search_catalog(
        session,
        game=context.game,
        snapshot=snapshot,
        entity_type=arguments["entity_type"],
        query=arguments["query"],
        limit=arguments["limit"],
    )
    summary = _search_catalog_summary(
        context=context,
        response_preferences=response_preferences,
        snapshot=snapshot,
        entity_type=arguments["entity_type"],
        query=arguments["query"],
        match_slugs=[
            match.get("slug")
            for match in result.get("matches") or []
            if isinstance(match, dict) and isinstance(match.get("slug"), str)
        ],
    )
    return result, {
        "phase": "execution",
        "tool": tool_name,
        "status": "completed",
        "summary": summary,
        "arguments": {
            "entity_type": arguments["entity_type"],
            "query": arguments["query"],
            "limit": arguments["limit"],
        },
        "entity_type": arguments["entity_type"],
        "query": arguments["query"],
        "match_count": len(result.get("matches") or []),
        "match_slugs": [
            match.get("slug")
            for match in result.get("matches") or []
            if isinstance(match, dict) and match.get("slug")
        ],
    }, []


def _entity_exists(
    *,
    tool_name: str,
    slug: str,
    context: MatchContext,
    snapshot: CatalogSnapshot,
) -> bool:
    catalog = snapshot.catalogs[context.game]
    if tool_name == "get_champion":
        return slug in catalog.champions_by_slug
    if tool_name == "get_item":
        return slug in catalog.items_by_slug
    return slug in catalog.runes_by_slug


def _entity_exists_for_type(
    *,
    entity_type: str,
    slug: str,
    context: MatchContext,
    snapshot: CatalogSnapshot,
) -> bool:
    catalog = snapshot.catalogs[context.game]
    if entity_type == "champion":
        return slug in catalog.champions_by_slug
    if entity_type == "item":
        return slug in catalog.items_by_slug
    return slug in catalog.runes_by_slug


def _extract_candidate_filters(arguments: dict[str, Any]) -> dict[str, Any]:
    nested_filters = _sanitize_candidate_filters(arguments.get("filters"))
    top_level_filters = _sanitize_candidate_filters(
        {
            key: value
            for key, value in arguments.items()
            if key not in {"game", "entity_type", "raw_name", "filters"}
        }
    )
    merged = dict(nested_filters)
    for key, value in top_level_filters.items():
        existing = merged.get(key)
        if existing is None:
            merged[key] = value
            continue
        if isinstance(existing, list) and isinstance(value, list):
            merged[key] = [*existing, *[item for item in value if item not in existing]][:8]
    return merged


def _sanitize_candidate_filters(raw_filters: Any) -> dict[str, Any]:
    if not isinstance(raw_filters, dict):
        return {}
    allowed_keys = {
        "position",
        "lane",
        "role",
        "class",
        "class_name",
        "category",
        "subtype",
        "path",
        "slot",
        "tag",
        "tags",
        "keyword",
        "keywords",
    }
    sanitized: dict[str, Any] = {}
    for raw_key, raw_value in raw_filters.items():
        key = str(raw_key).strip().lower()
        if key not in allowed_keys:
            continue
        canonical_key = "keywords" if key in {"tag", "tags"} else key
        if isinstance(raw_value, str):
            cleaned = " ".join(raw_value.split())[:60]
            if cleaned:
                sanitized[canonical_key] = cleaned
            continue
        if isinstance(raw_value, list):
            cleaned_items = [
                " ".join(str(item).split())[:60]
                for item in raw_value[:8]
                if isinstance(item, str) and item.strip()
            ]
            if cleaned_items:
                sanitized[canonical_key] = cleaned_items
    return sanitized


def _clean_tool_text_or_list(value: Any) -> str | list[str] | None:
    if isinstance(value, str):
        cleaned = " ".join(value.split())[:60]
        return cleaned or None
    if isinstance(value, list):
        cleaned_items = [
            " ".join(str(item).split())[:60]
            for item in value[:8]
            if isinstance(item, str) and item.strip()
        ]
        return cleaned_items or None
    return None


def _tool_call_key(tool_name: str, arguments: dict[str, Any]) -> str:
    return json.dumps(
        {"tool_name": tool_name, "arguments": arguments},
        ensure_ascii=False,
        sort_keys=True,
    )


def _loaded_single_entity_summary(
    *,
    context: MatchContext,
    response_preferences: ResponsePreferences,
    snapshot: CatalogSnapshot,
    entity_type: str,
    slug: str,
) -> str:
    entity_name = _preferred_entity_name(
        context=context,
        response_preferences=response_preferences,
        snapshot=snapshot,
        slug=slug,
    )
    if _is_zh_output(response_preferences):
        return f"读取{_entity_type_label(entity_type, zh=True)}数据：{entity_name}。"
    return f"Loaded {_entity_type_label(entity_type, zh=False)} facts for {entity_name}."


def _loaded_batch_entities_summary(
    *,
    context: MatchContext,
    response_preferences: ResponsePreferences,
    snapshot: CatalogSnapshot,
    entity_type: str,
    slugs: list[str],
    missing_slugs: list[str],
) -> str:
    names = [
        _preferred_entity_name(
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
            slug=slug,
        )
        for slug in slugs
    ]
    if _is_zh_output(response_preferences):
        summary = (
            f"读取{_entity_type_label(entity_type, zh=True)}数据："
            f"{_format_entity_name_list(names, entity_type=entity_type, zh=True)}。"
        )
        if missing_slugs:
            summary += f" 未命中 {len(missing_slugs)} 个候选。"
        return summary
    summary = (
        f"Loaded {_entity_type_label(entity_type, zh=False)} facts for "
        f"{_format_entity_name_list(names, entity_type=entity_type, zh=False)}."
    )
    if missing_slugs:
        summary += f" {len(missing_slugs)} candidates were not found."
    return summary


def _listed_candidates_summary(
    *,
    context: MatchContext,
    response_preferences: ResponsePreferences,
    snapshot: CatalogSnapshot,
    entity_type: str,
    filters: dict[str, Any],
    candidate_slugs: list[str],
    candidate_count: int,
) -> str:
    names = [
        _preferred_entity_name(
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
            slug=slug,
        )
        for slug in candidate_slugs[:4]
    ]
    filter_text = _filters_text(filters)
    if _is_zh_output(response_preferences):
        summary = (
            f"按筛选条件列出 {candidate_count} 个{_entity_type_label(entity_type, zh=True)}候选"
        )
        if filter_text:
            summary += f"（{filter_text}）"
        if names:
            summary += f"：{_format_entity_name_list(names, entity_type=entity_type, zh=True)}。"
        else:
            summary += "。"
        return summary
    summary = (
        f"Listed {candidate_count} filtered "
        f"{_entity_type_label(entity_type, zh=False)} candidates"
    )
    if filter_text:
        summary += f" ({filter_text})"
    if names:
        summary += (
            f": {_format_entity_name_list(names, entity_type=entity_type, zh=False)}."
        )
    else:
        summary += "."
    return summary


def _resolved_slug_summary(
    *,
    context: MatchContext,
    response_preferences: ResponsePreferences,
    snapshot: CatalogSnapshot,
    entity_type: str,
    raw_name: str,
    resolved_slug: str | None,
    resolution_status: str | None,
    candidate_slugs: list[str],
) -> str:
    if resolved_slug:
        entity_name = _preferred_entity_name(
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
            slug=resolved_slug,
        )
        if _is_zh_output(response_preferences):
            return (
                f"将 “{raw_name}” 解析为"
                f"{_entity_type_label(entity_type, zh=True)}：{entity_name}。"
            )
        return (
            f"Resolved “{raw_name}” to the "
            f"{_entity_type_label(entity_type, zh=False)} {entity_name}."
        )
    names = [
        _preferred_entity_name(
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
            slug=slug,
        )
        for slug in candidate_slugs[:4]
    ]
    if _is_zh_output(response_preferences):
        if names:
            return (
                f"尝试解析 “{raw_name}”，当前接近的"
                f"{_entity_type_label(entity_type, zh=True)}候选有："
                f"{_format_entity_name_list(names, entity_type=entity_type, zh=True)}。"
            )
        return f"暂时无法稳定解析 “{raw_name}”。"
    if names:
        return (
            f"Tried to resolve “{raw_name}”. Closest {_entity_type_label(entity_type, zh=False)} "
            f"candidates: {_format_entity_name_list(names, entity_type=entity_type, zh=False)}."
        )
    return (
        f"Could not confidently resolve “{raw_name}” yet"
        + (f" ({resolution_status})." if resolution_status else ".")
    )


def _search_catalog_summary(
    *,
    context: MatchContext,
    response_preferences: ResponsePreferences,
    snapshot: CatalogSnapshot,
    entity_type: str,
    query: str,
    match_slugs: list[str],
) -> str:
    names = [
        _preferred_entity_name(
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
            slug=slug,
        )
        for slug in match_slugs[:4]
    ]
    if _is_zh_output(response_preferences):
        if names:
            return (
                f"搜索{_entity_type_label(entity_type, zh=True)}目录“{query}”，找到："
                f"{_format_entity_name_list(names, entity_type=entity_type, zh=True)}。"
            )
        return f"搜索{_entity_type_label(entity_type, zh=True)}目录“{query}”，暂时没有命中。"
    if names:
        return (
            f"Searched the {_entity_type_label(entity_type, zh=False)} catalog for “{query}” "
            f"and found {_format_entity_name_list(names, entity_type=entity_type, zh=False)}."
        )
    return (
        f"Searched the {_entity_type_label(entity_type, zh=False)} catalog for “{query}” "
        "but found no close matches."
    )


def _listed_item_ids_summary(
    *,
    context: MatchContext,
    response_preferences: ResponsePreferences,
    snapshot: CatalogSnapshot,
    requested_categories: list[str],
    item_slugs: list[str],
) -> str:
    names = [
        _preferred_entity_name(
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
            slug=slug,
        )
        for slug in item_slugs[:6]
    ]
    category_text = ", ".join(requested_categories) if requested_categories else "all"
    if _is_zh_output(response_preferences):
        if names:
            return (
                f"列出装备类别“{category_text}”的真实 ID，包含："
                f"{_format_entity_name_list(names, entity_type='item', zh=True)}。"
            )
        return f"装备类别“{category_text}”下暂时没有匹配的装备 ID。"
    if names:
        return (
            f"Listed real item IDs for category “{category_text}”: "
            f"{_format_entity_name_list(names, entity_type='item', zh=False)}."
        )
    return f"No item IDs matched category “{category_text}”."


def _preferred_entity_name(
    *,
    context: MatchContext,
    response_preferences: ResponsePreferences,
    snapshot: CatalogSnapshot,
    slug: str,
) -> str:
    catalog = snapshot.catalogs[context.game]
    entity = (
        catalog.champions_by_slug.get(slug)
        or catalog.items_by_slug.get(slug)
        or catalog.runes_by_slug.get(slug)
    )
    if entity is None:
        return slug
    return entity.preferred_name(
        response_preferences.language,
        response_preferences.terminology_style,
    )


def _format_entity_name_list(names: list[str], *, entity_type: str, zh: bool) -> str:
    unique_names = [name for index, name in enumerate(names) if name and name not in names[:index]]
    if not unique_names:
        return _entity_type_label(entity_type, zh=zh)
    if zh:
        if len(unique_names) <= 4:
            return "、".join(unique_names)
        return (
            f"{'、'.join(unique_names[:4])} 等{len(unique_names)}个"
            f"{_entity_type_label(entity_type, zh=True)}"
        )
    if len(unique_names) == 1:
        return unique_names[0]
    if len(unique_names) == 2:
        return f"{unique_names[0]} and {unique_names[1]}"
    if len(unique_names) <= 4:
        return ", ".join(unique_names[:-1]) + f", and {unique_names[-1]}"
    return (
        ", ".join(unique_names[:4])
        + f", and {len(unique_names) - 4} more "
        + f"{_entity_type_label(entity_type, zh=False)}s"
    )


def _entity_type_label(entity_type: str, *, zh: bool) -> str:
    if zh:
        return {"champion": "英雄", "item": "装备", "rune": "符文"}.get(entity_type, "数据")
    return entity_type


def _filters_text(filters: dict[str, Any]) -> str:
    if not filters:
        return ""
    parts: list[str] = []
    for key, value in filters.items():
        if isinstance(value, list):
            parts.append(f"{key}={', '.join(str(item) for item in value)}")
        else:
            parts.append(f"{key}={value}")
    return "; ".join(parts[:3])


def _is_zh_output(response_preferences: ResponsePreferences) -> bool:
    return response_preferences.language.value.startswith("zh")


def _extract_validation_errors(exc: ApiError) -> list[str]:
    issues = exc.details.get("issues") if exc.details else None
    if not issues:
        return [str(exc)]
    messages: list[str] = []
    for issue in issues:
        if isinstance(issue, dict):
            location = ".".join(str(part) for part in issue.get("loc") or [])
            message = str(issue.get("msg") or issue)
            messages.append(f"{location}: {message}" if location else message)
        else:
            messages.append(str(issue))
    return messages or [str(exc)]


def _tool_decision_summary(reason: str) -> str:
    if reason == "baseline_is_sufficient":
        return "Injected context and baseline were enough, so no extra tool calls were needed."
    if reason == "injected_context_is_sufficient":
        return "Injected match context was already sufficient, so generation can start directly."
    if reason == "tool_round_limit_reached":
        return "Tool round limit reached. Proceeding with the facts already collected."
    if reason == "tool_call_limit_reached":
        return "Tool call limit reached. Proceeding with the facts already collected."
    return "No additional tool calls were needed before generation."


def _tool_plan_summary(
    *,
    reasoning_summary: str,
    tool_calls: list[dict[str, Any]],
    done: bool,
) -> str:
    cleaned = " ".join(reasoning_summary.split())
    if cleaned:
        return cleaned[:280]
    if done:
        return (
            "Current injected context and gathered facts are enough. "
            "Moving on to answer generation."
        )
    tool_names = ", ".join(tool_call["tool_name"] for tool_call in tool_calls) or "no tools"
    return f"Need a little more grounded data before answering. Next tool calls: {tool_names}."


def _aggregate_provider_usage(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    aggregate = {
        "provider_name": None,
        "model_name": None,
        "tokens_input": None,
        "tokens_output": None,
        "latency_ms": None,
        "cost_usd": None,
    }
    for payload in payloads:
        if payload.get("provider_name"):
            aggregate["provider_name"] = payload["provider_name"]
        if payload.get("model_name"):
            aggregate["model_name"] = payload["model_name"]
        if payload.get("tokens_input") is not None:
            aggregate["tokens_input"] = (aggregate["tokens_input"] or 0) + payload["tokens_input"]
        if payload.get("tokens_output") is not None:
            aggregate["tokens_output"] = (
                (aggregate["tokens_output"] or 0) + payload["tokens_output"]
            )
        if payload.get("latency_ms") is not None:
            aggregate["latency_ms"] = (aggregate["latency_ms"] or 0) + payload["latency_ms"]
        if payload.get("cost_usd") is not None:
            aggregate["cost_usd"] = (aggregate["cost_usd"] or 0) + payload["cost_usd"]
    return aggregate


def _temperature_for_run_type(run_type: RunType) -> float:
    if run_type == RunType.CHAT_FOLLOWUP:
        return 0.35
    if run_type in {RunType.RECOMMEND_FULL_BUILD, RunType.RECOMMEND_SLOT}:
        return 0.2
    return 0.15
