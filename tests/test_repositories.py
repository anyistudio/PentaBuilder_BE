import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import create_database_engine, create_session_factory
from app.repositories.core import (
    AIRunsRepository,
    CacheRepository,
    DataVersionsRepository,
    LeaderboardRepository,
    SessionsRepository,
    UsersRepository,
)


@pytest.fixture
def db_session(tmp_path) -> Session:
    database_url = f"sqlite:///{tmp_path / 'repo-tests.db'}"
    engine = create_database_engine(database_url)
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    session_factory = create_session_factory(database_url)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_repository_crud_round_trip(db_session: Session) -> None:
    users_repository = UsersRepository(db_session)
    data_versions_repository = DataVersionsRepository(db_session)
    sessions_repository = SessionsRepository(db_session)
    ai_runs_repository = AIRunsRepository(db_session)
    cache_repository = CacheRepository(db_session)

    user = users_repository.create(
        auth_provider="clerk",
        auth_subject="user_123",
        email="test@example.com",
        username="BlueFox",
    )
    data_version = data_versions_repository.create(
        data_version="full-20260411",
        manifest_object_key="game_data/manifest.json",
        source_root="game_data",
        is_active=True,
    )
    session_record = sessions_repository.create(
        user_id=user.id,
        client_session_id="client-1",
        game="lol",
        data_version=data_version.data_version,
        last_context_snapshot={},
        transcript_object_key="sessions/session-1.json",
    )
    run = ai_runs_repository.create(
        session_id=session_record.id,
        user_id=user.id,
        run_type="evaluate_build",
        status="completed",
        game="lol",
        data_version=data_version.data_version,
        own_champion_slug="lol-ahri",
        enemy_comp_key="lol-zed",
        normalized_environment_key="ranked",
        has_free_text_environment=False,
        operation_context={"slot_index": 2},
        semantic_context_hash="a" * 64,
        response_variant_hash="b" * 64,
        structured_result={"score": 84},
    )
    cache_entry = cache_repository.create(
        run_type="evaluate_build",
        game="lol",
        data_version=data_version.data_version,
        own_champion_slug="lol-ahri",
        enemy_comp_key="lol-zed",
        enemy_count=1,
        normalized_environment_key="ranked",
        semantic_context_hash="a" * 64,
        response_variant_hash="b" * 64,
        language="zh-CN",
        terminology_style="official",
        structured_result={"score": 84},
        artifact_object_key="runs/run-1.json",
        source_run_id=run.id,
    )

    assert users_repository.get_by_auth_subject("clerk", "user_123") is not None
    assert data_versions_repository.get_active() is not None
    assert sessions_repository.get(session_record.id) is not None
    assert ai_runs_repository.get(run.id) is not None
    assert (
        cache_repository.get_by_response_variant_hash(
            run_type="evaluate_build",
            response_variant_hash=cache_entry.response_variant_hash,
        )
        is not None
    )


def test_leaderboard_unique_scope_handles_null_enemy(db_session: Session) -> None:
    users_repository = UsersRepository(db_session)
    data_versions_repository = DataVersionsRepository(db_session)
    ai_runs_repository = AIRunsRepository(db_session)
    leaderboard_repository = LeaderboardRepository(db_session)

    user = users_repository.create(auth_provider="clerk", auth_subject="user_456")
    data_version = data_versions_repository.create(
        data_version="full-20260411",
        manifest_object_key="game_data/manifest.json",
        source_root="game_data",
        is_active=True,
    )
    run = ai_runs_repository.create(
        user_id=user.id,
        run_type="evaluate_build",
        status="completed",
        game="lol",
        data_version=data_version.data_version,
        own_champion_slug="lol-ahri",
        enemy_comp_key="_none",
        normalized_environment_key="_none",
        has_free_text_environment=False,
        operation_context={},
        semantic_context_hash="c" * 64,
        response_variant_hash="d" * 64,
        structured_result={"score": 91},
    )
    leaderboard_repository.create(
        game="lol",
        data_version=data_version.data_version,
        own_champion_slug="lol-ahri",
        enemy_champion_slug=None,
        top_run_id=run.id,
        top_user_id=user.id,
        top_username_snapshot="BlueFox",
        top_score=91,
    )

    with pytest.raises(IntegrityError):
        leaderboard_repository.create(
            game="lol",
            data_version=data_version.data_version,
            own_champion_slug="lol-ahri",
            enemy_champion_slug=None,
            top_run_id=run.id,
            top_user_id=user.id,
            top_username_snapshot="BlueFox",
            top_score=92,
        )
