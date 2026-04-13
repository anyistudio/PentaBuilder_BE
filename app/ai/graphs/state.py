from typing import Any, TypedDict


class RunGraphState(TypedDict, total=False):
    context: dict[str, Any]
    operation_context: dict[str, Any]
    prompt: str
    result: dict[str, Any]
    reasoning_text: str
