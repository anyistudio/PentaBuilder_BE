"""Focused local benchmark helpers for the recommend_full_build workflow."""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker
from tqdm.auto import tqdm

from app.core.config import BASE_DIR, Settings, get_settings
from app.domain.enums import Game, RunType
from app.domain.match_context import MatchContext, ResponsePreferences, build_slot_count_for_game
from app.evals.models import EvalCase, EvalModelRef, parse_model_refs

OUTPUT_TIMEZONE = ZoneInfo("America/Chicago")
DEFAULT_PRICE_FILE_PATH = BASE_DIR / "scripts" / "recommend_full_build_model_prices.json"


def build_recommend_full_build_benchmark_cases(data_version: str) -> list[EvalCase]:
    prefs = ResponsePreferences(language="zh-CN", terminology_style="official")
    return [
        EvalCase(
            case_key="rfb-benchmark-lol-jinx-zero-items-vs-frontline",
            feature=RunType.RECOMMEND_FULL_BUILD,
            description="LoL Jinx starts from zero items into double frontline.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-jinx",
                enemy_slugs=["lol-malphite", "lol-rammus"],
                own_build=_slots(Game.LOL, None, None, None, None, None, None),
                own_runes=_runes(
                    primary=["lol-conqueror", "lol-triumph", "lol-legend-alacrity"],
                    secondary=[],
                ),
                tags=["ranked", "tank-heavy", "cc-heavy"],
            ),
            payload={},
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="rfb-benchmark-lol-ahri-one-item-vs-zed",
            feature=RunType.RECOMMEND_FULL_BUILD,
            description="LoL Ahri has one core item into Zed burst pressure.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-ahri",
                enemy_slugs=["lol-zed"],
                own_build=_slots(Game.LOL, "lol-luden-s-companion", None, None, None, None, None),
                own_runes=_runes(
                    primary=["lol-electrocute", "lol-sudden-impact"],
                    secondary=["lol-manaflow-band", "lol-transcendence"],
                ),
                tags=["ranked", "assassin-heavy"],
            ),
            payload={},
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="rfb-benchmark-lol-orianna-two-items-vs-dive",
            feature=RunType.RECOMMEND_FULL_BUILD,
            description="LoL Orianna already has two items and faces Yone + Vi dive.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-orianna",
                enemy_slugs=["lol-yone", "lol-vi"],
                own_build=_slots(
                    Game.LOL,
                    "lol-luden-s-companion",
                    "lol-zhonya-s-hourglass",
                    None,
                    None,
                    None,
                    None,
                ),
                own_runes=_runes(
                    primary=["lol-electrocute"],
                    secondary=["lol-manaflow-band", "lol-transcendence"],
                ),
                tags=["ranked", "assassin-heavy", "cc-heavy"],
            ),
            payload={},
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="rfb-benchmark-lol-darius-three-items-vs-garen",
            feature=RunType.RECOMMEND_FULL_BUILD,
            description="LoL Darius is three items deep in a bruiser mirror.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-darius",
                enemy_slugs=["lol-garen"],
                own_build=_slots(
                    Game.LOL,
                    "lol-black-cleaver",
                    "lol-plated-steelcaps",
                    "lol-sterak-s-gage",
                    None,
                    None,
                    None,
                ),
                own_runes=_runes(
                    primary=["lol-conqueror", "lol-triumph"],
                    secondary=[],
                ),
                tags=["ranked", "early-game"],
            ),
            payload={},
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="rfb-benchmark-wr-lucian-four-items-vs-ashe",
            feature=RunType.RECOMMEND_FULL_BUILD,
            description="Wild Rift Lucian already has four steps built into Ashe poke.",
            context=_context(
                game=Game.WILD_RIFT,
                data_version=data_version,
                own_champion_slug="wr-lucian",
                enemy_slugs=["wr-ashe"],
                own_build=_slots(
                    Game.WILD_RIFT,
                    "wr-essence-reaver",
                    "wr-gluttonous-greaves",
                    "wr-navori-quickblades",
                    "wr-stasis-enchant",
                    None,
                    None,
                    None,
                ),
                own_runes=_runes(
                    primary=["wr-kraken-slayer", "wr-brutal", "wr-coup-de-grace"],
                    secondary=["wr-bone-plating"],
                ),
                tags=["normal"],
            ),
            payload={},
            response_preferences=prefs,
        ),
    ]


def load_model_refs_from_env_file(
    *,
    env_path: Path | None = None,
    settings: Settings | None = None,
) -> list[EvalModelRef]:
    resolved_settings = settings or get_settings()
    model_args = _read_model_matrix_from_env_file(env_path or (BASE_DIR / ".env"))
    if not model_args:
        model_args = resolved_settings.all_models_list
    if not model_args:
        raise ValueError("No ALL_MODEL or ALL_MODELS entries were found in the backend .env file.")
    return parse_model_refs(model_args, resolved_settings)


def filter_model_refs(
    *,
    model_refs: list[EvalModelRef],
    providers: list[str] | None = None,
    models: list[str] | None = None,
) -> list[EvalModelRef]:
    filtered = model_refs
    provider_filters = _normalize_filter_values(providers)
    if provider_filters:
        filtered = [
            ref for ref in filtered if ref.provider_name.strip().lower() in provider_filters
        ]
        if not filtered:
            requested = ", ".join(sorted(provider_filters))
            available = ", ".join(sorted({ref.provider_name for ref in model_refs}))
            raise ValueError(
                f"No models matched provider filter(s): {requested}. "
                f"Available providers: {available or 'none'}."
            )

    model_filters = _normalize_filter_values(models)
    if model_filters:
        filtered = [
            ref
            for ref in filtered
            if _model_filter_candidates(ref) & model_filters
        ]
        if not filtered:
            requested = ", ".join(sorted(model_filters))
            available = ", ".join(sorted(ref.label for ref in model_refs))
            raise ValueError(
                f"No models matched model filter(s): {requested}. "
                f"Available models: {available or 'none'}."
            )

    return filtered


def sync_model_price_table(
    *,
    model_refs: list[EvalModelRef],
    price_file_path: Path = DEFAULT_PRICE_FILE_PATH,
) -> dict[str, Any]:
    existing = _read_json_file(price_file_path)
    existing_models = existing.get("models", {}) if isinstance(existing, dict) else {}

    # Keep this file as a long-lived registry so filtered benchmark runs
    # cannot accidentally delete prices for models that were filled earlier.
    models_payload: dict[str, Any] = {
        str(label): dict(entry)
        for label, entry in (existing_models.items() if isinstance(existing_models, dict) else [])
        if isinstance(entry, dict)
    }
    for ref in model_refs:
        label = ref.label
        previous = models_payload.get(label, {})
        models_payload[label] = {
            "provider_name": ref.provider_name,
            "model_name": ref.model_name,
            "input_price_per_1m_tokens_usd": previous.get("input_price_per_1m_tokens_usd"),
            "output_price_per_1m_tokens_usd": previous.get("output_price_per_1m_tokens_usd"),
            "notes": previous.get("notes", ""),
        }

    payload = _build_model_price_table_payload(models_payload)
    price_file_path.parent.mkdir(parents=True, exist_ok=True)
    price_file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def build_selected_model_price_table(
    *,
    model_refs: list[EvalModelRef],
    price_table: dict[str, Any],
) -> dict[str, Any]:
    table_models = price_table.get("models", {}) if isinstance(price_table, dict) else {}
    selected_models: dict[str, Any] = {}
    for ref in model_refs:
        existing_entry = table_models.get(ref.label, {}) if isinstance(table_models, dict) else {}
        if not isinstance(existing_entry, dict):
            existing_entry = {}
        selected_models[ref.label] = {
            "provider_name": existing_entry.get("provider_name", ref.provider_name),
            "model_name": existing_entry.get("model_name", ref.model_name),
            "input_price_per_1m_tokens_usd": existing_entry.get("input_price_per_1m_tokens_usd"),
            "output_price_per_1m_tokens_usd": existing_entry.get("output_price_per_1m_tokens_usd"),
            "notes": existing_entry.get("notes", ""),
        }
    return _build_model_price_table_payload(
        selected_models,
        generated_at=(
            price_table.get("generated_at")
            if isinstance(price_table.get("generated_at"), str)
            else None
        ),
    )


def build_default_output_dir(data_version: str) -> Path:
    timestamp = datetime.now(tz=OUTPUT_TIMEZONE).strftime("%Y%m%d_%H%M%S")
    return (
        BASE_DIR
        / "evaluation_reports"
        / f"recommend_full_build_benchmark_{data_version}_{timestamp}"
    )


def run_recommend_full_build_benchmark(
    *,
    session_factory: sessionmaker[Session],
    ai_run_service,
    data_version: str,
    model_refs: list[EvalModelRef],
    output_dir: Path,
    price_file_path: Path = DEFAULT_PRICE_FILE_PATH,
    show_progress: bool = True,
    show_failure_logs: bool = True,
) -> dict[str, Any]:
    cases = build_recommend_full_build_benchmark_cases(data_version)
    price_registry = sync_model_price_table(model_refs=model_refs, price_file_path=price_file_path)
    price_table = build_selected_model_price_table(
        model_refs=model_refs,
        price_table=price_registry,
    )

    results: list[dict[str, Any]] = []
    work_items = list(product(model_refs, cases))
    progress = tqdm(
        work_items,
        total=len(work_items),
        desc="recommend_full_build benchmark",
        unit="run",
        disable=(not show_progress) or (not sys.stderr.isatty()),
    )
    for model_ref, case in progress:
        progress.set_postfix_str(f"{model_ref.label} · {case.case_key}")
        record = _run_one_case(
            session_factory=session_factory,
            ai_run_service=ai_run_service,
            case=case,
            model_ref=model_ref,
            price_table=price_table,
        )
        results.append(record)
        if show_failure_logs and record.get("status") == "failed":
            tqdm.write(
                "[FAILED] "
                f"{record['model_label']} · {record['case_key']} · "
                f"{record.get('error_summary') or record.get('error') or 'Unknown error'}"
            )

    report = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "data_version": data_version,
        "feature": RunType.RECOMMEND_FULL_BUILD.value,
        "case_count": len(cases),
        "model_count": len(model_refs),
        "models": [
            {
                "provider_name": ref.provider_name,
                "model_name": ref.model_name,
                "label": ref.label,
            }
            for ref in model_refs
        ],
        "price_file_path": str(price_file_path),
        "summary": _summarize_results(results),
        "results": results,
    }
    output_paths = _write_benchmark_artifacts(
        report=report,
        cases=cases,
        output_dir=output_dir,
        price_table=price_table,
    )
    return {
        "report": report,
        "cases": cases,
        "price_registry": price_registry,
        "price_table": price_table,
        "output_paths": output_paths,
    }


def render_recommend_full_build_benchmark_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Recommend Full Build Benchmark",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Data version: `{report['data_version']}`",
        f"- Models: {', '.join(model['label'] for model in report['models'])}",
        f"- Cases: `{report['case_count']}`",
        f"- Price file: `{report['price_file_path']}`",
        "",
        "## Summary by Model",
        "",
        (
            "| Model | Success | Avg elapsed (ms) | Avg run latency (ms) | "
            "Avg input | Avg output | Provider cost total | Estimated cost total |"
        ),
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for summary in report["summary"]["model_summaries"]:
        lines.append(
            f"| `{summary['model_label']}` | "
            f"{summary['completed_count']}/{summary['total_count']} | "
            f"{_display_number(summary['avg_total_elapsed_ms'])} | "
            f"{_display_number(summary['avg_run_latency_ms'])} | "
            f"{_display_number(summary['avg_tokens_input'])} | "
            f"{_display_number(summary['avg_tokens_output'])} | "
            f"{_display_currency(summary['provider_cost_total_usd'])} | "
            f"{_display_currency(summary['estimated_cost_total_usd'])} |"
        )

    lines.extend(["", "## Per Case Results", ""])
    for record in report["results"]:
        lines.extend(
            [
                f"### `{record['case_key']}` · `{record['model_label']}`",
                "",
                f"- Description: {record['description']}",
                f"- Owned item count: `{record['owned_item_count']}`",
                f"- Status: `{record['status']}`",
                f"- Total elapsed: `{record.get('total_elapsed_ms')}` ms",
                f"- Run latency: `{record.get('run_latency_ms')}` ms",
                (
                    f"- Tokens in/out: `{record.get('tokens_input')}` / "
                    f"`{record.get('tokens_output')}`"
                ),
                f"- Provider cost: `{record.get('provider_cost_usd')}`",
                (
                    "- Estimated cost from price table: "
                    f"`{record.get('estimated_cost_from_price_table_usd')}`"
                ),
                "",
                "**Generated Content**",
                "",
                "```json",
                json.dumps(record.get("generated_content"), ensure_ascii=False, indent=2),
                "```",
                "",
                "**Explanation**",
                "",
                "```text",
                record.get("explanation") or "",
                "```",
                "",
            ]
        )
        if record.get("error"):
            lines.extend(["**Failure Details**", ""])
            if record.get("error_summary"):
                lines.append(f"- Failure summary: `{record['error_summary']}`")
            if record.get("error_code"):
                lines.append(f"- Error code: `{record['error_code']}`")
            if record.get("error_status_code") is not None:
                lines.append(f"- Status code: `{record['error_status_code']}`")
            lines.append(f"- Error message: `{record['error']}`")
            if record.get("run_error_code"):
                lines.append(f"- Stored run error code: `{record['run_error_code']}`")
            if record.get("run_error_message"):
                lines.append(f"- Stored run error message: `{record['run_error_message']}`")
            lines.append("")
            if record.get("error_issues"):
                lines.extend(
                    [
                        "**Issue Breakdown**",
                        "",
                        "```text",
                        "\n".join(str(item) for item in record["error_issues"]),
                        "```",
                        "",
                    ]
                )
            if record.get("error_details") is not None:
                lines.extend(
                    [
                        "**Raw Error Details**",
                        "",
                        "```json",
                        json.dumps(record["error_details"], ensure_ascii=False, indent=2),
                        "```",
                        "",
                    ]
                )

    return "\n".join(lines)


def _run_one_case(
    *,
    session_factory: sessionmaker[Session],
    ai_run_service,
    case: EvalCase,
    model_ref: EvalModelRef,
    price_table: dict[str, Any],
) -> dict[str, Any]:
    run = None
    payload = dict(case.payload)
    started_at = time.perf_counter()

    with session_factory() as session:
        try:
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
            total_elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
            estimated_cost = _estimate_cost_from_price_table(
                model_label=model_ref.label,
                tokens_input=run.tokens_input,
                tokens_output=run.tokens_output,
                price_table=price_table,
            )
            return {
                "case_key": case.case_key,
                "description": case.description,
                "feature": case.feature.value,
                "provider_name": model_ref.provider_name,
                "model_name": model_ref.model_name,
                "model_label": model_ref.label,
                "run_id": str(run.id),
                "status": run.status,
                "owned_item_count": _owned_item_count(case.context),
                "context": case.context.model_dump(mode="json"),
                "payload": payload,
                "total_elapsed_ms": total_elapsed_ms,
                "run_latency_ms": run.latency_ms,
                "tokens_input": run.tokens_input,
                "tokens_output": run.tokens_output,
                "provider_cost_usd": float(run.cost_usd) if run.cost_usd is not None else None,
                "estimated_cost_from_price_table_usd": estimated_cost,
                "generated_content": _extract_generated_content(result),
                "explanation": str(result.get("summary") or ""),
                "raw_result": result,
            }
        except Exception as exc:
            session.rollback()
            return {
                "case_key": case.case_key,
                "description": case.description,
                "feature": case.feature.value,
                "provider_name": model_ref.provider_name,
                "model_name": model_ref.model_name,
                "model_label": model_ref.label,
                "run_id": str(run.id) if run is not None else None,
                "status": "failed",
                "owned_item_count": _owned_item_count(case.context),
                "context": case.context.model_dump(mode="json"),
                "payload": payload,
                "total_elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                "run_latency_ms": getattr(run, "latency_ms", None),
                "tokens_input": getattr(run, "tokens_input", None),
                "tokens_output": getattr(run, "tokens_output", None),
                "provider_cost_usd": None,
                "estimated_cost_from_price_table_usd": None,
                "generated_content": None,
                "explanation": "",
                "raw_result": None,
                **_build_failure_error_payload(exc=exc, run=run),
            }


def _summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in results:
        grouped.setdefault(record["model_label"], []).append(record)

    model_summaries: list[dict[str, Any]] = []
    for model_label, records in sorted(grouped.items()):
        completed = [record for record in records if record["status"] == "completed"]
        model_summaries.append(
            {
                "model_label": model_label,
                "total_count": len(records),
                "completed_count": len(completed),
                "avg_total_elapsed_ms": _avg(record["total_elapsed_ms"] for record in completed),
                "avg_run_latency_ms": _avg(record["run_latency_ms"] for record in completed),
                "avg_tokens_input": _avg(record["tokens_input"] for record in completed),
                "avg_tokens_output": _avg(record["tokens_output"] for record in completed),
                "provider_cost_total_usd": _sum(
                    record["provider_cost_usd"] for record in completed
                ),
                "estimated_cost_total_usd": _sum(
                    record["estimated_cost_from_price_table_usd"] for record in completed
                ),
            }
        )
    return {"model_summaries": model_summaries}


def _write_benchmark_artifacts(
    *,
    report: dict[str, Any],
    cases: list[EvalCase],
    output_dir: Path,
    price_table: dict[str, Any],
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "report.json"
    markdown_path = output_dir / "report.md"
    cases_path = output_dir / "cases.json"
    price_snapshot_path = output_dir / "model_prices_snapshot.json"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(
        render_recommend_full_build_benchmark_markdown(report),
        encoding="utf-8",
    )
    cases_path.write_text(
        json.dumps(
            [
                {
                    "case_key": case.case_key,
                    "description": case.description,
                    "owned_item_count": _owned_item_count(case.context),
                    "context": case.context.model_dump(mode="json"),
                    "payload": case.payload,
                }
                for case in cases
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    price_snapshot_path.write_text(
        json.dumps(price_table, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "output_dir": str(output_dir),
        "report_json": str(json_path),
        "report_markdown": str(markdown_path),
        "cases_json": str(cases_path),
        "price_snapshot_json": str(price_snapshot_path),
    }


def _extract_generated_content(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "recommended_build_order": result.get("recommended_build_order")
        or result.get("recommended_build"),
        "recommended_runes": result.get("recommended_runes"),
        "slot_notes": result.get("slot_notes"),
    }


def _estimate_cost_from_price_table(
    *,
    model_label: str,
    tokens_input: int | None,
    tokens_output: int | None,
    price_table: dict[str, Any],
) -> float | None:
    if tokens_input is None or tokens_output is None:
        return None
    model_entry = (price_table.get("models") or {}).get(model_label)
    if not isinstance(model_entry, dict):
        return None
    input_price = model_entry.get("input_price_per_1m_tokens_usd")
    output_price = model_entry.get("output_price_per_1m_tokens_usd")
    if not isinstance(input_price, (int, float)) or not isinstance(output_price, (int, float)):
        return None
    return round(
        (tokens_input / 1_000_000) * input_price
        + (tokens_output / 1_000_000) * output_price,
        8,
    )


def _build_failure_error_payload(
    *,
    exc: Exception,
    run,
) -> dict[str, Any]:
    details = getattr(exc, "details", None)
    error_issues = _extract_error_issue_messages(details)
    return {
        "error": str(exc),
        "error_summary": error_issues[0] if error_issues else str(exc),
        "error_code": getattr(exc, "code", None) or getattr(run, "error_code", None),
        "error_status_code": getattr(exc, "status_code", None),
        "error_details": _json_safe_error_details(details),
        "error_issues": error_issues,
        "run_error_code": getattr(run, "error_code", None),
        "run_error_message": getattr(run, "error_message", None),
    }


def _read_model_matrix_from_env_file(env_path: Path) -> list[str]:
    if not env_path.exists():
        return []
    parsed: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = _strip_wrapping_quotes(value.strip())

    raw_models = parsed.get("ALL_MODEL") or parsed.get("ALL_MODELS") or ""
    return [item.strip() for item in raw_models.split(",") if item.strip()]


def _normalize_filter_values(raw_values: list[str] | None) -> set[str]:
    return {
        part.strip().lower()
        for raw_value in (raw_values or [])
        for part in raw_value.split(",")
        if part.strip()
    }


def _model_filter_candidates(ref: EvalModelRef) -> set[str]:
    provider = ref.provider_name.strip().lower()
    model = ref.model_name.strip().lower()
    label = ref.label.strip().lower()
    return {
        model,
        label,
        f"{provider}:{model}",
    }


def _extract_error_issue_messages(details: Any) -> list[str]:
    if not isinstance(details, dict):
        return []
    issues = details.get("issues")
    if not isinstance(issues, list):
        return []

    messages: list[str] = []
    for issue in issues:
        if isinstance(issue, dict):
            location = ".".join(str(part) for part in issue.get("loc") or [])
            message = str(issue.get("msg") or issue)
            messages.append(f"{location}: {message}" if location else message)
        else:
            messages.append(str(issue))
    return messages


def _json_safe_error_details(details: Any) -> Any:
    if details is None or isinstance(details, (dict, list, str, int, float, bool)):
        return details
    return str(details)


def _build_model_price_table_payload(
    models_payload: dict[str, Any],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    return {
        "generated_at": generated_at or datetime.now(tz=timezone.utc).isoformat(),
        "currency": "USD",
        "price_unit": "per_1m_tokens",
        "models": {label: models_payload[label] for label in sorted(models_payload)},
    }


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _owned_item_count(context: MatchContext) -> int:
    return sum(1 for slot in context.own_build if slot)


def _avg(values) -> float | None:
    filtered = [value for value in values if isinstance(value, (int, float))]
    if not filtered:
        return None
    return round(sum(filtered) / len(filtered), 2)


def _sum(values) -> float | None:
    filtered = [value for value in values if isinstance(value, (int, float))]
    if not filtered:
        return None
    return round(sum(filtered), 8)


def _display_number(value: float | int | None) -> str:
    if value is None:
        return "-"
    if isinstance(value, int):
        return str(value)
    return f"{value:.2f}"


def _display_currency(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.6f}"


def _context(
    *,
    game: Game,
    data_version: str,
    own_champion_slug: str,
    enemy_slugs: list[str],
    own_build: list[str | None],
    own_runes: dict[str, list[str]],
    tags: list[str],
    free_text: str = "",
) -> MatchContext:
    return MatchContext(
        game=game,
        data_version=data_version,
        own_champion_slug=own_champion_slug,
        enemy_team=[
            {
                "champion_slug": slug,
                "build": [None] * build_slot_count_for_game(game),
                "runes": {"primary": [], "secondary": []},
            }
            for slug in enemy_slugs
        ],
        own_build=own_build,
        own_runes=own_runes,
        environment={"tags": tags, "free_text": free_text},
    )


def _slots(game: Game, *entries: str | None) -> list[str | None]:
    slot_count = build_slot_count_for_game(game)
    if len(entries) != slot_count:
        raise ValueError(f"{game.value} requires exactly {slot_count} slots.")
    return list(entries)


def _runes(*, primary: list[str], secondary: list[str]) -> dict[str, list[str]]:
    return {"primary": primary, "secondary": secondary}
