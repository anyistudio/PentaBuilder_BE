from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


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
    primary_reasoning_provider: str = "google"
    primary_reasoning_model: str = "gemini-3.1-pro-preview"
    fast_reasoning_provider: str = "google"
    fast_reasoning_model: str = "gemini-3.1-pro-preview"
    calibration_provider: str = "google"
    calibration_model: str = "gemini-3.1-pro-preview"
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
