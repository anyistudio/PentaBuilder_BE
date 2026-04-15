import json
import time
from collections.abc import Iterator
from functools import lru_cache
from typing import Any

import httpx

from app.ai.providers.base import BaseLLMClient, LLMResult, LLMStreamEvent, LLMUsage
from app.core.config import get_settings


@lru_cache(maxsize=1)
def _http2_enabled() -> bool:
    try:
        import h2  # noqa: F401
    except ImportError:
        return False
    return True


class OpenAIClient(BaseLLMClient):
    provider_name = "openai"

    def __init__(
        self,
        model_name: str,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        organization_id: str | None = None,
        project_id: str | None = None,
    ) -> None:
        super().__init__(model_name)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.organization_id = organization_id
        self.project_id = project_id
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
        started_at = time.perf_counter()
        payload = self._build_payload(
            prompt=prompt,
            system_prompt=system_prompt,
            response_mime_type=response_mime_type,
            response_schema=response_schema,
            temperature=temperature,
            stream=False,
        )
        url = self._responses_url()

        if settings.debug_llm:
            self._debug_request(
                mode="responses.create",
                url=url,
                prompt=prompt,
                system_prompt=system_prompt,
                response_mime_type=response_mime_type,
            )

        response = self._client.post(
            url,
            headers=self._headers(),
            json=payload,
        )
        self._raise_for_status(response)
        response_payload = response.json()
        text = self._extract_text(response_payload).strip()
        usage = self._extract_usage(response_payload, started_at=started_at) or LLMUsage(
            latency_ms=round((time.perf_counter() - started_at) * 1000)
        )

        if settings.debug_llm:
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
        started_at = time.perf_counter()
        usage = LLMUsage(latency_ms=0)
        payload = self._build_payload(
            prompt=prompt,
            system_prompt=system_prompt,
            response_mime_type=response_mime_type,
            response_schema=response_schema,
            temperature=temperature,
            stream=True,
        )
        url = self._responses_url()

        if settings.debug_llm:
            self._debug_request(
                mode="responses.stream",
                url=url,
                prompt=prompt,
                system_prompt=system_prompt,
                response_mime_type=response_mime_type,
            )

        with self._client.stream(
            "POST",
            url,
            headers=self._headers(stream=True),
            json=payload,
        ) as response:
            self._raise_for_status(response)
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
                delta = self._extract_stream_delta(event_payload)
                usage = self._extract_usage(event_payload, started_at=started_at) or usage
                if delta:
                    yield LLMStreamEvent(event_type="text_delta", delta=delta)

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
        stream: bool,
    ) -> dict[str, Any]:
        text_config = self._build_text_config(
            response_mime_type=response_mime_type,
            response_schema=response_schema,
        )
        if self._requires_json_keyword(text_config=text_config):
            prompt = self._ensure_json_keyword(prompt)

        payload: dict[str, Any] = {
            "model": self.model_name,
            "input": prompt,
            "store": False,
        }
        if system_prompt:
            payload["instructions"] = system_prompt
        if stream:
            payload["stream"] = True
        if temperature is not None and self._supports_temperature():
            payload["temperature"] = temperature

        if text_config:
            payload["text"] = text_config
        return payload

    def _build_text_config(
        self,
        *,
        response_mime_type: str | None,
        response_schema: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if response_mime_type != "application/json":
            return None
        if response_schema and self._supports_strict_json_schema(response_schema):
            return {
                "format": {
                    "type": "json_schema",
                    "name": "structured_response",
                    "schema": response_schema,
                    "strict": True,
                }
            }
        return {"format": {"type": "json_object"}}

    def _supports_strict_json_schema(self, schema: dict[str, Any]) -> bool:
        return self._is_strict_json_schema_node(schema)

    def _is_strict_json_schema_node(self, node: Any) -> bool:
        if isinstance(node, bool):
            return True
        if isinstance(node, list):
            return all(self._is_strict_json_schema_node(item) for item in node)
        if not isinstance(node, dict):
            return True

        node_type = node.get("type")
        if node_type == "object":
            if node.get("additionalProperties") is not False:
                return False
            properties = node.get("properties")
            if properties is not None and not isinstance(properties, dict):
                return False
            if isinstance(properties, dict):
                return all(self._is_strict_json_schema_node(child) for child in properties.values())

        for key, value in node.items():
            if key in {"properties", "$defs", "definitions"}:
                if not isinstance(value, dict):
                    return False
                if not all(self._is_strict_json_schema_node(child) for child in value.values()):
                    return False
                continue
            if key in {"items", "additionalProperties", "not", "if", "then", "else", "contains"}:
                if not self._is_strict_json_schema_node(value):
                    return False
                continue
            if key in {"anyOf", "allOf", "oneOf", "prefixItems"}:
                if not isinstance(value, list):
                    return False
                if not all(self._is_strict_json_schema_node(item) for item in value):
                    return False
                continue
        return True

    def _supports_temperature(self) -> bool:
        return not (
            self.model_name.startswith("gpt-5") and self.model_name.endswith("-pro")
        )

    def _requires_json_keyword(self, *, text_config: dict[str, Any] | None) -> bool:
        if not isinstance(text_config, dict):
            return False
        format_config = text_config.get("format")
        if not isinstance(format_config, dict):
            return False
        return format_config.get("type") == "json_object"

    def _ensure_json_keyword(self, prompt: str) -> str:
        if "json" in prompt.lower():
            return prompt
        return "JSON response required.\n\n" + prompt

    def _raise_for_status(self, response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            settings = get_settings()
            if settings.debug_llm:
                print(f"[DEBUG_LLM] HTTP ERROR: {response.status_code} {response.text[:2000]}")
            raise

    def _responses_url(self) -> str:
        return f"{self.base_url}/responses"

    def _headers(self, *, stream: bool = False) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        if stream:
            headers["Accept"] = "text/event-stream"
        if self.organization_id:
            headers["OpenAI-Organization"] = self.organization_id
        if self.project_id:
            headers["OpenAI-Project"] = self.project_id
        return headers

    def _extract_text(self, payload: dict[str, Any]) -> str:
        direct_text = payload.get("output_text")
        if isinstance(direct_text, str) and direct_text:
            return direct_text

        output_items = payload.get("output") or []
        chunks: list[str] = []
        for item in output_items:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for content in item.get("content") or []:
                if not isinstance(content, dict):
                    continue
                if content.get("type") == "output_text":
                    text = content.get("text")
                    if isinstance(text, str):
                        chunks.append(text)
        return "".join(chunks)

    def _extract_stream_delta(self, payload: dict[str, Any]) -> str:
        if payload.get("type") != "response.output_text.delta":
            return ""
        delta = payload.get("delta")
        return delta if isinstance(delta, str) else ""

    def _extract_usage(self, payload: dict[str, Any], *, started_at: float) -> LLMUsage | None:
        usage_payload = payload.get("usage")
        if not isinstance(usage_payload, dict):
            response_payload = payload.get("response")
            if isinstance(response_payload, dict):
                usage_payload = response_payload.get("usage")
        if not isinstance(usage_payload, dict):
            return None
        return LLMUsage(
            input_tokens=usage_payload.get("input_tokens"),
            output_tokens=usage_payload.get("output_tokens"),
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

    def _debug_response(self, *, text: str, usage: LLMUsage | None) -> None:
        print("\n" + "-" * 80)
        print(f"[DEBUG_LLM] RESPONSE from {self.model_name}")
        print(
            "[DEBUG_LLM] Tokens: "
            f"in={usage.input_tokens if usage else None}, "
            f"out={usage.output_tokens if usage else None}, "
            f"latency={usage.latency_ms if usage else None}ms"
        )
        print(f"[DEBUG_LLM] OUTPUT ({len(text)} chars):")
        print(text[:4000] + ("..." if len(text) > 4000 else ""))
        print("-" * 80 + "\n")
