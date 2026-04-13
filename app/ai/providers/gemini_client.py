import logging
import time

import httpx

from app.ai.providers.base import BaseLLMClient, LLMResult, LLMUsage
from app.core.config import get_settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAYS = [5, 15, 30]  # seconds


class GeminiClient(BaseLLMClient):
    provider_name = "google"

    def __init__(self, model_name: str, api_key: str) -> None:
        super().__init__(model_name)
        self.api_key = api_key

    def generate_text(self, *, prompt: str, system_prompt: str | None = None) -> LLMResult:
        settings = get_settings()
        debug = settings.debug_llm

        started_at = time.perf_counter()
        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": system_prompt}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent"

        if debug:
            print("\n" + "=" * 80)
            print(f"[DEBUG_LLM] REQUEST to {self.model_name}")
            print(f"[DEBUG_LLM] URL: {url}")
            print(f"[DEBUG_LLM] PROMPT ({len(prompt)} chars):")
            print(prompt[:2000] + ("..." if len(prompt) > 2000 else ""))
            print("=" * 80)

        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                response = httpx.post(
                    url,
                    params={"key": self.api_key},
                    json={"contents": contents},
                    timeout=60.0,
                )
                if response.status_code == 429:
                    delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                    logger.warning(
                        f"Gemini 429 rate limited (attempt {attempt + 1}/{MAX_RETRIES}), "
                        f"retrying in {delay}s..."
                    )
                    if debug:
                        print(f"[DEBUG_LLM] 429 RATE LIMITED — waiting {delay}s before retry {attempt + 2}...")
                    time.sleep(delay)
                    last_error = httpx.HTTPStatusError(
                        f"429 Too Many Requests", request=response.request, response=response
                    )
                    continue
                response.raise_for_status()
                break
            except httpx.HTTPStatusError as e:
                if e.response.status_code != 429:
                    if debug:
                        print(f"[DEBUG_LLM] HTTP ERROR: {e.response.status_code} {e.response.text[:500]}")
                    raise
                last_error = e
                delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                logger.warning(
                    f"Gemini 429 rate limited (attempt {attempt + 1}/{MAX_RETRIES}), "
                    f"retrying in {delay}s..."
                )
                if debug:
                    print(f"[DEBUG_LLM] 429 RATE LIMITED — waiting {delay}s before retry {attempt + 2}...")
                time.sleep(delay)
        else:
            if debug:
                print(f"[DEBUG_LLM] FAILED after {MAX_RETRIES} retries due to rate limiting.")
            raise last_error  # type: ignore[misc]

        payload = response.json()
        candidates = payload.get("candidates", [])
        if not candidates:
            if debug:
                print(f"[DEBUG_LLM] ERROR: No candidates returned. Full payload: {payload}")
            raise ValueError("Gemini returned no candidates.")

        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts).strip()
        usage_payload = payload.get("usageMetadata", {})
        usage = LLMUsage(
            input_tokens=usage_payload.get("promptTokenCount"),
            output_tokens=usage_payload.get("candidatesTokenCount"),
            latency_ms=round((time.perf_counter() - started_at) * 1000),
        )

        if debug:
            print("\n" + "-" * 80)
            print(f"[DEBUG_LLM] RESPONSE from {self.model_name}")
            print(f"[DEBUG_LLM] Tokens: in={usage.input_tokens}, out={usage.output_tokens}, latency={usage.latency_ms}ms")
            print(f"[DEBUG_LLM] OUTPUT ({len(text)} chars):")
            print(text[:3000] + ("..." if len(text) > 3000 else ""))
            print("-" * 80 + "\n")

        return LLMResult(
            text=text,
            usage=usage,
            provider_name=self.provider_name,
            model_name=self.model_name,
        )

