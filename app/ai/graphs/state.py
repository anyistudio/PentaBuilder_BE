from typing import Any, TypedDict


class RunGraphState(TypedDict, total=False):
    context: dict[str, Any]
    operation_context: dict[str, Any]
    streamed_text: str | None

    tool_round_count: int
    total_tool_calls: int
    tool_trace: list[dict[str, Any]]
    tool_facts: dict[str, list[dict[str, Any]]]
    seen_tool_call_keys: list[str]
    pending_tool_calls: list[dict[str, Any]]
    need_tools: bool
    tool_context_ready: bool
    tool_decision_reason: str | None

    provider_usage_payloads: list[dict[str, Any]]
    prompt: dict[str, Any]
    model_result: dict[str, Any]
    result: dict[str, Any]
    validation_errors: list[str]
    repair_requested: bool
    repair_attempt_count: int
    final_result: dict[str, Any]
