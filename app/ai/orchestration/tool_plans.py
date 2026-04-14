from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.errors import ApiError

ToolName = Literal[
    "get_champion",
    "get_item",
    "get_rune",
    "batch_get_entities",
    "search_catalog",
]


class ToolCallSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tool_name: ToolName
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolSelectionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tool_calls: list[ToolCallSpec] = Field(default_factory=list, max_length=2)
    done: bool = False


def get_tool_plan_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "tool_calls": {
                "type": "array",
                "description": "The next minimal set of tool calls needed for this round.",
                "maxItems": 2,
                "items": {
                    "type": "object",
                    "properties": {
                        "tool_name": {
                            "type": "string",
                            "enum": [
                                "get_champion",
                                "get_item",
                                "get_rune",
                                "batch_get_entities",
                                "search_catalog",
                            ],
                        },
                        "arguments": {
                            "type": "object",
                            "description": "Tool arguments for the selected tool.",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["tool_name", "arguments"],
                    "additionalProperties": False,
                },
            },
            "done": {
                "type": "boolean",
                "description": (
                    "Set to true when the current injected context and tool facts are enough."
                ),
            },
        },
        "required": ["tool_calls", "done"],
        "additionalProperties": False,
    }


def validate_tool_plan(raw_result: dict[str, Any]) -> ToolSelectionResult:
    try:
        return ToolSelectionResult.model_validate(raw_result)
    except ValidationError as exc:
        raise ApiError(
            "Invalid AI tool plan.",
            code="provider_error",
            status_code=502,
            details={"issues": exc.errors()},
        ) from exc
