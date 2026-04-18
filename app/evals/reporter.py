"""Markdown report rendering for AI workflow evaluations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.domain.enums import RunType


def build_default_output_path(data_version: str) -> Path:
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Path("evaluation_reports") / f"ai_workflow_eval_{data_version}_{timestamp}.md"


def render_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# AI Workflow Evaluation Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Data version: `{report['data_version']}`",
        f"- Models: {', '.join(model['label'] for model in report['models'])}",
        "",
        "## Average Latency by Feature and Model",
        "",
        "| Feature | Model | Success | Avg latency (ms) |",
        "| --- | --- | --- | ---: |",
    ]

    for summary in report["summary"]["feature_model_summaries"]:
        lines.append(
            f"| `{summary['feature']}` | `{summary['model_label']}` | "
            f"{summary['completed_count']}/{summary['total_count']} | "
            f"{summary['avg_latency_ms'] if summary['avg_latency_ms'] is not None else '-'} |"
        )

    lines.extend(["", "## Per Case Results", ""])

    results_by_feature: dict[str, list[dict[str, Any]]] = {}
    for record in report["results"]:
        results_by_feature.setdefault(record["feature"], []).append(record)

    for feature in [run_type.value for run_type in RunType]:
        feature_records = results_by_feature.get(feature, [])
        if not feature_records:
            continue

        lines.extend([f"### `{feature}`", ""])

        cases_by_key: dict[str, list[dict[str, Any]]] = {}
        for record in feature_records:
            cases_by_key.setdefault(record["case_key"], []).append(record)

        for case_key, case_records in cases_by_key.items():
            first = case_records[0]
            lines.extend(
                [
                    f"#### `{case_key}`",
                    "",
                    f"- Description: {first['description']}",
                    f"- Context: {first['context_brief']}",
                    "",
                ]
            )
            if first.get("payload"):
                lines.extend(
                    [
                        "**Payload**",
                        "",
                        "```json",
                        json.dumps(first["payload"], ensure_ascii=False, indent=2),
                        "```",
                        "",
                    ]
                )
            for record in case_records:
                lines.extend(
                    [
                        f"##### `{record['model_label']}`",
                        "",
                        f"- Status: `{record['status']}`",
                        f"- Latency: `{record.get('latency_ms')}` ms",
                        (
                            f"- Tokens in/out: `{record.get('tokens_input')}` / "
                            f"`{record.get('tokens_output')}`"
                        ),
                        "",
                    ]
                )
                if record.get("error"):
                    lines.extend(
                        [
                            "```text",
                            record["error"],
                            "```",
                            "",
                        ]
                    )
                else:
                    lines.extend(
                        [
                            "```json",
                            json.dumps(record.get("result"), ensure_ascii=False, indent=2),
                            "```",
                            "",
                        ]
                    )

    return "\n".join(lines)
