from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import Game


class ActivateDataVersionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data_version: str


class CacheClearRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data_version: str | None = None
    game: Game | None = None


class ProviderModelRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider_name: str
    model_name: str


class PrecomputeBaselinesRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data_version: str
    game: Game
    provider_name: str
    model_name: str


class GenerateCalibrationsRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data_version: str
    games: list[Game]
    models: list[ProviderModelRef] = Field(default_factory=list)


class RunBenchmarksRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    dataset_id: str
    models: list[ProviderModelRef] = Field(default_factory=list)


class AdminJobAcceptedPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job_id: str
    status: str


class AdminJobRunSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    job_type: str
    status: str
    summary: str | None = None
    request_payload: dict[str, Any] | None = None
    result_summary: dict[str, Any] | None = None
    artifact_object_key: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class AdminJobDetailPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job: AdminJobRunSchema
