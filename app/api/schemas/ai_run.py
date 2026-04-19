from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import RunStatus, RunType
from app.domain.match_context import MatchContext, ResponsePreferences


class AIRunSummarySchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    session_id: str | None = None
    run_type: RunType
    status: RunStatus
    cache_resolution: str
    provider_name: str | None = None
    model_name: str | None = None
    tokens_input: int | None = None
    tokens_output: int | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None
    score_value: int | None = None
    created_at: str | None = None


class AIRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_type: RunType
    context: MatchContext
    response_preferences: ResponsePreferences = Field(default_factory=ResponsePreferences)
    stream: bool = False
    session_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AIRunPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run: AIRunSummarySchema
    result: dict[str, Any] | None = None


class AIRunStreamingPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run: AIRunSummarySchema
    stream_url: str


class LLMLogClearPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cleared: bool
    existed: bool
    bytes_removed: int
    files_removed: int = 0
    log_path: str
