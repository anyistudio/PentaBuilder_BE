from functools import lru_cache

from app.ai.providers.base import BaseLLMClient
from app.ai.providers.gemini_client import GeminiClient
from app.ai.providers.openai_client import OpenAIClient
from app.core.config import Settings


@lru_cache(maxsize=64)
def _create_google_client(model_name: str, api_key: str) -> GeminiClient:
    return GeminiClient(model_name=model_name, api_key=api_key)


@lru_cache(maxsize=64)
def _create_openai_client(
    model_name: str,
    api_key: str,
    base_url: str,
    organization_id: str | None,
    project_id: str | None,
) -> OpenAIClient:
    return OpenAIClient(
        model_name=model_name,
        api_key=api_key,
        base_url=base_url,
        organization_id=organization_id,
        project_id=project_id,
    )


def create_llm_client(
    *, settings: Settings, provider_name: str, model_name: str
) -> BaseLLMClient | None:
    if provider_name == "google" and settings.google_api_key.get_secret_value() not in {
        "",
        "replace-me",
    }:
        return _create_google_client(model_name, settings.google_api_key.get_secret_value())
    if provider_name == "openai" and settings.openai_api_key.get_secret_value() not in {
        "",
        "replace-me",
    }:
        return _create_openai_client(
            model_name,
            settings.openai_api_key.get_secret_value(),
            settings.openai_base_url,
            settings.openai_organization_id,
            settings.openai_project_id,
        )
    return None
