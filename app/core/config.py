from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_PRIMARY_REASONING_MODEL_REF = "google:gemini-3-flash-preview"
DEFAULT_FAST_REASONING_MODEL_REF = "google:gemini-3-flash-preview"
DEFAULT_CALIBRATION_MODEL_REF = "google:gemini-3-flash-preview"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "local"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_secret: SecretStr = SecretStr("change-me")
    log_level: str = "INFO"
    access_token_ttl_seconds: int = 3600
    dev_auth_enabled: bool = True
    cors_allowed_origins: str = ""

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/pentabuilder"

    @field_validator("database_url", mode="before")
    @classmethod
    def handle_database_url(cls, v: str) -> str:
        if isinstance(v, str) and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+psycopg://", 1)
        return v

    @field_validator(
        "primary_reasoning_model",
        "fast_reasoning_model",
        "calibration_model",
        "slug_selector_model",
        mode="before",
    )
    @classmethod
    def validate_model_ref_setting(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = str(v).strip()
        if not cleaned:
            return None
        provider_name, separator, model_name = cleaned.partition(":")
        if separator == ":" and (not provider_name.strip() or not model_name.strip()):
            raise ValueError(
                "Model config values must use either `provider:model_name` or just `model_name`."
            )
        return cleaned

    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "pentabuilder-dev"
    s3_access_key: SecretStr = SecretStr("minioadmin")
    s3_secret_key: SecretStr = SecretStr("minioadmin")
    s3_region: str = "us-east-1"

    game_data_source: str = "local"
    game_data_local_root: str = "game_data"
    game_data_s3_root: str = "game_data/"
    game_localization_root: str = "game_localization/"
    benchmark_local_root: str = "benchmark_datasets/"

    jwt_signing_key: SecretStr = SecretStr("replace-me")
    clerk_secret_key: SecretStr = SecretStr("replace-me")
    clerk_jwks_url: str = "https://example.clerk.accounts.dev/.well-known/jwks.json"
    clerk_issuer: str = "https://example.clerk.accounts.dev"
    clerk_audience: str | None = None
    admin_username: str = "admin"
    admin_password: SecretStr = SecretStr("replace-me")

    google_api_key: SecretStr = SecretStr("replace-me")
    openai_api_key: SecretStr = SecretStr("replace-me")
    openai_base_url: str = "https://api.openai.com/v1"
    openai_organization_id: str | None = None
    openai_project_id: str | None = None
    all_models: str = ""
    primary_reasoning_model: str = DEFAULT_PRIMARY_REASONING_MODEL_REF
    fast_reasoning_model: str = DEFAULT_FAST_REASONING_MODEL_REF
    slug_selector_model: str | None = None
    calibration_model: str = DEFAULT_CALIBRATION_MODEL_REF
    debug_llm: bool = True

    @property
    def is_local(self) -> bool:
        return self.app_env.lower() in {"local", "dev", "development", "test"}

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def all_models_list(self) -> list[str]:
        return [model.strip() for model in self.all_models.split(",") if model.strip()]

    @property
    def resolved_primary_reasoning_provider(self) -> str:
        provider_name, _ = _split_model_ref(
            raw_value=self.primary_reasoning_model,
            fallback_provider="google",
            fallback_model="gemini-3-flash-preview",
        )
        return provider_name

    @property
    def resolved_primary_reasoning_model(self) -> str:
        _, model_name = _split_model_ref(
            raw_value=self.primary_reasoning_model,
            fallback_provider="google",
            fallback_model="gemini-3-flash-preview",
        )
        return model_name

    @property
    def resolved_fast_reasoning_provider(self) -> str:
        provider_name, _ = _split_model_ref(
            raw_value=self.fast_reasoning_model,
            fallback_provider="google",
            fallback_model="gemini-3-flash-preview",
        )
        return provider_name

    @property
    def resolved_fast_reasoning_model(self) -> str:
        _, model_name = _split_model_ref(
            raw_value=self.fast_reasoning_model,
            fallback_provider="google",
            fallback_model="gemini-3-flash-preview",
        )
        return model_name

    @property
    def resolved_slug_selector_provider(self) -> str:
        provider_name, _ = _split_model_ref(
            raw_value=self.slug_selector_model,
            fallback_provider=self.resolved_fast_reasoning_provider,
            fallback_model=self.resolved_fast_reasoning_model,
        )
        return provider_name

    @property
    def resolved_slug_selector_model(self) -> str:
        _, model_name = _split_model_ref(
            raw_value=self.slug_selector_model,
            fallback_provider=self.resolved_fast_reasoning_provider,
            fallback_model=self.resolved_fast_reasoning_model,
        )
        return model_name

    @property
    def resolved_calibration_provider(self) -> str:
        provider_name, _ = _split_model_ref(
            raw_value=self.calibration_model,
            fallback_provider="google",
            fallback_model="gemini-3-flash-preview",
        )
        return provider_name

    @property
    def resolved_calibration_model(self) -> str:
        _, model_name = _split_model_ref(
            raw_value=self.calibration_model,
            fallback_provider="google",
            fallback_model="gemini-3-flash-preview",
        )
        return model_name

    @model_validator(mode="after")
    def validate_production_auth_settings(self) -> "Settings":
        if self.is_local:
            return self

        missing: list[str] = []
        if not self.clerk_jwks_url or "example.clerk.accounts.dev" in self.clerk_jwks_url:
            missing.append("CLERK_JWKS_URL")
        if not self.clerk_issuer or self.clerk_issuer == "https://example.clerk.accounts.dev":
            missing.append("CLERK_ISSUER")

        if missing:
            raise ValueError(
                "Missing production Clerk configuration: "
                + ", ".join(missing)
                + ". Set the real Clerk domain values in Railway before deploy."
            )

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def _split_model_ref(
    *,
    raw_value: str | None,
    fallback_provider: str,
    fallback_model: str,
) -> tuple[str, str]:
    cleaned = (raw_value or "").strip()
    if not cleaned:
        return fallback_provider, fallback_model
    provider_name, separator, model_name = cleaned.partition(":")
    if separator == ":":
        if provider_name.strip() and model_name.strip():
            return provider_name.strip(), model_name.strip()
        return fallback_provider, fallback_model
    return fallback_provider, cleaned
