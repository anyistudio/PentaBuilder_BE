from app.ai.providers.base import BaseLLMClient
from app.ai.providers.gemini_client import GeminiClient
from app.core.config import Settings


def create_llm_client(
    *, settings: Settings, provider_name: str, model_name: str
) -> BaseLLMClient | None:
    if provider_name == "google" and settings.google_api_key.get_secret_value() not in {
        "",
        "replace-me",
    }:
        return GeminiClient(
            model_name=model_name, api_key=settings.google_api_key.get_secret_value()
        )
    return None
