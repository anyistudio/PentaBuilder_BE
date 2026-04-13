"""Add admin job, calibration, and benchmark tables."""

import sqlalchemy as sa
from alembic import op

revision = "20260412_0002"
down_revision = "20260412_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_calibrations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("game", sa.Text(), nullable=False),
        sa.Column("data_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("summary_object_key", sa.Text(), nullable=True),
        sa.Column("summary_excerpt", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "game in ('lol', 'wild_rift')",
            name="model_calibrations_game_valid",
        ),
        sa.CheckConstraint(
            "status in ('pending', 'completed', 'failed')",
            name="model_calibrations_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["data_version"],
            ["data_versions.data_version"],
            name=op.f("fk_model_calibrations_data_version_data_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_calibrations")),
        sa.UniqueConstraint(
            "provider_name",
            "model_name",
            "game",
            "data_version",
            name=op.f("uq_model_calibrations_provider_name"),
        ),
    )
    op.create_index(
        "ix_model_calibrations_model_created_at",
        "model_calibrations",
        ["model_name", "created_at"],
        unique=False,
    )

    op.create_table(
        "benchmark_datasets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("game", sa.Text(), nullable=False),
        sa.Column("data_version", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("labeling_status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "game in ('lol', 'wild_rift')",
            name="benchmark_datasets_game_valid",
        ),
        sa.CheckConstraint(
            "labeling_status in ('draft', 'ready', 'archived')",
            name="benchmark_datasets_labeling_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["data_version"],
            ["data_versions.data_version"],
            name=op.f("fk_benchmark_datasets_data_version_data_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_benchmark_datasets")),
        sa.UniqueConstraint("name", name=op.f("uq_benchmark_datasets_name")),
    )

    op.create_table(
        "benchmark_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("case_key", sa.Text(), nullable=False),
        sa.Column("run_type", sa.Text(), nullable=False),
        sa.Column("input_context", sa.JSON(), nullable=False),
        sa.Column("expected_output", sa.JSON(), nullable=False),
        sa.Column("grading_rubric", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["benchmark_datasets.id"],
            name=op.f("fk_benchmark_cases_dataset_id_benchmark_datasets"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_benchmark_cases")),
        sa.UniqueConstraint("dataset_id", "case_key", name=op.f("uq_benchmark_cases_dataset_id")),
    )
    op.create_index(
        "ix_benchmark_cases_dataset_run_type",
        "benchmark_cases",
        ["dataset_id", "run_type"],
        unique=False,
    )

    op.create_table(
        "benchmark_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("summary_object_key", sa.Text(), nullable=True),
        sa.Column("avg_latency_ms", sa.Integer(), nullable=True),
        sa.Column("avg_cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("accuracy_score", sa.Numeric(6, 4), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status in ('pending', 'running', 'completed', 'failed')",
            name="benchmark_runs_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["benchmark_datasets.id"],
            name=op.f("fk_benchmark_runs_dataset_id_benchmark_datasets"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_benchmark_runs")),
    )
    op.create_index(
        "ix_benchmark_runs_dataset_status",
        "benchmark_runs",
        ["dataset_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_benchmark_runs_model_created_at",
        "benchmark_runs",
        ["model_name", "created_at"],
        unique=False,
    )

    op.create_table(
        "benchmark_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("benchmark_run_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("ai_run_id", sa.Uuid(), nullable=True),
        sa.Column("score", sa.Numeric(6, 4), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("result_summary", sa.JSON(), nullable=True),
        sa.Column("artifact_object_key", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["ai_run_id"], ["ai_runs.id"], name=op.f("fk_benchmark_results_ai_run_id_ai_runs")
        ),
        sa.ForeignKeyConstraint(
            ["benchmark_run_id"],
            ["benchmark_runs.id"],
            name=op.f("fk_benchmark_results_benchmark_run_id_benchmark_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["benchmark_cases.id"],
            name=op.f("fk_benchmark_results_case_id_benchmark_cases"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_benchmark_results")),
        sa.UniqueConstraint(
            "benchmark_run_id",
            "case_id",
            name=op.f("uq_benchmark_results_benchmark_run_id"),
        ),
    )
    op.create_index(
        "ix_benchmark_results_run_score",
        "benchmark_results",
        ["benchmark_run_id", "score"],
        unique=False,
    )
    op.create_index("ix_benchmark_results_case_id", "benchmark_results", ["case_id"], unique=False)

    op.create_table(
        "admin_job_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("request_payload", sa.JSON(), nullable=True),
        sa.Column("result_summary", sa.JSON(), nullable=True),
        sa.Column("artifact_object_key", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status in ('pending', 'running', 'completed', 'failed')",
            name="admin_job_runs_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("fk_admin_job_runs_requested_by_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_job_runs")),
    )


def downgrade() -> None:
    op.drop_table("admin_job_runs")

    op.drop_index("ix_benchmark_results_case_id", table_name="benchmark_results")
    op.drop_index("ix_benchmark_results_run_score", table_name="benchmark_results")
    op.drop_table("benchmark_results")

    op.drop_index("ix_benchmark_runs_model_created_at", table_name="benchmark_runs")
    op.drop_index("ix_benchmark_runs_dataset_status", table_name="benchmark_runs")
    op.drop_table("benchmark_runs")

    op.drop_index("ix_benchmark_cases_dataset_run_type", table_name="benchmark_cases")
    op.drop_table("benchmark_cases")

    op.drop_table("benchmark_datasets")

    op.drop_index("ix_model_calibrations_model_created_at", table_name="model_calibrations")
    op.drop_table("model_calibrations")
