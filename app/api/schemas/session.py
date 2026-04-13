from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import Game
from app.domain.match_context import MatchContext, SessionEvent


class SessionSummarySchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str | None = None
    game: Game
    data_version: str
    event_count: int
    updated_at: str | None = None
    last_context_snapshot: dict = Field(default_factory=dict)


class SessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    client_session_id: str | None = None
    game: Game
    data_version: str
    initial_context: MatchContext


class SessionCreatePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session: SessionSummarySchema


class SessionDetailPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session: SessionSummarySchema
    transcript: dict


class SessionListPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[SessionSummarySchema]
    next_cursor: str | None = None


class SessionClaimRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    client_session_id: str
    events: list[SessionEvent]


class SessionClaimPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session_id: str
    claimed_event_count: int
