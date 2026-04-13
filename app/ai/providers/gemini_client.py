import time

import httpx

from app.ai.providers.base import BaseLLMClient, LLMResult, LLMUsage


class GeminiClient(BaseLLMClient):
    provider_name = "google"

    def __init__(self, model_name: str, api_key: str) -> None:
        super().__init__(model_name)
        self.api_key = api_key

    def generate_text(self, *, prompt: str, system_prompt: str | None = None) -> LLMResult:
        started_at = time.perf_counter()
        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": system_prompt}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent",
            params={"key": self.api_key},
            json={"contents": contents},
            timeout=30.0,
        )
        response.raise_for_status()
        payload = response.json()
        candidates = payload.get("candidates", [])
        if not candidates:
            raise ValueError("Gemini returned no candidates.")

        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts).strip()
        usage_payload = payload.get("usageMetadata", {})
        usage = LLMUsage(
            input_tokens=usage_payload.get("promptTokenCount"),
            output_tokens=usage_payload.get("candidatesTokenCount"),
            latency_ms=round((time.perf_counter() - started_at) * 1000),
        )
        return LLMResult(
            text=text,
            usage=usage,
            provider_name=self.provider_name,
            model_name=self.model_name,
        )
