from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.base import Base
from app.main import create_app


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def build_configured_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    database_path = tmp_path / "app.db"
    localization_root = tmp_path / "game_localization"
    (localization_root / "lol").mkdir(parents=True)
    (localization_root / "wild_rift").mkdir(parents=True)
    (localization_root / "lol" / "champions.zh-CN.json").write_text(
        """
        [
          {"slug": "lol-ahri", "zh_official_name": "阿狸", "zh_aliases": ["狐狸"]},
          {"slug": "lol-zed", "zh_official_name": "劫", "zh_aliases": []}
        ]
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("GAME_DATA_SOURCE", "local")
    monkeypatch.setenv(
        "GAME_DATA_LOCAL_ROOT",
        "/Users/jialinliu/Dev/PentaBuilder/PentaBuilder_BE/game_data",
    )
    monkeypatch.setenv("GAME_LOCALIZATION_ROOT", str(localization_root))
    monkeypatch.setenv(
        "BENCHMARK_LOCAL_ROOT",
        "/Users/jialinliu/Dev/PentaBuilder/PentaBuilder_BE/benchmark_datasets",
    )
    monkeypatch.setenv("JWT_SIGNING_KEY", "test-signing-key-with-32-plus-bytes")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    get_settings.cache_clear()

    app = create_app()
    engine = app.state.session_factory.kw["bind"]
    Base.metadata.create_all(bind=engine)
    return app


@pytest.fixture
def configured_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    return build_configured_app(monkeypatch, tmp_path)


@pytest.fixture
def configured_client(configured_app) -> Iterator[TestClient]:
    with TestClient(configured_app) as test_client:
        yield test_client
