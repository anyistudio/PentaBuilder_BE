import json
import logging
import time
from collections.abc import Iterator
from typing import Any

import httpx

from app.ai.providers.base import BaseLLMClient, LLMResult, LLMStreamEvent, LLMUsage
from app.core.config import get_settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAYS = [5, 15, 30]  # seconds


class GeminiClient(BaseLLMClient):
    provider_name = "google"

    def __init__(self, model_name: str, api_key: str) -> None:
        super().__init__(model_name)
        self.api_key = api_key

    def generate_text(
        self,
        *,
        prompt: str,
        system_prompt: str | None = None,
        response_mime_type: str | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> LLMResult:
        settings = get_settings()
        debug = settings.debug_llm

        started_at = time.perf_counter()
        payload = self._build_payload(
            prompt=prompt,
            system_prompt=system_prompt,
            response_mime_type=response_mime_type,
            response_schema=response_schema,
            temperature=temperature,
        )
        url = self._generate_url()

        if debug:
            self._debug_request(
                mode="generateContent",
                url=url,
                prompt=prompt,
                system_prompt=system_prompt,
                response_mime_type=response_mime_type,
            )

        response = self._post_with_retries(url=url, payload=payload, debug=debug)
        response_payload = response.json()
        text = self._extract_text(response_payload).strip()
        usage = self._extract_usage(response_payload, started_at=started_at)

        if debug:
            self._debug_response(text=text, usage=usage)

        return LLMResult(
            text=text,
            usage=usage,
            provider_name=self.provider_name,
            model_name=self.model_name,
        )

    def stream_text(
        self,
        *,
        prompt: str,
        system_prompt: str | None = None,
        response_mime_type: str | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> Iterator[LLMStreamEvent]:
        settings = get_settings()
        debug = settings.debug_llm
        started_at = time.perf_counter()
        payload = self._build_payload(
            prompt=prompt,
            system_prompt=system_prompt,
            response_mime_type=response_mime_type,
            response_schema=response_schema,
            temperature=temperature,
        )
        url = self._stream_url()

        if debug:
            self._debug_request(
                mode="streamGenerateContent",
                url=url,
                prompt=prompt,
                system_prompt=system_prompt,
                response_mime_type=response_mime_type,
            )

        usage = LLMUsage(latency_ms=0)
        with httpx.stream(
            "POST",
            url,
            headers=self._headers(),
            json=payload,
            timeout=120.0,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                if isinstance(line, bytes):
                    line = line.decode("utf-8")
                if not line.startswith("data: "):
                    continue
                raw_data = line.removeprefix("data: ").strip()
                if not raw_data or raw_data == "[DONE]":
                    continue
                event_payload = json.loads(raw_data)
                delta = self._extract_text(event_payload)
                usage = self._extract_usage(event_payload, started_at=started_at)
                if delta:
                    yield LLMStreamEvent(event_type="text_delta", delta=delta)

        usage.latency_ms = round((time.perf_counter() - started_at) * 1000)
        yield LLMStreamEvent(
            event_type="completed",
            usage=usage,
            provider_name=self.provider_name,
            model_name=self.model_name,
        )

    def _build_payload(
        self,
        *,
        prompt: str,
        system_prompt: str | None,
        response_mime_type: str | None,
        response_schema: dict[str, Any] | None,
        temperature: float | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        }
        if system_prompt:
            payload["system_instruction"] = {"parts": [{"text": system_prompt}]}

        generation_config: dict[str, Any] = {}
        if response_mime_type:
            generation_config["responseMimeType"] = response_mime_type
        if response_schema:
            generation_config["responseJsonSchema"] = response_schema
        if temperature is not None:
            generation_config["temperature"] = temperature
        if generation_config:
            payload["generationConfig"] = generation_config
        return payload

    def _generate_url(self) -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent"

    def _stream_url(self) -> str:
        return (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model_name}:streamGenerateContent?alt=sse"
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

    def _post_with_retries(
        self,
        *,
        url: str,
        payload: dict[str, Any],
        debug: bool,
    ) -> httpx.Response:
        last_error: httpx.HTTPError | None = None
        for attempt in range(MAX_RETRIES):
            try:
                response = httpx.post(
                    url,
                    headers=self._headers(),
                    json=payload,
                    timeout=120.0,
                )
                if response.status_code == 429:
                    delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                    logger.warning(
                        "Gemini 429 rate limited (attempt %s/%s), retrying in %ss...",
                        attempt + 1,
                        MAX_RETRIES,
                        delay,
                    )
                    if debug:
                        print(
                            "[DEBUG_LLM] 429 RATE LIMITED — "
                            f"waiting {delay}s before retry {attempt + 2}..."
                        )
                    time.sleep(delay)
                    last_error = httpx.HTTPStatusError(
                        "429 Too Many Requests",
                        request=response.request,
                        response=response,
                    )
                    continue
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 429:
                    if debug:
                        print(
                            f"[DEBUG_LLM] HTTP ERROR: {exc.response.status_code} "
                            f"{exc.response.text[:500]}"
                        )
                    raise
                last_error = exc
                delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                logger.warning(
                    "Gemini 429 rate limited (attempt %s/%s), retrying in %ss...",
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                )
                time.sleep(delay)
        if debug:
            print(f"[DEBUG_LLM] FAILED after {MAX_RETRIES} retries due to rate limiting.")
        raise last_error or RuntimeError("Gemini request failed without a response.")

    def _extract_text(self, payload: dict[str, Any]) -> str:
        candidates = payload.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(part.get("text", "") for part in parts if isinstance(part, dict))

    def _extract_usage(self, payload: dict[str, Any], *, started_at: float) -> LLMUsage:
        usage_payload = payload.get("usageMetadata", {})
        return LLMUsage(
            input_tokens=usage_payload.get("promptTokenCount"),
            output_tokens=usage_payload.get("candidatesTokenCount"),
            latency_ms=round((time.perf_counter() - started_at) * 1000),
        )

    def _debug_request(
        self,
        *,
        mode: str,
        url: str,
        prompt: str,
        system_prompt: str | None,
        response_mime_type: str | None,
    ) -> None:
        print("\n" + "=" * 80)
        print(f"[DEBUG_LLM] REQUEST to {self.model_name} ({mode})")
        print(f"[DEBUG_LLM] URL: {url}")
        if response_mime_type:
            print(f"[DEBUG_LLM] RESPONSE MIME TYPE: {response_mime_type}")
        if system_prompt:
            print(f"[DEBUG_LLM] SYSTEM PROMPT ({len(system_prompt)} chars):")
            print(system_prompt[:2000] + ("..." if len(system_prompt) > 2000 else ""))
        print(f"[DEBUG_LLM] USER PROMPT ({len(prompt)} chars):")
        print(prompt[:4000] + ("..." if len(prompt) > 4000 else ""))
        print("=" * 80)

    def _debug_response(self, *, text: str, usage: LLMUsage) -> None:
        print("\n" + "-" * 80)
        print(f"[DEBUG_LLM] RESPONSE from {self.model_name}")
        print(
            "[DEBUG_LLM] Tokens: "
            f"in={usage.input_tokens}, out={usage.output_tokens}, latency={usage.latency_ms}ms"
        )
        print(f"[DEBUG_LLM] OUTPUT ({len(text)} chars):")
        print(text[:3000] + ("..." if len(text) > 3000 else ""))
        print("-" * 80 + "\n")
