from fastapi.testclient import TestClient

from app.catalog.registry import CatalogEntity
from app.core.config import get_settings
from app.db.base import Base
from app.domain.enums import Game, Language, TerminologyStyle
from app.main import create_app
from app.services.catalog_service import CatalogService


def test_catalog_service_preserves_enriched_catalog_text() -> None:
    service = CatalogService(data_version_service=None, registry=None)  # type: ignore[arg-type]
    quick_explanation_en = "Poke with W, scout with E, and start fights from range with R."
    entity = CatalogEntity(
        entity_type="champion",
        game=Game.LOL,
        slug="lol-ashe",
        source_slug="ashe",
        english_name="Ashe",
        icon_url=None,
        raw_payload={
            "description": "Ashe is a marksman focused on slows and long-range engage.",
            "description_zh": "艾希是一名依靠减速和远程开团的射手。",
            "quick_explanation": "W消耗，E看视野，大招远距离开人。",
            "quick_explanation_en": quick_explanation_en,
            "abilities": [
                {
                    "skill": "Q",
                    "name": "Ranger's Focus",
                    "blurb": "Ashe builds Focus by attacking.",
                    "damage_type": "Physical damage",
                    "quick_zh": "Q就是攒层后开强化普攻，站着输出更疼。",
                }
            ],
        },
        display_names={"zh-CN": "艾希", "en": "Ashe"},
    )

    summary_zh = service.summarize_entity(
        entity,
        data_version="test",
        language=Language.ZH_CN,
        terminology_style=TerminologyStyle.OFFICIAL,
    )
    assert summary_zh.description == "艾希是一名依靠减速和远程开团的射手。"
    assert summary_zh.quick_explanation == "W消耗，E看视野，大招远距离开人。"
    assert summary_zh.abilities[0].quick_zh == "Q就是攒层后开强化普攻，站着输出更疼。"

    summary_en = service.summarize_entity(
        entity,
        data_version="test",
        language=Language.EN,
        terminology_style=TerminologyStyle.OFFICIAL,
    )
    assert summary_en.description == "Ashe is a marksman focused on slows and long-range engage."
    assert summary_en.quick_explanation == quick_explanation_en


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
        wild_rift_champions = wild_rift_response.json()["data"]["champions"]
        aatrox = next(
            champion for champion in wild_rift_champions if champion["slug"] == "wr-aatrox"
        )
        assert "top" in aatrox["position_tags"]
        assert aatrox["abilities"]
        assert aatrox["summary"]

        items_response = client.get("/api/v1/catalog/lol/items")
        assert items_response.status_code == 200
        lol_items = items_response.json()["data"]["items"]
        abyssal_mask = next(item for item in lol_items if item["slug"] == "lol-abyssal-mask")
        assert abyssal_mask["cost"] == "2650"
        assert abyssal_mask["stats"]
        assert abyssal_mask["main_attributes"]

        lookup_response = client.get(
            "/api/v1/catalog/lol/lookup",
            params={"q": "狐狸", "entity_type": "champion", "language": "zh-CN"},
        )
        assert lookup_response.status_code == 200
        first_result = lookup_response.json()["data"]["results"][0]
        assert first_result["slug"] == "lol-ahri"
        assert first_result["name"] == "阿狸"
        assert first_result["summary"]
