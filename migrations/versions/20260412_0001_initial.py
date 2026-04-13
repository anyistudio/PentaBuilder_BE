"""Initial backend schema."""

import sqlalchemy as sa
from alembic import op

revision = "20260412_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    dialect_name = op.get_bind().dialect.name

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("auth_provider", sa.Text(), nullable=False),
        sa.Column("auth_subject", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("email_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("icon_url", sa.Text(), nullable=True),
        sa.Column(
            "preferred_language", sa.Text(), server_default=sa.text("'zh-CN'"), nullable=False
        ),
        sa.Column(
            "preferred_terminology_style",
            sa.Text(),
            server_default=sa.text("'official'"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("auth_provider in ('clerk')", name="users_auth_provider_valid"),
        sa.CheckConstraint(
            "preferred_language in ('zh-CN', 'en')",
            name="users_preferred_language_valid",
        ),
        sa.CheckConstraint(
            "preferred_terminology_style in ('official', 'slang_zh')",
            name="users_terminology_style_valid",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("auth_provider", "auth_subject", name=op.f("uq_users_auth_provider")),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=False)
    op.create_index("ix_users_username", "users", ["username"], unique=False)

    op.create_table(
        "data_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("data_version", sa.Text(), nullable=False),
        sa.Column("manifest_object_key", sa.Text(), nullable=False),
        sa.Column("source_root", sa.Text(), nullable=False),
        sa.Column("lol_patch_version", sa.Text(), nullable=True),
        sa.Column("wild_rift_patch_version", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_versions")),
        sa.UniqueConstraint("data_version", name=op.f("uq_data_versions_data_version")),
    )
    op.create_index(
        "uq_data_versions_active",
        "data_versions",
        ["is_active"],
        unique=True,
        sqlite_where=sa.text("is_active = 1"),
        postgresql_where=sa.text("is_active = true"),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("client_session_id", sa.Text(), nullable=True),
        sa.Column("game", sa.Text(), nullable=False),
        sa.Column("data_version", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("last_context_snapshot", sa.JSON(), nullable=False),
        sa.Column("transcript_object_key", sa.Text(), nullable=False),
        sa.Column("event_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("game in ('lol', 'wild_rift')", name="sessions_game_valid"),
        sa.ForeignKeyConstraint(
            ["data_version"],
            ["data_versions.data_version"],
            name=op.f("fk_sessions_data_version_data_versions"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("client_session_id", name=op.f("uq_sessions_client_session_id")),
    )
    op.create_index(
        "ix_sessions_user_updated_at", "sessions", ["user_id", "updated_at"], unique=False
    )
    op.create_index(
        "ix_sessions_data_version_updated_at",
        "sessions",
        ["data_version", "updated_at"],
        unique=False,
    )

    op.create_table(
        "ai_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("run_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("game", sa.Text(), nullable=False),
        sa.Column("data_version", sa.Text(), nullable=False),
        sa.Column("own_champion_slug", sa.Text(), nullable=True),
        sa.Column("enemy_comp_key", sa.Text(), nullable=True),
        sa.Column("normalized_environment_key", sa.Text(), nullable=True),
        sa.Column(
            "has_free_text_environment",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("operation_context", sa.JSON(), nullable=False),
        sa.Column("semantic_context_hash", sa.CHAR(length=64), nullable=True),
        sa.Column("response_variant_hash", sa.CHAR(length=64), nullable=True),
        sa.Column("cache_resolution", sa.Text(), server_default=sa.text("'miss'"), nullable=False),
        sa.Column("cached_entry_id", sa.Uuid(), nullable=True),
        sa.Column("provider_name", sa.Text(), nullable=True),
        sa.Column("model_name", sa.Text(), nullable=True),
        sa.Column("tokens_input", sa.Integer(), nullable=True),
        sa.Column("tokens_output", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("score_value", sa.SmallInteger(), nullable=True),
        sa.Column("structured_result", sa.JSON(), nullable=True),
        sa.Column("artifact_object_key", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
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
        sa.ForeignKeyConstraint(
            ["data_version"],
            ["data_versions.data_version"],
            name=op.f("fk_ai_runs_data_version_data_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], name=op.f("fk_ai_runs_session_id_sessions")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_ai_runs_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_runs")),
    )
    op.create_index(
        "ix_ai_runs_session_created_at", "ai_runs", ["session_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_ai_runs_user_created_at", "ai_runs", ["user_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_ai_runs_game_version_type_created_at",
        "ai_runs",
        ["game", "data_version", "run_type", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_ai_runs_game_version_champion_created_at",
        "ai_runs",
        ["game", "data_version", "own_champion_slug", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_ai_runs_semantic_context_hash", "ai_runs", ["semantic_context_hash"], unique=False
    )
    op.create_index(
        "ix_ai_runs_response_variant_hash", "ai_runs", ["response_variant_hash"], unique=False
    )
    op.create_index(
        "ix_ai_runs_cache_resolution_created_at",
        "ai_runs",
        ["cache_resolution", "created_at"],
        unique=False,
    )

    op.create_table(
        "baseline_builds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("game", sa.Text(), nullable=False),
        sa.Column("data_version", sa.Text(), nullable=False),
        sa.Column("own_champion_slug", sa.Text(), nullable=False),
        sa.Column("recommended_build", sa.JSON(), nullable=False),
        sa.Column("recommended_runes", sa.JSON(), nullable=False),
        sa.Column("provider_name", sa.Text(), nullable=True),
        sa.Column("model_name", sa.Text(), nullable=True),
        sa.Column("source_run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("game in ('lol', 'wild_rift')", name="baseline_builds_game_valid"),
        sa.ForeignKeyConstraint(
            ["data_version"],
            ["data_versions.data_version"],
            name=op.f("fk_baseline_builds_data_version_data_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["source_run_id"], ["ai_runs.id"], name=op.f("fk_baseline_builds_source_run_id_ai_runs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_baseline_builds")),
        sa.UniqueConstraint(
            "game", "data_version", "own_champion_slug", name=op.f("uq_baseline_builds_game")
        ),
    )
    op.create_index(
        "ix_baseline_builds_data_version_game",
        "baseline_builds",
        ["data_version", "game"],
        unique=False,
    )

    op.create_table(
        "cached_context_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_type", sa.Text(), nullable=False),
        sa.Column("game", sa.Text(), nullable=False),
        sa.Column("data_version", sa.Text(), nullable=False),
        sa.Column("own_champion_slug", sa.Text(), nullable=False),
        sa.Column("enemy_comp_key", sa.Text(), nullable=False),
        sa.Column("enemy_count", sa.SmallInteger(), nullable=False),
        sa.Column("normalized_environment_key", sa.Text(), nullable=False),
        sa.Column("semantic_context_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("response_variant_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("terminology_style", sa.Text(), nullable=False),
        sa.Column("structured_result", sa.JSON(), nullable=False),
        sa.Column("artifact_object_key", sa.Text(), nullable=False),
        sa.Column("source_run_id", sa.Uuid(), nullable=False),
        sa.Column("hit_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("game in ('lol', 'wild_rift')", name="cache_game_valid"),
        sa.CheckConstraint("language in ('zh-CN', 'en')", name="cache_language_valid"),
        sa.CheckConstraint(
            "terminology_style in ('official', 'slang_zh')",
            name="cache_terminology_style_valid",
        ),
        sa.CheckConstraint("enemy_count between 0 and 5", name="cache_enemy_count_valid"),
        sa.ForeignKeyConstraint(
            ["data_version"],
            ["data_versions.data_version"],
            name=op.f("fk_cached_context_results_data_version_data_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["source_run_id"],
            ["ai_runs.id"],
            name=op.f("fk_cached_context_results_source_run_id_ai_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cached_context_results")),
        sa.UniqueConstraint(
            "run_type", "response_variant_hash", name=op.f("uq_cached_context_results_run_type")
        ),
    )
    op.create_index(
        "ix_cache_game_version_champion",
        "cached_context_results",
        ["game", "data_version", "own_champion_slug"],
        unique=False,
    )
    op.create_index(
        "ix_cache_semantic_context_hash",
        "cached_context_results",
        ["semantic_context_hash"],
        unique=False,
    )
    op.create_index("ix_cache_last_hit_at", "cached_context_results", ["last_hit_at"], unique=False)

    if dialect_name != "sqlite":
        op.create_foreign_key(
            "fk_ai_runs_cached_entry_id_cached_context_results",
            "ai_runs",
            "cached_context_results",
            ["cached_entry_id"],
            ["id"],
        )

    op.create_table(
        "leaderboard_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("game", sa.Text(), nullable=False),
        sa.Column("data_version", sa.Text(), nullable=False),
        sa.Column("own_champion_slug", sa.Text(), nullable=False),
        sa.Column("enemy_champion_slug", sa.Text(), nullable=True),
        sa.Column("top_run_id", sa.Uuid(), nullable=False),
        sa.Column("top_session_id", sa.Uuid(), nullable=True),
        sa.Column("top_user_id", sa.Uuid(), nullable=True),
        sa.Column("top_username_snapshot", sa.Text(), nullable=True),
        sa.Column("top_score", sa.SmallInteger(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "top_score between 0 and 100", name="leaderboard_entries_top_score_valid"
        ),
        sa.ForeignKeyConstraint(
            ["data_version"],
            ["data_versions.data_version"],
            name=op.f("fk_leaderboard_entries_data_version_data_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["top_run_id"], ["ai_runs.id"], name=op.f("fk_leaderboard_entries_top_run_id_ai_runs")
        ),
        sa.ForeignKeyConstraint(
            ["top_session_id"],
            ["sessions.id"],
            name=op.f("fk_leaderboard_entries_top_session_id_sessions"),
        ),
        sa.ForeignKeyConstraint(
            ["top_user_id"], ["users.id"], name=op.f("fk_leaderboard_entries_top_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_leaderboard_entries")),
    )
    op.create_index(
        "ix_leaderboard_game_version_top_score",
        "leaderboard_entries",
        ["game", "data_version", "top_score"],
        unique=False,
    )
    op.create_index(
        "ix_leaderboard_game_version_champion_top_score",
        "leaderboard_entries",
        ["game", "data_version", "own_champion_slug", "top_score"],
        unique=False,
    )
    op.create_index(
        "uq_leaderboard_scope",
        "leaderboard_entries",
        [
            "game",
            "data_version",
            "own_champion_slug",
            sa.text("coalesce(enemy_champion_slug, '_none')"),
        ],
        unique=True,
    )


def downgrade() -> None:
    dialect_name = op.get_bind().dialect.name

    op.drop_index("uq_leaderboard_scope", table_name="leaderboard_entries")
    op.drop_index(
        "ix_leaderboard_game_version_champion_top_score", table_name="leaderboard_entries"
    )
    op.drop_index("ix_leaderboard_game_version_top_score", table_name="leaderboard_entries")
    op.drop_table("leaderboard_entries")

    if dialect_name != "sqlite":
        op.drop_constraint(
            "fk_ai_runs_cached_entry_id_cached_context_results", "ai_runs", type_="foreignkey"
        )
    op.drop_index("ix_cache_last_hit_at", table_name="cached_context_results")
    op.drop_index("ix_cache_semantic_context_hash", table_name="cached_context_results")
    op.drop_index("ix_cache_game_version_champion", table_name="cached_context_results")
    op.drop_table("cached_context_results")

    op.drop_index("ix_baseline_builds_data_version_game", table_name="baseline_builds")
    op.drop_table("baseline_builds")

    op.drop_index("ix_ai_runs_cache_resolution_created_at", table_name="ai_runs")
    op.drop_index("ix_ai_runs_response_variant_hash", table_name="ai_runs")
    op.drop_index("ix_ai_runs_semantic_context_hash", table_name="ai_runs")
    op.drop_index("ix_ai_runs_game_version_champion_created_at", table_name="ai_runs")
    op.drop_index("ix_ai_runs_game_version_type_created_at", table_name="ai_runs")
    op.drop_index("ix_ai_runs_user_created_at", table_name="ai_runs")
    op.drop_index("ix_ai_runs_session_created_at", table_name="ai_runs")
    op.drop_table("ai_runs")

    op.drop_index("ix_sessions_data_version_updated_at", table_name="sessions")
    op.drop_index("ix_sessions_user_updated_at", table_name="sessions")
    op.drop_table("sessions")

    op.drop_index("uq_data_versions_active", table_name="data_versions")
    op.drop_table("data_versions")

    op.drop_index("ix_users_username", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
