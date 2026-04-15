import pytest
from pydantic import ValidationError

from app.domain.enums import Game, Language, RunType, TerminologyStyle
from app.domain.match_context import (
    MatchContext,
    ResponsePreferences,
    build_response_variant_hash,
    build_semantic_context_hash,
    canonicalize_environment_tags,
)


def make_match_context(*, free_text: str = "对面爆发高") -> MatchContext:
    return MatchContext(
        game=Game.LOL,
        data_version="full-20260411",
        own_champion_slug="lol-ahri",
        enemy_team=[
            {
                "champion_slug": "lol-zed",
                "build": ["lol-eclipse", None, None, None, None, None],
                "runes": {"primary": [], "secondary": []},
            },
            {
                "champion_slug": "lol-lee-sin",
                "build": [None, None, None, None, None, None],
                "runes": {"primary": [], "secondary": []},
            },
        ],
        own_build=["lol-luden-s-companion", None, None, None, None, None],
        own_runes={"primary": [], "secondary": []},
        environment={
            "tags": ["assassin-heavy", "ranked"],
            "free_text": free_text,
        },
    )


def test_environment_tags_are_sorted_and_deduplicated() -> None:
    assert canonicalize_environment_tags(["ranked", "aram", "ranked"]) == ("aram", "ranked")


def test_match_context_rejects_mismatched_slug_prefix() -> None:
    with pytest.raises(ValidationError):
        MatchContext(
            game=Game.WILD_RIFT,
            data_version="full-20260411",
            own_champion_slug="lol-ahri",
        )


def test_wild_rift_context_defaults_to_seven_build_slots() -> None:
    context = MatchContext(
        game=Game.WILD_RIFT,
        data_version="full-20260411",
        own_champion_slug="wr-ahri",
    )

    assert len(context.own_build) == 7


def test_semantic_hash_ignores_free_text_and_input_order() -> None:
    context_a = make_match_context(free_text="前期压力很大")
    context_b = MatchContext(
        game=Game.LOL,
        data_version="full-20260411",
        own_champion_slug="lol-ahri",
        enemy_team=list(reversed(context_a.enemy_team)),
        own_build=context_a.own_build,
        own_runes=context_a.own_runes.model_dump(),
        environment={"tags": ["ranked", "assassin-heavy"], "free_text": "另一段描述"},
    )

    assert build_semantic_context_hash(context_a) == build_semantic_context_hash(context_b)


def test_response_variant_hash_changes_with_language_and_run_type() -> None:
    context = make_match_context()
    zh_hash = build_response_variant_hash(
        context,
        run_type=RunType.RECOMMEND_SLOT,
        response_preferences=ResponsePreferences(
            language=Language.ZH_CN,
            terminology_style=TerminologyStyle.OFFICIAL,
        ),
        operation_context={"slot_index": 2},
    )
    en_hash = build_response_variant_hash(
        context,
        run_type=RunType.RECOMMEND_SLOT,
        response_preferences=ResponsePreferences(
            language=Language.EN,
            terminology_style=TerminologyStyle.OFFICIAL,
        ),
        operation_context={"slot_index": 2},
    )
    explain_hash = build_response_variant_hash(
        context,
        run_type=RunType.EXPLAIN_SLOT,
        response_preferences=ResponsePreferences(),
        operation_context={"slot_index": 2},
    )

    assert zh_hash != en_hash
    assert zh_hash != explain_hash
