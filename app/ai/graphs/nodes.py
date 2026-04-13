from collections.abc import Callable
from typing import Any

from app.ai.graphs.validators import validate_run_result
from app.ai.heuristics import generate_run_result
from app.ai.orchestration.prompt_builder import build_prompt
from app.ai.providers.base import BaseLLMClient
from app.catalog.registry import CatalogSnapshot
from app.domain.enums import RunType
from app.domain.match_context import MatchContext, ResponsePreferences


def prepare_context_node(state: dict[str, Any]) -> dict[str, Any]:
    return {"context": state["context"], "operation_context": state.get("operation_context", {})}


def generate_result_node(
    *,
    run_type: RunType,
    context: MatchContext,
    response_preferences: ResponsePreferences,
    snapshot: CatalogSnapshot,
    baseline: dict[str, Any] | None,
    reference_summary: str | None,
    calibration_summary: str | None,
    llm_client: BaseLLMClient | None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _node(state: dict[str, Any]) -> dict[str, Any]:
        operation_context = state.get("operation_context", {})
        prompt = build_prompt(
            run_type=run_type,
            context=context,
            response_preferences=response_preferences,
            operation_context=operation_context,
            baseline_summary=baseline["summary"] if baseline else None,
            reference_summary=reference_summary,
            calibration_summary=calibration_summary,
            snapshot=snapshot,
        )
        heuristic_result = generate_run_result(
            run_type=run_type,
            context=context,
            response_preferences=response_preferences,
            operation_context=operation_context,
            snapshot=snapshot,
            baseline=baseline,
            reference_summary=reference_summary,
            calibration_summary=calibration_summary,
        )
        result = heuristic_result.result
        reasoning_text = heuristic_result.reasoning_text
        if llm_client is not None and run_type in {RunType.EXPLAIN_SLOT, RunType.CHAT_FOLLOWUP}:
            llm_result = llm_client.generate_text(prompt=prompt)
            if llm_result.text:
                result["summary"] = llm_result.text
                reasoning_text = llm_result.text
                result.setdefault("_provider_usage", {})
                result["_provider_usage"] = {
                    "provider_name": llm_result.provider_name,
                    "model_name": llm_result.model_name,
                    "tokens_input": llm_result.usage.input_tokens,
                    "tokens_output": llm_result.usage.output_tokens,
                    "latency_ms": llm_result.usage.latency_ms,
                    "cost_usd": llm_result.usage.cost_usd,
                }
        return {"prompt": prompt, "result": result, "reasoning_text": reasoning_text}

    return _node


def validate_result_node(state: dict[str, Any]) -> dict[str, Any]:
    return {"result": validate_run_result(state["result"])}
