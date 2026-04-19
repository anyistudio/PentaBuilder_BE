from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from app.core.config import BASE_DIR
from app.core.request_context import get_request_id

LLM_DEBUG_LOG_DIR = BASE_DIR / "log"
LEGACY_LLM_DEBUG_LOG_PATH = BASE_DIR / "debug_llm.log"
LLM_DEBUG_LOG_TIMEZONE = ZoneInfo("America/Chicago")
DETAIL_SECTION_KEYS = {
    "system_prompt",
    "prompt",
    "output_text",
    "usage",
    "error",
    "result_payload",
    "response_schema",
    "request_payload",
    "response_payload",
}

_LLM_DEBUG_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar(
    "llm_debug_context",
    default=None,
)
_LLM_DEBUG_LOCK = Lock()


def get_llm_debug_context() -> dict[str, Any]:
    return dict(_LLM_DEBUG_CONTEXT.get() or {})


@contextmanager
def llm_debug_scope(**updates: Any) -> Iterator[dict[str, Any]]:
    current = get_llm_debug_context()
    merged = {
        **current,
        **{key: value for key, value in updates.items() if value is not None},
    }
    token = _LLM_DEBUG_CONTEXT.set(merged)
    try:
        yield merged
    finally:
        _LLM_DEBUG_CONTEXT.reset(token)


def append_llm_debug_log(event: str, **payload: Any) -> None:
    record: dict[str, Any] = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "event": event,
        **get_llm_debug_context(),
    }
    request_id = get_request_id()
    if request_id:
        record["request_id"] = request_id
    record.update(
        {
            key: _normalize_debug_value(value)
            for key, value in payload.items()
            if value is not None
        }
    )

    log_path = _resolve_log_path(record)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with _LLM_DEBUG_LOCK:
        file_has_content = log_path.exists() and log_path.stat().st_size > 0
        with log_path.open("a", encoding="utf-8") as handle:
            if file_has_content:
                handle.write("\n\n")
            handle.write(_format_debug_record(record))


def clear_llm_debug_log() -> dict[str, Any]:
    log_dir = Path(LLM_DEBUG_LOG_DIR)
    legacy_log_path = Path(LEGACY_LLM_DEBUG_LOG_PATH)
    with _LLM_DEBUG_LOCK:
        existed = False
        bytes_removed = 0
        files_removed = 0

        if log_dir.exists():
            for log_path in sorted(log_dir.glob("*.log")):
                if not log_path.is_file():
                    continue
                existed = True
                files_removed += 1
                bytes_removed += log_path.stat().st_size
                log_path.unlink()

        if legacy_log_path.exists():
            existed = True
            files_removed += 1
            bytes_removed += legacy_log_path.stat().st_size
            legacy_log_path.unlink()

        log_dir.mkdir(parents=True, exist_ok=True)
    return {
        "cleared": True,
        "existed": existed,
        "bytes_removed": bytes_removed,
        "files_removed": files_removed,
        "log_path": str(log_dir),
    }


def usage_to_payload(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    if is_dataclass(usage):
        return asdict(usage)
    if isinstance(usage, dict):
        return {key: _normalize_debug_value(value) for key, value in usage.items()}
    payload: dict[str, Any] = {}
    for key in ("input_tokens", "output_tokens", "cost_usd", "latency_ms"):
        value = getattr(usage, key, None)
        if value is not None:
            payload[key] = value
    return payload or None


def _normalize_debug_value(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _normalize_debug_value(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _normalize_debug_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_debug_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _format_debug_record(record: dict[str, Any]) -> str:
    sections = dict(record)
    timestamp = str(sections.pop("timestamp", ""))
    event = str(sections.pop("event", ""))

    lines = [
        "=" * 100,
        f"LLM Debug Event: {event}",
        f"Timestamp: {timestamp}",
    ]

    metadata_lines = _format_metadata_lines(sections)
    if metadata_lines:
        lines.append("")
        lines.append("## Metadata")
        lines.extend(metadata_lines)

    section_specs = [
        ("system_prompt", "System Prompt"),
        ("prompt", "Prompt"),
        ("output_text", "Output Text"),
        ("usage", "Usage"),
        ("error", "Error"),
        ("result_payload", "Result Payload"),
        ("response_schema", "Response Schema"),
        ("request_payload", "Request Payload"),
        ("response_payload", "Response Payload"),
    ]
    for key, title in section_specs:
        if key not in sections:
            continue
        value = sections.pop(key)
        lines.append("")
        lines.append(f"## {title}")
        lines.extend(_render_block(value, indent=0))

    if sections:
        lines.append("")
        lines.append("## Extra")
        lines.extend(_render_mapping(sections, indent=0))

    lines.append("=" * 100)
    return "\n".join(lines) + "\n"


def _format_metadata_lines(record: dict[str, Any]) -> list[str]:
    lines: list[str] = []

    record.pop("log_file_name", None)

    request_id = record.pop("request_id", None)
    if request_id:
        lines.append(f"- Request ID: {request_id}")

    http_method = record.pop("http_method", None)
    api_path = record.pop("api_path", None)
    api_endpoint = record.pop("api_endpoint", None)
    if http_method or api_path:
        api_call = " ".join(part for part in [http_method, api_path] if part)
        lines.append(f"- API Call: {api_call}")
    if api_endpoint and api_endpoint != api_path:
        lines.append(f"- API Endpoint: {api_endpoint}")

    workflow_name = record.pop("workflow_name", None)
    if workflow_name:
        lines.append(f"- Workflow: {workflow_name}")

    execution_mode = record.pop("execution_mode", None)
    if execution_mode:
        lines.append(f"- Execution Mode: {execution_mode}")

    run_type = record.pop("run_type", None)
    if run_type:
        lines.append(f"- Run Type: {run_type}")

    session_id = record.pop("session_id", None)
    if session_id:
        lines.append(f"- Session ID: {session_id}")

    run_id = record.pop("run_id", None)
    if run_id:
        lines.append(f"- Run ID: {run_id}")

    cache_resolution = record.pop("cache_resolution", None)
    if cache_resolution:
        lines.append(f"- Cache Resolution: {cache_resolution}")

    cached_entry_id = record.pop("cached_entry_id", None)
    if cached_entry_id:
        lines.append(f"- Cached Entry ID: {cached_entry_id}")

    graph_node = record.pop("graph_node", None)
    if graph_node:
        lines.append(f"- Graph Node: {graph_node}")

    tool_name = record.pop("tool_name", None)
    if tool_name:
        lines.append(f"- Tool: {tool_name}")

    tool_stage = record.pop("tool_stage", None)
    if tool_stage:
        lines.append(f"- Tool Stage: {tool_stage}")

    job_type = record.pop("job_type", None)
    if job_type:
        lines.append(f"- Job Type: {job_type}")

    provider_name = record.pop("provider_name", None)
    model_name = record.pop("model_name", None)
    if provider_name or model_name:
        model_desc = " / ".join(part for part in [provider_name, model_name] if part)
        lines.append(f"- Model: {model_desc}")

    llm_api_mode = record.pop("llm_api_mode", None)
    if llm_api_mode:
        lines.append(f"- LLM API Mode: {llm_api_mode}")

    llm_api_url = record.pop("llm_api_url", None)
    if llm_api_url:
        lines.append(f"- LLM API URL: {llm_api_url}")

    response_mime_type = record.pop("response_mime_type", None)
    if response_mime_type:
        lines.append(f"- Response MIME Type: {response_mime_type}")

    temperature = record.pop("temperature", None)
    if temperature is not None:
        lines.append(f"- Temperature: {temperature}")

    for key in ("calibration_batch_index", "entity_batch_size"):
        value = record.pop(key, None)
        if value is not None:
            lines.append(f"- {_labelize(key)}: {value}")

    for key in list(record.keys()):
        value = record[key]
        if key in DETAIL_SECTION_KEYS:
            continue
        if _is_inline_value(value):
            lines.append(f"- {_labelize(key)}: {_format_inline_scalar(value)}")
            record.pop(key)

    return lines


def _render_block(value: Any, *, indent: int) -> list[str]:
    if isinstance(value, dict):
        return _render_mapping(value, indent=indent)
    if isinstance(value, (list, tuple)):
        return _render_sequence(value, indent=indent)
    if isinstance(value, str):
        return _render_text(value, indent=indent)
    return [f"{' ' * indent}{_format_inline_scalar(value)}"]


def _render_mapping(value: dict[str, Any], *, indent: int) -> list[str]:
    spaces = " " * indent
    if not value:
        return [f"{spaces}(empty)"]

    lines: list[str] = []
    for key, item in value.items():
        if _is_inline_value(item):
            lines.append(f"{spaces}{key}: {_format_inline_scalar(item)}")
            continue
        lines.append(f"{spaces}{key}:")
        lines.extend(_render_block(item, indent=indent + 2))
    return lines


def _render_sequence(value: list[Any] | tuple[Any, ...], *, indent: int) -> list[str]:
    spaces = " " * indent
    if not value:
        return [f"{spaces}(empty)"]

    lines: list[str] = []
    for index, item in enumerate(value):
        item_label = f"- item[{index}]"
        if _is_inline_value(item):
            lines.append(f"{spaces}{item_label}: {_format_inline_scalar(item)}")
            continue
        lines.append(f"{spaces}{item_label}:")
        lines.extend(_render_block(item, indent=indent + 2))
    return lines


def _render_text(value: str, *, indent: int) -> list[str]:
    spaces = " " * indent
    if value == "":
        return [f"{spaces}(empty)"]
    if "\n" not in value and len(value) <= 160:
        return [f"{spaces}{value}"]
    lines = [f"{spaces}|"]
    for line in value.split("\n"):
        lines.append(f"{spaces}  {line}")
    return lines


def _is_inline_value(value: Any) -> bool:
    if isinstance(value, str):
        return "\n" not in value and len(value) <= 160
    return _is_simple_scalar(value)


def _is_simple_scalar(value: Any) -> bool:
    return isinstance(value, (int, float, bool)) or value is None


def _format_inline_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _labelize(key: str) -> str:
    words = key.split("_")
    return " ".join(word.capitalize() for word in words)


def _resolve_log_path(record: dict[str, Any]) -> Path:
    log_file_name = record.get("log_file_name")
    if isinstance(log_file_name, str) and log_file_name.strip():
        return Path(LLM_DEBUG_LOG_DIR) / _sanitize_log_file_name(log_file_name)

    request_id = record.get("request_id")
    if isinstance(request_id, str) and request_id.strip():
        return Path(LLM_DEBUG_LOG_DIR) / f"request-{_sanitize_log_stem(request_id)}.log"

    return Path(LLM_DEBUG_LOG_DIR) / "misc.log"


def build_run_log_file_name(*, run_id: str, started_at: datetime | str) -> str:
    if isinstance(started_at, str):
        started_at_value = datetime.fromisoformat(started_at)
    else:
        started_at_value = started_at

    if started_at_value.tzinfo is None:
        started_at_value = started_at_value.replace(tzinfo=timezone.utc)
    started_at_value = started_at_value.astimezone(LLM_DEBUG_LOG_TIMEZONE)

    timestamp = started_at_value.strftime("%Y%m%d-%H%M%S-%f")
    run_suffix = _sanitize_log_stem(run_id)[-4:] or "misc"
    return f"{timestamp}-{run_suffix}.log"


def _sanitize_log_stem(value: str) -> str:
    sanitized = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value)
    return sanitized.strip("-_") or "misc"


def _sanitize_log_file_name(value: str) -> str:
    safe_name = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "-"
        for char in value
    ).strip("-_")
    if not safe_name.endswith(".log"):
        safe_name = f"{safe_name}.log"
    return safe_name or "misc.log"
