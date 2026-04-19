from app.ai.graphs.nodes import _sanitize_tool_call
from app.domain.match_context import MatchContext


def _load_snapshot(configured_app):
    session = configured_app.state.session_factory()
    version = configured_app.state.data_version_service.get_active_version(session)
    snapshot = configured_app.state.game_data_registry.get_or_load(
        data_version=version.data_version,
        source_root=version.source_root,
    )
    session.close()
    return snapshot


def test_list_catalog_candidates_sanitizer_fills_game_and_maps_tags_to_keywords(
    configured_app,
) -> None:
    snapshot = _load_snapshot(configured_app)
    context = MatchContext(
        game="wild_rift",
        data_version=snapshot.data_version,
        own_champion_slug="wr-heimerdinger",
        enemy_team=[],
        own_build=[None, None, None, None, None, None, None],
        own_runes={"primary": [], "secondary": []},
        environment={"tags": ["aram"], "free_text": ""},
    )

    sanitized = _sanitize_tool_call(
        tool_call={
            "tool_name": "list_catalog_candidates",
            "arguments": {
                "entity_type": "item",
                "tags": ["magic"],
            },
        },
        context=context,
        snapshot=snapshot,
    )

    assert sanitized == {
        "tool_name": "list_catalog_candidates",
        "arguments": {
            "game": "wild_rift",
            "entity_type": "item",
            "filters": {
                "keywords": ["magic"],
            },
        },
    }


def test_resolve_catalog_slug_sanitizer_accepts_nested_tags_without_explicit_game(
    configured_app,
) -> None:
    snapshot = _load_snapshot(configured_app)
    context = MatchContext(
        game="wild_rift",
        data_version=snapshot.data_version,
        own_champion_slug="wr-heimerdinger",
        enemy_team=[],
        own_build=[None, None, None, None, None, None, None],
        own_runes={"primary": [], "secondary": []},
        environment={"tags": ["aram"], "free_text": ""},
    )

    sanitized = _sanitize_tool_call(
        tool_call={
            "tool_name": "resolve_catalog_slug",
            "arguments": {
                "entity_type": "rune",
                "raw_name": "法力流系带",
                "filters": {
                    "tags": ["mana"],
                },
            },
        },
        context=context,
        snapshot=snapshot,
    )

    assert sanitized == {
        "tool_name": "resolve_catalog_slug",
        "arguments": {
            "game": "wild_rift",
            "entity_type": "rune",
            "raw_name": "法力流系带",
            "filters": {
                "keywords": ["mana"],
            },
        },
    }


def test_list_item_ids_sanitizer_accepts_kind_alias_without_explicit_game(
    configured_app,
) -> None:
    snapshot = _load_snapshot(configured_app)
    context = MatchContext(
        game="wild_rift",
        data_version=snapshot.data_version,
        own_champion_slug="wr-heimerdinger",
        enemy_team=[],
        own_build=[None, None, None, None, None, None, None],
        own_runes={"primary": [], "secondary": []},
        environment={"tags": ["aram"], "free_text": ""},
    )

    sanitized = _sanitize_tool_call(
        tool_call={
            "tool_name": "list_item_ids",
            "arguments": {
                "kind": "magic",
            },
        },
        context=context,
        snapshot=snapshot,
    )

    assert sanitized == {
        "tool_name": "list_item_ids",
        "arguments": {
            "game": "wild_rift",
            "category": "magic",
        },
    }
