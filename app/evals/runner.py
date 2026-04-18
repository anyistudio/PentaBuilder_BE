"""Eval execution engine: runs cases against models and collects results."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.domain.enums import RunType
from app.domain.match_context import MatchContext
from app.main import create_app

from app.evals.models import EvalCase, EvalModelRef
from app.evals.reporter import build_default_output_path, render_markdown_report
from app.evals.test_cases import build_eval_cases


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_eval_app(*, debug_llm: bool = False) -> FastAPI:
    settings = get_settings()
    settings.debug_llm = debug_llm
    return create_app()


# ---------------------------------------------------------------------------
# Top-level runner
# ---------------------------------------------------------------------------


def run_local_workflow_eval(
    *,
    session_factory: sessionmaker[Session],
    ai_run_service,
    data_version: str,
    model_refs: list[EvalModelRef],
    output_path: Path,
    feature_filter: set[RunType] | None = None,
) -> dict[str, Any]:
    cases = build_eval_cases(data_version)
    if feature_filter:
        cases = [case for case in cases if case.feature in feature_filter]

    results: list[dict[str, Any]] = []
    for model_ref in model_refs:
        for case in cases:
            record = _run_one_case(
                session_factory=session_factory,
                ai_run_service=ai_run_service,
                case=case,
                model_ref=model_ref,
            )
            results.append(record)

    report = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "data_version": data_version,
        "models": [
            {"provider_name": ref.provider_name, "model_name": ref.model_name, "label": ref.label}
            for ref in model_refs
        ],
        "summary": _summarize_results(results),
        "results": results,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_markdown_report(report), encoding="utf-8")
    return report


# ---------------------------------------------------------------------------
# Single-case executor
# ---------------------------------------------------------------------------


def _run_one_case(
    *,
    session_factory: sessionmaker[Session],
    ai_run_service,
    case: EvalCase,
    model_ref: EvalModelRef,
) -> dict[str, Any]:
    payload = dict(case.payload)
    with session_factory() as session:
        try:
            if case.reply_seed is not None:
                seed_run, _ = ai_run_service.create_run(
                    session,
                    user=None,
                    session_id=None,
                    run_type=case.reply_seed.run_type,
                    context=case.context,
                    response_preferences=case.response_preferences,
                    operation_context=dict(case.reply_seed.payload),
                    stream=False,
                    use_cache=False,
                )
                ai_run_service.execute_run(
                    session,
                    run=seed_run,
                    context=case.context,
                    response_preferences=case.response_preferences,
                    operation_context=dict(case.reply_seed.payload),
                    provider_name_override=model_ref.provider_name,
                    model_name_override=model_ref.model_name,
                )
                payload["reply_to_run_id"] = str(seed_run.id)

            run, _ = ai_run_service.create_run(
                session,
                user=None,
                session_id=None,
                run_type=case.feature,
                context=case.context,
                response_preferences=case.response_preferences,
                operation_context=payload,
                stream=False,
                use_cache=False,
            )
            result = ai_run_service.execute_run(
                session,
                run=run,
                context=case.context,
                response_preferences=case.response_preferences,
                operation_context=payload,
                provider_name_override=model_ref.provider_name,
                model_name_override=model_ref.model_name,
            )
            return {
                "case_key": case.case_key,
                "feature": case.feature.value,
                "description": case.description,
                "model_label": model_ref.label,
                "provider_name": model_ref.provider_name,
                "model_name": model_ref.model_name,
                "status": run.status,
                "latency_ms": run.latency_ms,
                "tokens_input": run.tokens_input,
                "tokens_output": run.tokens_output,
                "cost_usd": float(run.cost_usd) if run.cost_usd is not None else None,
                "payload": payload,
                "context_brief": _context_brief(case.context),
                "result": result,
            }
        except Exception as exc:
            session.rollback()
            return {
                "case_key": case.case_key,
                "feature": case.feature.value,
                "description": case.description,
                "model_label": model_ref.label,
                "provider_name": model_ref.provider_name,
                "model_name": model_ref.model_name,
                "status": "failed",
                "latency_ms": None,
                "tokens_input": None,
                "tokens_output": None,
                "cost_usd": None,
                "payload": payload,
                "context_brief": _context_brief(case.context),
                "error": str(exc),
                "result": None,
            }


# ---------------------------------------------------------------------------
# Result aggregation
# ---------------------------------------------------------------------------


def _summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in results:
        grouped.setdefault((record["feature"], record["model_label"]), []).append(record)

    feature_model_summaries: list[dict[str, Any]] = []
    for (feature, model_label), records in sorted(grouped.items()):
        completed = [record for record in records if record["status"] == "completed"]
        latencies = [
            record["latency_ms"] for record in completed if record["latency_ms"] is not None
        ]
        feature_model_summaries.append(
            {
                "feature": feature,
                "model_label": model_label,
                "total_count": len(records),
                "completed_count": len(completed),
                "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else None,
            }
        )
    return {"feature_model_summaries": feature_model_summaries}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _context_brief(context: MatchContext) -> str:
    enemies = ", ".join(enemy.champion_slug for enemy in context.enemy_team) or "none"
    tags = ", ".join(context.environment.tags) or "none"
    return (
        f"game={context.game.value}, own={context.own_champion_slug}, "
        f"enemies={enemies}, tags={tags}"
    )
