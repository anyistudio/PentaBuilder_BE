from dataclasses import dataclass


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


class BaseLLMClient:
    provider_name = "base"

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def generate_text(self, *, prompt: str, system_prompt: str | None = None) -> LLMResult:
        raise NotImplementedError
