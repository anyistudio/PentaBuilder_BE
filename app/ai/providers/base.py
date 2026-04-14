from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class LLMUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None


@dataclass
class LLMResult:
    text: str
    usage: LLMUsage
    provider_name: str
    model_name: str


@dataclass
class LLMStreamEvent:
    event_type: Literal["text_delta", "completed"]
    delta: str = ""
    usage: LLMUsage | None = None
    provider_name: str | None = None
    model_name: str | None = None


class BaseLLMClient:
    provider_name = "base"

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def generate_text(
        self,
        *,
        prompt: str,
        system_prompt: str | None = None,
        response_mime_type: str | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> LLMResult:
        del prompt, system_prompt, response_mime_type, response_schema, temperature
        raise NotImplementedError

    def stream_text(
        self,
        *,
        prompt: str,
        system_prompt: str | None = None,
        response_mime_type: str | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> Iterator[LLMStreamEvent]:
        del prompt, system_prompt, response_mime_type, response_schema, temperature
        raise NotImplementedError
