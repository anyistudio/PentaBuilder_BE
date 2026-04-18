import json
import logging
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from functools import lru_cache
from typing import Any

import httpx

from app.ai.providers.base import BaseLLMClient, LLMResult, LLMStreamEvent, LLMUsage
from app.core.config import get_settings
from app.core.errors import IntegrationError

logger = logging.getLogger(__name__)

MAX_RETRIES = 4
RETRY_DELAYS = [1, 2, 4, 8]  # seconds
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}

GEMINI_MODEL_ALIASES = {
    "gemini-3.1-pro": "gemini-3-pro-preview",
    "gemini-3.1-pro-preview": "gemini-3-pro-preview",
}


@lru_cache(maxsize=1)
def _http2_enabled() -> bool:
    try:
        import h2  # noqa: F401
    except ImportError:
        return False
    return True


def normalize_gemini_model_name(model_name: str) -> str:
    return GEMINI_MODEL_ALIASES.get(model_name, model_name)


class GeminiClient(BaseLLMClient):
    provider_name = "google"

    def __init__(self, model_name: str, api_key: str) -> None:
        super().__init__(normalize_gemini_model_name(model_name))
        self.api_key = api_key
        self._client = httpx.Client(
            http2=_http2_enabled(),
            timeout=120.0,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )

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
        try:
            with self._client.stream(
                "POST",
                url,
                headers=self._headers(),
                json=payload,
            ) as response:
                if response.status_code in RETRYABLE_STATUS_CODES:
                    raise self._build_response_error(response, exhausted=False)
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    if debug:
                        print(
                            f"[DEBUG_LLM] HTTP ERROR: {response.status_code} "
                            f"{self._response_excerpt(response)}"
                        )
                    raise self._build_response_error(response, exhausted=False) from exc
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
        except httpx.RequestError as exc:
            raise self._build_request_error(exc, exhausted=False) from exc

        usage.latency_ms = round((time.perf_counter() - started_at) * 1000)
        yield LLMStreamEvent(
            event_type="completed",
            usage=usage,
            provider_name=self.provider_name,
            model_name=self.model_name,
        )

    def close(self) -> None:
        self._client.close()

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
        for attempt in range(MAX_RETRIES):
            try:
                response = self._client.post(
                    url,
                    headers=self._headers(),
                    json=payload,
                )
            except httpx.RequestError as exc:
                if not self._can_retry_attempt(attempt):
                    if debug:
                        print(
                            "[DEBUG_LLM] REQUEST ERROR: "
                            f"{type(exc).__name__} {exc}"
                        )
                    raise self._build_request_error(exc, exhausted=True) from exc
                delay = self._retry_delay(attempt=attempt)
                logger.warning(
                    "Gemini request transport error %s (attempt %s/%s), retrying in %ss...",
                    type(exc).__name__,
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                )
                if debug:
                    print(
                        "[DEBUG_LLM] REQUEST ERROR — "
                        f"{type(exc).__name__}: {exc}. "
                        f"Waiting {delay}s before retry {attempt + 2}..."
                    )
                time.sleep(delay)
                continue

            if response.status_code in RETRYABLE_STATUS_CODES:
                if not self._can_retry_attempt(attempt):
                    if debug:
                        print(
                            "[DEBUG_LLM] RETRYABLE HTTP ERROR EXHAUSTED: "
                            f"{response.status_code} {self._response_excerpt(response)}"
                        )
                    raise self._build_response_error(response, exhausted=True)
                delay = self._retry_delay(attempt=attempt, response=response)
                logger.warning(
                    "Gemini upstream returned %s (attempt %s/%s), retrying in %ss...",
                    response.status_code,
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                )
                if debug:
                    print(
                        "[DEBUG_LLM] RETRYABLE HTTP ERROR — "
                        f"{response.status_code}. Waiting {delay}s before retry {attempt + 2}..."
                    )
                time.sleep(delay)
                continue

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if debug:
                    print(
                        f"[DEBUG_LLM] HTTP ERROR: {exc.response.status_code} "
                        f"{self._response_excerpt(exc.response)}"
                    )
                raise self._build_response_error(exc.response, exhausted=False) from exc
            return response

        raise IntegrationError(
            "Gemini request failed after repeated retries.",
            status_code=503,
            code="provider_unavailable",
            details={
                "provider": self.provider_name,
                "model_name": self.model_name,
                "reason": "retry_loop_exhausted",
            },
        )

    def _can_retry_attempt(self, attempt: int) -> bool:
        return attempt < MAX_RETRIES - 1

    def _retry_delay(self, *, attempt: int, response: httpx.Response | None = None) -> float:
        if response is not None:
            retry_after = self._parse_retry_after(response.headers.get("Retry-After"))
            if retry_after is not None:
                return retry_after
        return RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]

    def _parse_retry_after(self, raw_value: str | None) -> float | None:
        if not raw_value:
            return None
        try:
            return max(0.0, float(raw_value))
        except ValueError:
            pass
        try:
            parsed = parsedate_to_datetime(raw_value)
        except (TypeError, ValueError, OverflowError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return max(0.0, (parsed - datetime.now(tz=UTC)).total_seconds())

    def _build_request_error(
        self,
        exc: httpx.RequestError,
        *,
        exhausted: bool,
    ) -> IntegrationError:
        return IntegrationError(
            (
                "Gemini is temporarily unavailable after multiple attempts."
                if exhausted
                else "Gemini request failed before a response was received."
            ),
            status_code=503,
            code="provider_unavailable",
            details={
                "provider": self.provider_name,
                "model_name": self.model_name,
                "reason": str(exc),
                "request_error_type": type(exc).__name__,
            },
        )

    def _build_response_error(
        self,
        response: httpx.Response,
        *,
        exhausted: bool,
    ) -> IntegrationError:
        status_code = response.status_code
        is_temporary = exhausted or status_code in RETRYABLE_STATUS_CODES
        return IntegrationError(
            (
                f"Gemini is temporarily unavailable (upstream {status_code})."
                if is_temporary
                else f"Gemini request failed with upstream status {status_code}."
            ),
            status_code=503 if is_temporary else 502,
            code="provider_unavailable" if is_temporary else "provider_error",
            details={
                "provider": self.provider_name,
                "model_name": self.model_name,
                "upstream_status_code": status_code,
                "response_excerpt": self._response_excerpt(response),
            },
        )

    def _response_excerpt(self, response: httpx.Response) -> str:
        try:
            text = response.text
        except Exception:
            return ""
        return text[:500]

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
