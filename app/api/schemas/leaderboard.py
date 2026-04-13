from pydantic import BaseModel, ConfigDict

from app.domain.enums import Game


class LeaderboardTopUserSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    username: str | None = None


class LeaderboardEntrySchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    own_champion_slug: str
    enemy_champion_slug: str | None = None
    top_run_id: str
    top_session_id: str | None = None
    top_user: LeaderboardTopUserSchema = LeaderboardTopUserSchema()
    top_score: int
    updated_at: str | None = None


class PaginationSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    limit: int
    offset: int


class LeaderboardListPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    game: Game
    data_version: str
    items: list[LeaderboardEntrySchema]
    pagination: PaginationSchema
