from app.ai.providers.factory import create_llm_client
from app.ai.providers.gemini_client import GeminiClient
from app.ai.providers.openai_client import OpenAIClient
from app.core.config import Settings


def test_openai_client_uses_responses_json_schema_payload():
    client = OpenAIClient(model_name="gpt-5.4-mini", api_key="test-key")

    payload = client._build_payload(
        prompt="Return JSON.",
        system_prompt="You are a test model.",
        response_mime_type="application/json",
        response_schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
        temperature=0.2,
        stream=False,
    )

    assert payload["model"] == "gpt-5.4-mini"
    assert payload["input"] == "Return JSON."
    assert payload["instructions"] == "You are a test model."
    assert payload["store"] is False
    assert payload["temperature"] == 0.2
    assert payload["text"] == {
        "format": {
            "type": "json_schema",
            "name": "structured_response",
            "schema": {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            },
            "strict": True,
        }
    }


def test_openai_client_falls_back_to_json_object_for_open_object_schema():
    client = OpenAIClient(model_name="gpt-5.4-mini", api_key="test-key")

    payload = client._build_payload(
        prompt="Return an object.",
        system_prompt=None,
        response_mime_type="application/json",
        response_schema={
            "type": "object",
            "properties": {
                "arguments": {
                    "type": "object",
                    "additionalProperties": True,
                }
            },
            "required": ["arguments"],
            "additionalProperties": False,
        },
        temperature=0.2,
        stream=False,
    )

    assert payload["input"].startswith("JSON response required.")
    assert payload["text"] == {"format": {"type": "json_object"}}


def test_openai_client_omits_temperature_for_gpt5_pro():
    client = OpenAIClient(model_name="gpt-5.4-pro", api_key="test-key")

    payload = client._build_payload(
        prompt="Say hi.",
        system_prompt=None,
        response_mime_type=None,
        response_schema=None,
        temperature=0.2,
        stream=False,
    )

    assert "temperature" not in payload


def test_openai_client_extracts_text_from_responses_output_items():
    client = OpenAIClient(model_name="gpt-5.4-mini", api_key="test-key")
    payload = {
        "output": [
            {"type": "reasoning", "summary": []},
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": '{"ok":true}'},
                ],
            },
        ]
    }

    assert client._extract_text(payload) == '{"ok":true}'


def test_openai_client_extracts_stream_delta_and_completed_usage():
    client = OpenAIClient(model_name="gpt-5.4-mini", api_key="test-key")
    delta_payload = {
        "type": "response.output_text.delta",
        "delta": "Hello",
    }
    completed_payload = {
        "type": "response.completed",
        "response": {
            "usage": {
                "input_tokens": 11,
                "output_tokens": 7,
            }
        },
    }

    assert client._extract_stream_delta(delta_payload) == "Hello"
    usage = client._extract_usage(completed_payload, started_at=0.0)
    assert usage is not None
    assert usage.input_tokens == 11
    assert usage.output_tokens == 7


def test_create_llm_client_reuses_openai_instances():
    settings = Settings(openai_api_key="test-key")

    first = create_llm_client(
        settings=settings,
        provider_name="openai",
        model_name="gpt-5.4-mini",
    )
    second = create_llm_client(
        settings=settings,
        provider_name="openai",
        model_name="gpt-5.4-mini",
    )

    assert first is second


def test_gemini_client_normalizes_legacy_model_aliases():
    preview_client = GeminiClient(model_name="gemini-3.1-pro-preview", api_key="test-key")
    legacy_client = GeminiClient(model_name="gemini-3.1-pro", api_key="test-key")

    assert preview_client.model_name == "gemini-3-pro-preview"
    assert legacy_client.model_name == "gemini-3-pro-preview"
