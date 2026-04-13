from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.core.config import get_settings


def test_alembic_upgrade_creates_core_tables(monkeypatch, tmp_path) -> None:
    database_path = tmp_path / "migration-test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()

    config = Config("/Users/jialinliu/Dev/PentaBuilder/PentaBuilder_BE/alembic.ini")
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    table_names = set(inspect(engine).get_table_names())

    assert {
        "users",
        "data_versions",
        "sessions",
        "ai_runs",
        "baseline_builds",
        "cached_context_results",
        "leaderboard_entries",
    }.issubset(table_names)
