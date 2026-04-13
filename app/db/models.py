import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

JSONType = sa.JSON().with_variant(JSONB(), "postgresql")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        sa.CheckConstraint("auth_provider in ('clerk')", name="users_auth_provider_valid"),
        sa.CheckConstraint(
            "preferred_language in ('zh-CN', 'en')",
            name="users_preferred_language_valid",
        ),
        sa.CheckConstraint(
            "preferred_terminology_style in ('official', 'slang_zh')",
            name="users_terminology_style_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    auth_provider: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    auth_subject: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    email: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    email_verified: Mapped[bool] = mapped_column(
        sa.Boolean(),
        nullable=False,
        default=False,
        server_default=sa.text("false"),
    )
    display_name: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    username: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    icon_url: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    preferred_language: Mapped[str] = mapped_column(
        sa.Text(),
        nullable=False,
        default="zh-CN",
        server_default=sa.text("'zh-CN'"),
    )
    preferred_terminology_style: Mapped[str] = mapped_column(
        sa.Text(),
        nullable=False,
        default="official",
        server_default=sa.text("'official'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


class DataVersion(Base):
    __tablename__ = "data_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    data_version: Mapped[str] = mapped_column(sa.Text(), nullable=False, unique=True)
    manifest_object_key: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    source_root: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    lol_patch_version: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    wild_rift_patch_version: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean(),
        nullable=False,
        default=False,
        server_default=sa.text("false"),
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    activated_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class SessionRecord(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        sa.CheckConstraint("game in ('lol', 'wild_rift')", name="sessions_game_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id"),
        nullable=False,
    )
    client_session_id: Mapped[str | None] = mapped_column(sa.Text(), nullable=True, unique=True)
    game: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    data_version: Mapped[str] = mapped_column(
        sa.Text(),
        sa.ForeignKey("data_versions.data_version"),
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    last_context_snapshot: Mapped[dict] = mapped_column(
        JSONType,
        nullable=False,
        default=dict,
    )
    transcript_object_key: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    event_count: Mapped[int] = mapped_column(
        sa.Integer(),
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


class AIRun(Base):
    __tablename__ = "ai_runs"
    __table_args__ = (
        sa.CheckConstraint("game in ('lol', 'wild_rift')", name="ai_runs_game_valid"),
        sa.CheckConstraint(
            "status in ('accepted', 'streaming', 'completed', 'failed', 'cancelled')",
            name="ai_runs_status_valid",
        ),
        sa.CheckConstraint(
            "cache_resolution in ('miss', 'strong_hit', 'reference_used', 'bypass')",
            name="ai_runs_cache_resolution_valid",
        ),
        sa.CheckConstraint(
            "score_value is null or (score_value between 0 and 100)",
            name="ai_runs_score_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("sessions.id"),
        nullable=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id"),
        nullable=True,
    )
    run_type: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    status: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    game: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    data_version: Mapped[str] = mapped_column(
        sa.Text(),
        sa.ForeignKey("data_versions.data_version"),
        nullable=False,
    )
    own_champion_slug: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    enemy_comp_key: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    normalized_environment_key: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    has_free_text_environment: Mapped[bool] = mapped_column(
        sa.Boolean(),
        nullable=False,
        default=False,
        server_default=sa.text("false"),
    )
    operation_context: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    semantic_context_hash: Mapped[str | None] = mapped_column(sa.CHAR(64), nullable=True)
    response_variant_hash: Mapped[str | None] = mapped_column(sa.CHAR(64), nullable=True)
    cache_resolution: Mapped[str] = mapped_column(
        sa.Text(),
        nullable=False,
        default="miss",
        server_default=sa.text("'miss'"),
    )
    cached_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey(
            "cached_context_results.id",
            use_alter=True,
            name="fk_ai_runs_cached_entry_id_cached_context_results",
        ),
        nullable=True,
    )
    provider_name: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    model_name: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    tokens_input: Mapped[int | None] = mapped_column(sa.Integer(), nullable=True)
    tokens_output: Mapped[int | None] = mapped_column(sa.Integer(), nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(sa.Numeric(12, 6), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer(), nullable=True)
    score_value: Mapped[int | None] = mapped_column(sa.SmallInteger(), nullable=True)
    structured_result: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    artifact_object_key: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    error_code: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


class BaselineBuild(Base):
    __tablename__ = "baseline_builds"
    __table_args__ = (
        sa.CheckConstraint("game in ('lol', 'wild_rift')", name="baseline_builds_game_valid"),
        sa.UniqueConstraint("game", "data_version", "own_champion_slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    game: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    data_version: Mapped[str] = mapped_column(
        sa.Text(),
        sa.ForeignKey("data_versions.data_version"),
        nullable=False,
    )
    own_champion_slug: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    recommended_build: Mapped[dict] = mapped_column(JSONType, nullable=False)
    recommended_runes: Mapped[dict] = mapped_column(JSONType, nullable=False)
    provider_name: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    model_name: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    source_run_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("ai_runs.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


class CachedContextResult(Base):
    __tablename__ = "cached_context_results"
    __table_args__ = (
        sa.CheckConstraint("game in ('lol', 'wild_rift')", name="cache_game_valid"),
        sa.CheckConstraint("language in ('zh-CN', 'en')", name="cache_language_valid"),
        sa.CheckConstraint(
            "terminology_style in ('official', 'slang_zh')",
            name="cache_terminology_style_valid",
        ),
        sa.CheckConstraint("enemy_count between 0 and 5", name="cache_enemy_count_valid"),
        sa.UniqueConstraint("run_type", "response_variant_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_type: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    game: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    data_version: Mapped[str] = mapped_column(
        sa.Text(),
        sa.ForeignKey("data_versions.data_version"),
        nullable=False,
    )
    own_champion_slug: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    enemy_comp_key: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    enemy_count: Mapped[int] = mapped_column(sa.SmallInteger(), nullable=False)
    normalized_environment_key: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    semantic_context_hash: Mapped[str] = mapped_column(sa.CHAR(64), nullable=False)
    response_variant_hash: Mapped[str] = mapped_column(sa.CHAR(64), nullable=False)
    language: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    terminology_style: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    structured_result: Mapped[dict] = mapped_column(JSONType, nullable=False)
    artifact_object_key: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    source_run_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("ai_runs.id"),
        nullable=False,
    )
    hit_count: Mapped[int] = mapped_column(
        sa.Integer(),
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    last_hit_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class LeaderboardEntry(Base):
    __tablename__ = "leaderboard_entries"
    __table_args__ = (
        sa.CheckConstraint(
            "top_score between 0 and 100",
            name="leaderboard_entries_top_score_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    game: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    data_version: Mapped[str] = mapped_column(
        sa.Text(),
        sa.ForeignKey("data_versions.data_version"),
        nullable=False,
    )
    own_champion_slug: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    enemy_champion_slug: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    top_run_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("ai_runs.id"),
        nullable=False,
    )
    top_session_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("sessions.id"),
        nullable=True,
    )
    top_user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id"),
        nullable=True,
    )
    top_username_snapshot: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    top_score: Mapped[int] = mapped_column(sa.SmallInteger(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


class ModelCalibration(Base):
    __tablename__ = "model_calibrations"
    __table_args__ = (
        sa.CheckConstraint("game in ('lol', 'wild_rift')", name="model_calibrations_game_valid"),
        sa.CheckConstraint(
            "status in ('pending', 'completed', 'failed')",
            name="model_calibrations_status_valid",
        ),
        sa.UniqueConstraint("provider_name", "model_name", "game", "data_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider_name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    model_name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    game: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    data_version: Mapped[str] = mapped_column(
        sa.Text(),
        sa.ForeignKey("data_versions.data_version"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    summary_object_key: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    summary_excerpt: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


class BenchmarkDataset(Base):
    __tablename__ = "benchmark_datasets"
    __table_args__ = (
        sa.CheckConstraint("game in ('lol', 'wild_rift')", name="benchmark_datasets_game_valid"),
        sa.CheckConstraint(
            "labeling_status in ('draft', 'ready', 'archived')",
            name="benchmark_datasets_labeling_status_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(sa.Text(), nullable=False, unique=True)
    game: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    data_version: Mapped[str] = mapped_column(
        sa.Text(),
        sa.ForeignKey("data_versions.data_version"),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    labeling_status: Mapped[str] = mapped_column(
        sa.Text(),
        nullable=False,
        default="draft",
        server_default=sa.text("'draft'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


class BenchmarkCase(Base):
    __tablename__ = "benchmark_cases"
    __table_args__ = (sa.UniqueConstraint("dataset_id", "case_key"),)

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("benchmark_datasets.id"),
        nullable=False,
    )
    case_key: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    run_type: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    input_context: Mapped[dict] = mapped_column(JSONType, nullable=False)
    expected_output: Mapped[dict] = mapped_column(JSONType, nullable=False)
    grading_rubric: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"
    __table_args__ = (
        sa.CheckConstraint(
            "status in ('pending', 'running', 'completed', 'failed')",
            name="benchmark_runs_status_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("benchmark_datasets.id"),
        nullable=False,
    )
    provider_name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    model_name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    status: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    summary_object_key: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    avg_latency_ms: Mapped[int | None] = mapped_column(sa.Integer(), nullable=True)
    avg_cost_usd: Mapped[float | None] = mapped_column(sa.Numeric(12, 6), nullable=True)
    accuracy_score: Mapped[float | None] = mapped_column(sa.Numeric(6, 4), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


class BenchmarkResult(Base):
    __tablename__ = "benchmark_results"
    __table_args__ = (sa.UniqueConstraint("benchmark_run_id", "case_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    benchmark_run_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("benchmark_runs.id"),
        nullable=False,
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("benchmark_cases.id"),
        nullable=False,
    )
    ai_run_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("ai_runs.id"),
        nullable=True,
    )
    score: Mapped[float | None] = mapped_column(sa.Numeric(6, 4), nullable=True)
    passed: Mapped[bool | None] = mapped_column(sa.Boolean(), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer(), nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(sa.Numeric(12, 6), nullable=True)
    result_summary: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    artifact_object_key: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


class AdminJobRun(Base):
    __tablename__ = "admin_job_runs"
    __table_args__ = (
        sa.CheckConstraint(
            "status in ('pending', 'running', 'completed', 'failed')",
            name="admin_job_runs_status_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_type: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    status: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id"),
        nullable=True,
    )
    request_payload: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    result_summary: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    artifact_object_key: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


sa.Index(
    "uq_data_versions_active",
    DataVersion.is_active,
    unique=True,
    sqlite_where=sa.text("is_active = 1"),
    postgresql_where=sa.text("is_active = true"),
)
sa.Index("ix_users_email", User.email)
sa.Index("ix_users_username", User.username)
sa.Index("ix_sessions_user_updated_at", SessionRecord.user_id, SessionRecord.updated_at.desc())
sa.Index(
    "ix_sessions_data_version_updated_at",
    SessionRecord.data_version,
    SessionRecord.updated_at.desc(),
)
sa.Index("ix_ai_runs_session_created_at", AIRun.session_id, AIRun.created_at)
sa.Index("ix_ai_runs_user_created_at", AIRun.user_id, AIRun.created_at.desc())
sa.Index(
    "ix_ai_runs_game_version_type_created_at",
    AIRun.game,
    AIRun.data_version,
    AIRun.run_type,
    AIRun.created_at.desc(),
)
sa.Index(
    "ix_ai_runs_game_version_champion_created_at",
    AIRun.game,
    AIRun.data_version,
    AIRun.own_champion_slug,
    AIRun.created_at.desc(),
)
sa.Index("ix_ai_runs_semantic_context_hash", AIRun.semantic_context_hash)
sa.Index("ix_ai_runs_response_variant_hash", AIRun.response_variant_hash)
sa.Index("ix_ai_runs_cache_resolution_created_at", AIRun.cache_resolution, AIRun.created_at.desc())
sa.Index("ix_baseline_builds_data_version_game", BaselineBuild.data_version, BaselineBuild.game)
sa.Index(
    "ix_cache_game_version_champion",
    CachedContextResult.game,
    CachedContextResult.data_version,
    CachedContextResult.own_champion_slug,
)
sa.Index("ix_cache_semantic_context_hash", CachedContextResult.semantic_context_hash)
sa.Index("ix_cache_last_hit_at", CachedContextResult.last_hit_at.desc())
sa.Index(
    "ix_leaderboard_game_version_top_score",
    LeaderboardEntry.game,
    LeaderboardEntry.data_version,
    LeaderboardEntry.top_score.desc(),
)
sa.Index(
    "ix_leaderboard_game_version_champion_top_score",
    LeaderboardEntry.game,
    LeaderboardEntry.data_version,
    LeaderboardEntry.own_champion_slug,
    LeaderboardEntry.top_score.desc(),
)
sa.Index(
    "uq_leaderboard_scope",
    LeaderboardEntry.game,
    LeaderboardEntry.data_version,
    LeaderboardEntry.own_champion_slug,
    sa.func.coalesce(LeaderboardEntry.enemy_champion_slug, sa.literal("_none")),
    unique=True,
)
sa.Index(
    "ix_model_calibrations_model_created_at",
    ModelCalibration.model_name,
    ModelCalibration.created_at.desc(),
)
sa.Index("ix_benchmark_cases_dataset_run_type", BenchmarkCase.dataset_id, BenchmarkCase.run_type)
sa.Index("ix_benchmark_runs_dataset_status", BenchmarkRun.dataset_id, BenchmarkRun.status)
sa.Index(
    "ix_benchmark_runs_model_created_at",
    BenchmarkRun.model_name,
    BenchmarkRun.created_at.desc(),
)
sa.Index(
    "ix_benchmark_results_run_score",
    BenchmarkResult.benchmark_run_id,
    BenchmarkResult.score.desc(),
)
sa.Index("ix_benchmark_results_case_id", BenchmarkResult.case_id)
