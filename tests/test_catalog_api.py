from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.base import Base
from app.main import create_app


def test_catalog_endpoints_bootstrap_and_lookup_localized_aliases(monkeypatch, tmp_path) -> None:
    database_path = tmp_path / "catalog.db"
    localization_root = tmp_path / "game_localization"
    (localization_root / "lol").mkdir(parents=True)
    (localization_root / "wild_rift").mkdir(parents=True)
    (localization_root / "lol" / "champions.zh-CN.json").write_text(
        """
        [
          {
            "slug": "lol-ahri",
            "zh_official_name": "阿狸",
            "zh_aliases": ["狐狸"]
          }
        ]
        """.strip(),
        encoding="utf-8",
    )
    (localization_root / "wild_rift" / "champions.zh-CN.json").write_text(
        """
        [
          {
            "slug": "wr-aatrox",
            "zh_official_name": "亚托克斯",
            "zh_aliases": ["剑魔"]
          }
        ]
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("GAME_DATA_SOURCE", "local")
    monkeypatch.setenv(
        "GAME_DATA_LOCAL_ROOT",
        "/Users/jialinliu/Dev/PentaBuilder/PentaBuilder_BE/game_data",
    )
    monkeypatch.setenv("GAME_LOCALIZATION_ROOT", str(localization_root))
    get_settings.cache_clear()

    app = create_app()
    engine = app.state.session_factory.kw["bind"]
    Base.metadata.create_all(bind=engine)

    with TestClient(app) as client:
        current_version_response = client.get("/api/v1/catalog/versions/current")
        assert current_version_response.status_code == 200
        assert current_version_response.json()["data"]["data_version"] == "full-20260411"

        wild_rift_response = client.get("/api/v1/catalog/wild_rift/champions")
        assert wild_rift_response.status_code == 200
        assert wild_rift_response.json()["data"]["champions"][0]["slug"].startswith("wr-")

        lookup_response = client.get(
            "/api/v1/catalog/lol/lookup",
            params={"q": "狐狸", "entity_type": "champion", "language": "zh-CN"},
        )
        assert lookup_response.status_code == 200
        first_result = lookup_response.json()["data"]["results"][0]
        assert first_result["slug"] == "lol-ahri"
        assert first_result["name"] == "阿狸"
