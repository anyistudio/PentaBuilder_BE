import json

import pytest

from app.ai.orchestration.result_contracts import validate_run_result
from app.ai.providers.base import LLMResult, LLMUsage
from app.ai.tools.catalog_tools import CatalogToolset
from app.core.errors import ApiError
from app.domain.enums import Game, RunType
from app.domain.match_context import MatchContext

WR_BUILD_TEMPLATE = [
    "wr-luden-s-echo",
    "wr-ionian-boots-of-lucidity",
    "wr-stormsurge",
    "wr-stasis-enchant",
    "wr-infinity-orb",
    "wr-rabadon-s-deathcap",
    "wr-void-staff",
]
WR_BUILD_ORDER_WITH_ENCHANT = [
    "wr-essence-reaver",
    "wr-gluttonous-greaves",
    "wr-navori-quickblades",
    "wr-stasis-enchant",
    "wr-infinity-edge",
    "wr-bloodthirster",
    "wr-mortal-reminder",
]
WR_RUNES_TEMPLATE = {
    "primary": [
        "wr-conqueror",
        "wr-brutal",
        "wr-coup-de-grace",
        "wr-legend-alacrity",
    ],
    "secondary": ["wr-bone-plating"],
}


class FixedSelectorLLM:
    provider_name = "google"
    model_name = "gemini-selector-test"

    def __init__(self, *, selected_slug: str) -> None:
        self.selected_slug = selected_slug

    def generate_text(
        self,
        *,
        prompt: str,
        system_prompt: str | None = None,
        response_mime_type: str | None = None,
        response_schema: dict | None = None,
        temperature: float | None = None,
    ) -> LLMResult:
        del prompt, system_prompt, response_mime_type, response_schema, temperature
        return LLMResult(
            text=json.dumps(
                {
                    "resolution_status": "selected",
                    "selected_slug": self.selected_slug,
                    "reasoning_summary": "候选里只有这个最符合原始名字。",
                },
                ensure_ascii=False,
            ),
            usage=LLMUsage(input_tokens=7, output_tokens=6, latency_ms=3, cost_usd=0.0002),
            provider_name=self.provider_name,
            model_name=self.model_name,
        )


def _load_snapshot(configured_app):
    session = configured_app.state.session_factory()
    version = configured_app.state.data_version_service.get_active_version(session)
    snapshot = configured_app.state.game_data_registry.get_or_load(
        data_version=version.data_version,
        source_root=version.source_root,
    )
    session.close()
    return snapshot


def test_resolve_catalog_slug_can_fallback_to_selector_model(
    configured_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _load_snapshot(configured_app)
    toolset = CatalogToolset(
        catalog_service=configured_app.state.catalog_service,
        selector_llm_client=FixedSelectorLLM(selected_slug="wr-crown-of-the-shattered-queen"),
    )
    monkeypatch.setattr(toolset, "_select_top_ranked_candidate", lambda ranked: None)

    result, usage_payloads = toolset.resolve_catalog_slug(
        snapshot,
        game=Game.WILD_RIFT,
        entity_type="item",
        raw_name="queen crown",
        filters={"category": "ap"},
    )

    assert result["resolution_status"] == "resolved"
    assert result["resolved_by"] == "selector_model"
    assert result["resolved_slug"] == "wr-crown-of-the-shattered-queen"
    assert any(
        candidate.get("slug") == "wr-crown-of-the-shattered-queen"
        for candidate in result["candidates"]
    )
    assert usage_payloads[0]["model_name"] == "gemini-selector-test"


def test_resolve_catalog_slug_uses_fuzzy_match_for_near_miss_item_id(configured_app) -> None:
    snapshot = _load_snapshot(configured_app)
    toolset = CatalogToolset(
        catalog_service=configured_app.state.catalog_service,
        selector_llm_client=None,
    )

    result, usage_payloads = toolset.resolve_catalog_slug(
        snapshot,
        game=Game.WILD_RIFT,
        entity_type="item",
        raw_name="wr-ludens-echo",
        filters=None,
    )

    assert usage_payloads == []
    assert result["resolution_status"] == "resolved"
    assert result["resolved_slug"] == "wr-luden-s-echo"
    assert result["resolved_id"] == "wr-luden-s-echo"
    assert result["resolved_entity"]["id"] == "wr-luden-s-echo"
    assert result["resolved_entity"]["fuzzy_score"] >= 90


def test_search_catalog_returns_top_match_with_real_id_and_params(configured_app) -> None:
    snapshot = _load_snapshot(configured_app)
    toolset = CatalogToolset(
        catalog_service=configured_app.state.catalog_service,
        selector_llm_client=None,
    )

    session = configured_app.state.session_factory()
    try:
        result = toolset.search_catalog(
            session,
            game=Game.WILD_RIFT,
            snapshot=snapshot,
            entity_type="item",
            query="ludens echo",
            limit=5,
        )
    finally:
        session.close()

    assert result["match_count"] >= 1
    assert result["top_match"]["id"] == "wr-luden-s-echo"
    assert result["top_match"]["slug"] == "wr-luden-s-echo"
    assert result["top_match"]["cost"]
    assert result["top_match"]["stats"]


def test_list_item_ids_returns_real_ids_for_magic_items(configured_app) -> None:
    snapshot = _load_snapshot(configured_app)
    toolset = CatalogToolset(
        catalog_service=configured_app.state.catalog_service,
        selector_llm_client=None,
    )

    result = toolset.list_item_ids(
        snapshot,
        game=Game.WILD_RIFT,
        category="magic",
    )

    assert result["requested_categories"] == ["magic"]
    assert result["item_count"] >= 1
    assert any(item["id"] == "wr-luden-s-echo" for item in result["items"])


def test_validate_run_result_reports_field_level_slug_errors(configured_app) -> None:
    snapshot = _load_snapshot(configured_app)
    context = MatchContext(
        game=Game.WILD_RIFT,
        data_version=snapshot.data_version,
        own_champion_slug="wr-ahri",
        enemy_team=[],
        own_build=[None, None, None, None, None, None, None],
        own_runes={"primary": [], "secondary": []},
        environment={"tags": [], "free_text": ""},
    )

    with pytest.raises(ApiError) as exc_info:
        validate_run_result(
            run_type=RunType.RECOMMEND_FULL_BUILD,
            raw_result={
                "recommended_build_order": ["wr-sorcerer-s-shoes", *WR_BUILD_TEMPLATE[1:]],
                "recommended_runes": {
                    "primary": ["wr-electrocute"],
                    "secondary": ["wr-sudden-impact"],
                },
                "summary": "bad slugs",
                "slot_notes": [],
            },
            context=context,
            operation_context={},
            snapshot=snapshot,
        )

    issues = exc_info.value.details["issues"]
    assert issues[0]["loc"] == ["recommended_build_order", 0]
    assert "Unknown item slug `wr-sorcerer-s-shoes`" in issues[0]["msg"]


def test_validate_run_result_accepts_seven_step_build_order_with_boots_and_enchant(
    configured_app,
) -> None:
    snapshot = _load_snapshot(configured_app)
    context = MatchContext(
        game=Game.WILD_RIFT,
        data_version=snapshot.data_version,
        own_champion_slug="wr-lucian",
        enemy_team=[],
        own_build=[None, None, None, None, None, None, None],
        own_runes={"primary": [], "secondary": []},
        environment={"tags": [], "free_text": ""},
    )

    result = validate_run_result(
        run_type=RunType.RECOMMEND_FULL_BUILD,
        raw_result={
            "recommended_build_order": WR_BUILD_ORDER_WITH_ENCHANT,
            "recommended_runes": WR_RUNES_TEMPLATE,
            "summary": "valid build order",
            "slot_notes": [{"slot_index": 3, "text": "第三步后补附魔提升容错。"}],
        },
        context=context,
        operation_context={},
        snapshot=snapshot,
    )

    assert result["recommended_build_order"] == WR_BUILD_ORDER_WITH_ENCHANT
    assert result["recommended_build"] == WR_BUILD_ORDER_WITH_ENCHANT
    assert result["build"] == WR_BUILD_ORDER_WITH_ENCHANT
    assert result["explanations"][0]["target"] == "step:4"


def test_validate_run_result_rejects_wild_rift_build_order_without_seven_steps(
    configured_app,
) -> None:
    snapshot = _load_snapshot(configured_app)
    context = MatchContext(
        game=Game.WILD_RIFT,
        data_version=snapshot.data_version,
        own_champion_slug="wr-lucian",
        enemy_team=[],
        own_build=[None, None, None, None, None, None, None],
        own_runes={"primary": [], "secondary": []},
        environment={"tags": [], "free_text": ""},
    )

    with pytest.raises(ApiError) as exc_info:
        validate_run_result(
            run_type=RunType.RECOMMEND_FULL_BUILD,
            raw_result={
                "recommended_build_order": WR_BUILD_ORDER_WITH_ENCHANT[:6],
                "recommended_runes": WR_RUNES_TEMPLATE,
                "summary": "invalid short enchant build order",
                "slot_notes": [],
            },
            context=context,
            operation_context={},
            snapshot=snapshot,
        )

    issues = exc_info.value.details["issues"]
    assert issues[0]["loc"] == ["recommended_build_order"]
    assert "exactly 7 slots" in issues[0]["msg"]


def test_validate_run_result_rejects_lol_recommend_full_build_with_enchant_step(
    configured_app,
) -> None:
    snapshot = _load_snapshot(configured_app)
    context = MatchContext(
        game=Game.LOL,
        data_version=snapshot.data_version,
        own_champion_slug="lol-ahri",
        enemy_team=[],
        own_build=[None, None, None, None, None, None],
        own_runes={"primary": [], "secondary": []},
        environment={"tags": [], "free_text": ""},
    )

    with pytest.raises(ApiError) as exc_info:
        validate_run_result(
            run_type=RunType.RECOMMEND_FULL_BUILD,
            raw_result={
                "recommended_build_order": [
                    "lol-luden-s-companion",
                    "lol-sorcerer-s-shoes",
                    "lol-enchantment-homeguard",
                    "lol-shadowflame",
                    "lol-rabadon-s-deathcap",
                    "lol-void-staff",
                ],
                "recommended_runes": {
                    "primary": ["lol-electrocute"],
                    "secondary": ["lol-manaflow-band"],
                },
                "summary": "invalid lol enchant build",
                "slot_notes": [],
            },
            context=context,
            operation_context={},
            snapshot=snapshot,
        )

    issues = exc_info.value.details["issues"]
    assert issues[0]["loc"] == ["recommended_build_order", 2]
    assert "must not include a separate enchant step" in issues[0]["msg"]
