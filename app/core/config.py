from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
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

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/pentabuilder"

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
    primary_reasoning_provider: str = "google"
    primary_reasoning_model: str = "gemini-3.1-pro"
    fast_reasoning_provider: str = "google"
    fast_reasoning_model: str = "gemini-3.1-pro"
    calibration_provider: str = "google"
    calibration_model: str = "gemini-3.1-pro"

    @property
    def is_local(self) -> bool:
        return self.app_env.lower() in {"local", "dev", "development", "test"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
