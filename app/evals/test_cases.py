"""Test cases for the AI workflow evaluation.

Each ``_<feature>_cases`` helper returns the EvalCase list for one feature.
To add / remove a single scenario, edit only the relevant helper.

Call ``build_eval_cases(data_version)`` to get the full list.
"""

from __future__ import annotations

from app.domain.enums import Game, RunType
from app.domain.match_context import MatchContext, ResponsePreferences, build_slot_count_for_game

from app.evals.models import EvalCase, EvalSeedRun


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_eval_cases(data_version: str) -> list[EvalCase]:
    zh_official = ResponsePreferences(language="zh-CN", terminology_style="official")
    return [
        *_recommend_full_build_cases(data_version, zh_official),
        *_evaluate_build_cases(data_version, zh_official),
        *_recommend_slot_cases(data_version, zh_official),
        *_explain_slot_cases(data_version, zh_official),
        *_compare_builds_cases(data_version, zh_official),
        *_game_status_cases(data_version, zh_official),
        *_chat_followup_cases(data_version, zh_official),
    ]


# ---------------------------------------------------------------------------
# Per-feature case builders
# ---------------------------------------------------------------------------


def _recommend_full_build_cases(
    data_version: str, prefs: ResponsePreferences
) -> list[EvalCase]:
    return [
        EvalCase(
            case_key="recommend-full-build-lol-ahri-vs-zed",
            feature=RunType.RECOMMEND_FULL_BUILD,
            description="LoL mid Ahri into Zed with assassin pressure.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-ahri",
                enemy_slugs=["lol-zed"],
                own_build=_slots(Game.LOL, "lol-luden-s-companion", None, None, None, None, None),
                own_runes=_runes(
                    primary=["lol-electrocute", "lol-sudden-impact"],
                    secondary=["lol-manaflow-band", "lol-transcendence"],
                ),
                tags=["ranked", "assassin-heavy"],
            ),
            payload={},
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="recommend-full-build-lol-jinx-vs-double-frontline",
            feature=RunType.RECOMMEND_FULL_BUILD,
            description="LoL ADC Jinx into Malphite + Rammus frontline.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-jinx",
                enemy_slugs=["lol-malphite", "lol-rammus"],
                own_build=_slots(Game.LOL, None, None, None, None, None, None),
                own_runes=_runes(
                    primary=["lol-conqueror", "lol-triumph", "lol-legend-alacrity"],
                    secondary=[],
                ),
                tags=["ranked", "tank-heavy", "cc-heavy"],
            ),
            payload={},
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="recommend-full-build-lol-orianna-vs-yone-vi",
            feature=RunType.RECOMMEND_FULL_BUILD,
            description="LoL control mage facing dive from Yone and Vi.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-orianna",
                enemy_slugs=["lol-yone", "lol-vi"],
                own_build=_slots(Game.LOL, None, None, None, None, None, None),
                own_runes=_runes(
                    primary=["lol-electrocute"],
                    secondary=["lol-manaflow-band", "lol-transcendence"],
                ),
                tags=["ranked", "assassin-heavy", "cc-heavy"],
            ),
            payload={},
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="recommend-full-build-wr-lucian-vs-ashe",
            feature=RunType.RECOMMEND_FULL_BUILD,
            description="Wild Rift Lucian dragon lane into Ashe.",
            context=_context(
                game=Game.WILD_RIFT,
                data_version=data_version,
                own_champion_slug="wr-lucian",
                enemy_slugs=["wr-ashe"],
                own_build=_slots(Game.WILD_RIFT, None, None, None, None, None, None, None),
                own_runes=_runes(
                    primary=["wr-kraken-slayer", "wr-brutal", "wr-coup-de-grace"],
                    secondary=["wr-bone-plating"],
                ),
                tags=["normal"],
            ),
            payload={},
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="recommend-full-build-wr-ashe-aram",
            feature=RunType.RECOMMEND_FULL_BUILD,
            description="Wild Rift Ashe ARAM against Kai'Sa.",
            context=_context(
                game=Game.WILD_RIFT,
                data_version=data_version,
                own_champion_slug="wr-ashe",
                enemy_slugs=["wr-kai-sa"],
                own_build=_slots(Game.WILD_RIFT, None, None, None, None, None, None, None),
                own_runes=_runes(
                    primary=["wr-arcane-comet", "wr-scorch"],
                    secondary=["wr-manaflow-band"],
                ),
                tags=["aram"],
            ),
            payload={},
            response_preferences=prefs,
        ),
    ]


def _evaluate_build_cases(data_version: str, prefs: ResponsePreferences) -> list[EvalCase]:
    return [
        EvalCase(
            case_key="evaluate-build-lol-ahri-one-item-vs-zed",
            feature=RunType.EVALUATE_BUILD,
            description="Evaluate a sparse Ahri build into Zed.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-ahri",
                enemy_slugs=["lol-zed"],
                own_build=_slots(Game.LOL, "lol-luden-s-companion", None, None, None, None, None),
                own_runes=_runes(
                    primary=["lol-electrocute"],
                    secondary=["lol-manaflow-band"],
                ),
                tags=["ranked", "assassin-heavy"],
            ),
            payload={},
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="evaluate-build-lol-jinx-crit-vs-frontline",
            feature=RunType.EVALUATE_BUILD,
            description="Evaluate a mostly standard crit Jinx build into tanks.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-jinx",
                enemy_slugs=["lol-malphite", "lol-rammus"],
                own_build=_slots(
                    Game.LOL,
                    "lol-kraken-slayer",
                    "lol-berserker-s-greaves",
                    "lol-phantom-dancer",
                    None,
                    None,
                    None,
                ),
                own_runes=_runes(
                    primary=["lol-conqueror", "lol-triumph", "lol-legend-alacrity"],
                    secondary=[],
                ),
                tags=["ranked", "tank-heavy"],
            ),
            payload={},
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="evaluate-build-lol-darius-bruiser-vs-garen",
            feature=RunType.EVALUATE_BUILD,
            description="Evaluate Darius bruiser setup in a bruiser mirror.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-darius",
                enemy_slugs=["lol-garen"],
                own_build=_slots(
                    Game.LOL,
                    "lol-black-cleaver",
                    "lol-plated-steelcaps",
                    "lol-sterak-s-gage",
                    None,
                    None,
                    None,
                ),
                own_runes=_runes(
                    primary=["lol-conqueror", "lol-triumph"],
                    secondary=[],
                ),
                tags=["ranked", "early-game"],
            ),
            payload={},
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="evaluate-build-wr-ahri-three-step-vs-zed",
            feature=RunType.EVALUATE_BUILD,
            description="Evaluate a three-step Wild Rift Ahri setup into Zed.",
            context=_context(
                game=Game.WILD_RIFT,
                data_version=data_version,
                own_champion_slug="wr-ahri",
                enemy_slugs=["wr-zed"],
                own_build=_slots(
                    Game.WILD_RIFT,
                    "wr-luden-s-echo",
                    "wr-ionian-boots-of-lucidity",
                    "wr-stasis-enchant",
                    None,
                    None,
                    None,
                    None,
                ),
                own_runes=_runes(
                    primary=["wr-electrocute", "wr-brutal"],
                    secondary=["wr-bone-plating"],
                ),
                tags=["ranked", "assassin-heavy"],
            ),
            payload={},
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="evaluate-build-wr-lucian-four-step-vs-ashe",
            feature=RunType.EVALUATE_BUILD,
            description="Evaluate Wild Rift Lucian lane build against Ashe poke.",
            context=_context(
                game=Game.WILD_RIFT,
                data_version=data_version,
                own_champion_slug="wr-lucian",
                enemy_slugs=["wr-ashe"],
                own_build=_slots(
                    Game.WILD_RIFT,
                    "wr-essence-reaver",
                    "wr-gluttonous-greaves",
                    "wr-navori-quickblades",
                    "wr-stasis-enchant",
                    None,
                    None,
                    None,
                ),
                own_runes=_runes(
                    primary=["wr-kraken-slayer", "wr-brutal", "wr-coup-de-grace"],
                    secondary=["wr-bone-plating"],
                ),
                tags=["normal"],
            ),
            payload={},
            response_preferences=prefs,
        ),
    ]


def _recommend_slot_cases(data_version: str, prefs: ResponsePreferences) -> list[EvalCase]:
    return [
        EvalCase(
            case_key="recommend-slot-lol-ahri-second-slot-vs-zed",
            feature=RunType.RECOMMEND_SLOT,
            description="Recommend Ahri slot 2 after Luden into Zed.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-ahri",
                enemy_slugs=["lol-zed"],
                own_build=_slots(Game.LOL, "lol-luden-s-companion", None, None, None, None, None),
                own_runes=_runes(
                    primary=["lol-electrocute"],
                    secondary=["lol-manaflow-band"],
                ),
                tags=["ranked", "assassin-heavy"],
            ),
            payload={"slot_index": 1},
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="recommend-slot-lol-jinx-third-slot-vs-frontline",
            feature=RunType.RECOMMEND_SLOT,
            description="Recommend Jinx third slot into heavy frontline.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-jinx",
                enemy_slugs=["lol-malphite", "lol-rammus"],
                own_build=_slots(
                    Game.LOL,
                    "lol-kraken-slayer",
                    "lol-berserker-s-greaves",
                    None,
                    None,
                    None,
                    None,
                ),
                own_runes=_runes(
                    primary=["lol-conqueror", "lol-triumph"],
                    secondary=[],
                ),
                tags=["ranked", "tank-heavy"],
            ),
            payload={"slot_index": 2},
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="recommend-slot-lol-orianna-third-slot-vs-dive",
            feature=RunType.RECOMMEND_SLOT,
            description="Recommend Orianna third slot into dive comp.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-orianna",
                enemy_slugs=["lol-yone", "lol-vi"],
                own_build=_slots(
                    Game.LOL,
                    "lol-luden-s-companion",
                    "lol-zhonya-s-hourglass",
                    None,
                    None,
                    None,
                    None,
                ),
                own_runes=_runes(
                    primary=["lol-electrocute"],
                    secondary=["lol-transcendence"],
                ),
                tags=["ranked", "assassin-heavy", "cc-heavy"],
            ),
            payload={"slot_index": 2},
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="recommend-slot-wr-lucian-fourth-step-vs-ashe",
            feature=RunType.RECOMMEND_SLOT,
            description="Recommend Lucian fourth step after ER + boots + Navori.",
            context=_context(
                game=Game.WILD_RIFT,
                data_version=data_version,
                own_champion_slug="wr-lucian",
                enemy_slugs=["wr-ashe"],
                own_build=_slots(
                    Game.WILD_RIFT,
                    "wr-essence-reaver",
                    "wr-gluttonous-greaves",
                    "wr-navori-quickblades",
                    None,
                    None,
                    None,
                    None,
                ),
                own_runes=_runes(
                    primary=["wr-kraken-slayer", "wr-brutal"],
                    secondary=[],
                ),
                tags=["normal"],
            ),
            payload={"slot_index": 3},
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="recommend-slot-wr-ahri-fifth-step-vs-zed",
            feature=RunType.RECOMMEND_SLOT,
            description="Recommend Ahri fifth step in Wild Rift into Zed.",
            context=_context(
                game=Game.WILD_RIFT,
                data_version=data_version,
                own_champion_slug="wr-ahri",
                enemy_slugs=["wr-zed"],
                own_build=_slots(
                    Game.WILD_RIFT,
                    "wr-luden-s-echo",
                    "wr-ionian-boots-of-lucidity",
                    "wr-infinity-orb",
                    "wr-stasis-enchant",
                    None,
                    None,
                    None,
                ),
                own_runes=_runes(
                    primary=["wr-electrocute", "wr-brutal"],
                    secondary=["wr-bone-plating"],
                ),
                tags=["ranked", "assassin-heavy"],
            ),
            payload={"slot_index": 4},
            response_preferences=prefs,
        ),
    ]


def _explain_slot_cases(data_version: str, prefs: ResponsePreferences) -> list[EvalCase]:
    return [
        EvalCase(
            case_key="explain-slot-lol-ahri-second-slot-current-shadowflame",
            feature=RunType.EXPLAIN_SLOT,
            description="Explain whether Shadowflame is okay before defense into Zed.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-ahri",
                enemy_slugs=["lol-zed"],
                own_build=_slots(
                    Game.LOL,
                    "lol-luden-s-companion",
                    "lol-shadowflame",
                    None,
                    None,
                    None,
                    None,
                ),
                own_runes=_runes(
                    primary=["lol-electrocute"],
                    secondary=["lol-manaflow-band"],
                ),
                tags=["ranked", "assassin-heavy"],
            ),
            payload={"slot_index": 1},
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="explain-slot-lol-jinx-fourth-slot-current-bloodthirster",
            feature=RunType.EXPLAIN_SLOT,
            description="Explain Jinx fourth slot choice into tank comp.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-jinx",
                enemy_slugs=["lol-malphite", "lol-rammus"],
                own_build=_slots(
                    Game.LOL,
                    "lol-kraken-slayer",
                    "lol-berserker-s-greaves",
                    "lol-phantom-dancer",
                    "lol-bloodthirster",
                    None,
                    None,
                ),
                own_runes=_runes(
                    primary=["lol-conqueror", "lol-triumph"],
                    secondary=[],
                ),
                tags=["ranked", "tank-heavy"],
            ),
            payload={"slot_index": 3},
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="explain-slot-lol-orianna-third-slot-current-banshee",
            feature=RunType.EXPLAIN_SLOT,
            description="Explain an early Banshee purchase on Orianna.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-orianna",
                enemy_slugs=["lol-yone", "lol-vi"],
                own_build=_slots(
                    Game.LOL,
                    "lol-luden-s-companion",
                    "lol-zhonya-s-hourglass",
                    "lol-banshee-s-veil",
                    None,
                    None,
                    None,
                ),
                own_runes=_runes(
                    primary=["lol-electrocute"],
                    secondary=["lol-transcendence"],
                ),
                tags=["ranked", "assassin-heavy", "cc-heavy"],
            ),
            payload={"slot_index": 2},
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="explain-slot-wr-lucian-fourth-step-current-stasis",
            feature=RunType.EXPLAIN_SLOT,
            description="Explain whether Lucian should enchant early against Ashe.",
            context=_context(
                game=Game.WILD_RIFT,
                data_version=data_version,
                own_champion_slug="wr-lucian",
                enemy_slugs=["wr-ashe"],
                own_build=_slots(
                    Game.WILD_RIFT,
                    "wr-essence-reaver",
                    "wr-gluttonous-greaves",
                    "wr-navori-quickblades",
                    "wr-stasis-enchant",
                    None,
                    None,
                    None,
                ),
                own_runes=_runes(
                    primary=["wr-kraken-slayer", "wr-brutal"],
                    secondary=["wr-bone-plating"],
                ),
                tags=["normal"],
            ),
            payload={"slot_index": 3},
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="explain-slot-wr-ashe-third-step-current-manamune",
            feature=RunType.EXPLAIN_SLOT,
            description="Explain ARAM Ashe third step after a poke opening.",
            context=_context(
                game=Game.WILD_RIFT,
                data_version=data_version,
                own_champion_slug="wr-ashe",
                enemy_slugs=["wr-kai-sa"],
                own_build=_slots(
                    Game.WILD_RIFT,
                    "wr-imperial-mandate",
                    "wr-ionian-boots-of-lucidity",
                    "wr-manamune",
                    None,
                    None,
                    None,
                    None,
                ),
                own_runes=_runes(
                    primary=["wr-arcane-comet", "wr-scorch"],
                    secondary=["wr-manaflow-band"],
                ),
                tags=["aram", "poke-heavy"],
            ),
            payload={"slot_index": 2},
            response_preferences=prefs,
        ),
    ]


def _compare_builds_cases(data_version: str, prefs: ResponsePreferences) -> list[EvalCase]:
    return [
        EvalCase(
            case_key="compare-builds-lol-ahri-defense-vs-greed",
            feature=RunType.COMPARE_BUILDS,
            description="Compare defensive Ahri second item against greedier damage path.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-ahri",
                enemy_slugs=["lol-zed"],
                own_build=_slots(
                    Game.LOL,
                    "lol-luden-s-companion",
                    "lol-zhonya-s-hourglass",
                    "lol-shadowflame",
                    None,
                    None,
                    None,
                ),
                own_runes=_runes(
                    primary=["lol-electrocute"],
                    secondary=["lol-manaflow-band"],
                ),
                tags=["ranked", "assassin-heavy"],
            ),
            payload={
                "comparison_context": {
                    "own_build": _slots(
                        Game.LOL,
                        "lol-luden-s-companion",
                        "lol-shadowflame",
                        "lol-zhonya-s-hourglass",
                        None,
                        None,
                        None,
                    ),
                    "own_runes": {
                        "primary": ["lol-electrocute"],
                        "secondary": ["lol-manaflow-band"],
                    },
                }
            },
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="compare-builds-lol-jinx-ie-vs-lifesteal-third",
            feature=RunType.COMPARE_BUILDS,
            description="Compare Jinx third-item Infinity Edge vs Bloodthirster timing.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-jinx",
                enemy_slugs=["lol-malphite", "lol-rammus"],
                own_build=_slots(
                    Game.LOL,
                    "lol-kraken-slayer",
                    "lol-berserker-s-greaves",
                    "lol-infinity-edge",
                    None,
                    None,
                    None,
                ),
                own_runes=_runes(
                    primary=["lol-conqueror", "lol-triumph"],
                    secondary=[],
                ),
                tags=["ranked", "tank-heavy"],
            ),
            payload={
                "comparison_context": {
                    "own_build": _slots(
                        Game.LOL,
                        "lol-kraken-slayer",
                        "lol-berserker-s-greaves",
                        "lol-bloodthirster",
                        None,
                        None,
                        None,
                    ),
                    "own_runes": {
                        "primary": ["lol-conqueror", "lol-triumph"],
                        "secondary": [],
                    },
                }
            },
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="compare-builds-lol-orianna-double-defense-vs-damage-third",
            feature=RunType.COMPARE_BUILDS,
            description="Compare safer Orianna third item against greedier AP spike.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-orianna",
                enemy_slugs=["lol-yone", "lol-vi"],
                own_build=_slots(
                    Game.LOL,
                    "lol-luden-s-companion",
                    "lol-zhonya-s-hourglass",
                    "lol-banshee-s-veil",
                    None,
                    None,
                    None,
                ),
                own_runes=_runes(
                    primary=["lol-electrocute"],
                    secondary=["lol-transcendence"],
                ),
                tags=["ranked", "assassin-heavy", "cc-heavy"],
            ),
            payload={
                "comparison_context": {
                    "own_build": _slots(
                        Game.LOL,
                        "lol-luden-s-companion",
                        "lol-zhonya-s-hourglass",
                        "lol-shadowflame",
                        None,
                        None,
                        None,
                    ),
                    "own_runes": {
                        "primary": ["lol-electrocute"],
                        "secondary": ["lol-transcendence"],
                    },
                }
            },
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="compare-builds-wr-lucian-stasis-early-vs-late",
            feature=RunType.COMPARE_BUILDS,
            description="Compare early Lucian enchant timing in Wild Rift.",
            context=_context(
                game=Game.WILD_RIFT,
                data_version=data_version,
                own_champion_slug="wr-lucian",
                enemy_slugs=["wr-ashe"],
                own_build=_slots(
                    Game.WILD_RIFT,
                    "wr-essence-reaver",
                    "wr-gluttonous-greaves",
                    "wr-navori-quickblades",
                    "wr-stasis-enchant",
                    "wr-infinity-edge",
                    None,
                    None,
                ),
                own_runes=_runes(
                    primary=["wr-kraken-slayer", "wr-brutal"],
                    secondary=["wr-bone-plating"],
                ),
                tags=["normal"],
            ),
            payload={
                "comparison_context": {
                    "own_build": _slots(
                        Game.WILD_RIFT,
                        "wr-essence-reaver",
                        "wr-gluttonous-greaves",
                        "wr-navori-quickblades",
                        "wr-infinity-edge",
                        "wr-stasis-enchant",
                        None,
                        None,
                    ),
                    "own_runes": {
                        "primary": ["wr-kraken-slayer", "wr-brutal"],
                        "secondary": ["wr-bone-plating"],
                    },
                }
            },
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="compare-builds-wr-ahri-penetration-vs-crown",
            feature=RunType.COMPARE_BUILDS,
            description="Compare Wild Rift Ahri pen-first vs safety-first sequencing.",
            context=_context(
                game=Game.WILD_RIFT,
                data_version=data_version,
                own_champion_slug="wr-ahri",
                enemy_slugs=["wr-zed"],
                own_build=_slots(
                    Game.WILD_RIFT,
                    "wr-luden-s-echo",
                    "wr-ionian-boots-of-lucidity",
                    "wr-infinity-orb",
                    "wr-stasis-enchant",
                    "wr-rabadon-s-deathcap",
                    None,
                    None,
                ),
                own_runes=_runes(
                    primary=["wr-electrocute", "wr-brutal"],
                    secondary=["wr-bone-plating"],
                ),
                tags=["ranked", "assassin-heavy"],
            ),
            payload={
                "comparison_context": {
                    "own_build": _slots(
                        Game.WILD_RIFT,
                        "wr-luden-s-echo",
                        "wr-ionian-boots-of-lucidity",
                        "wr-crown-of-the-shattered-queen",
                        "wr-stasis-enchant",
                        "wr-infinity-orb",
                        None,
                        None,
                    ),
                    "own_runes": {
                        "primary": ["wr-electrocute", "wr-brutal"],
                        "secondary": ["wr-bone-plating"],
                    },
                }
            },
            response_preferences=prefs,
        ),
    ]


def _game_status_cases(data_version: str, prefs: ResponsePreferences) -> list[EvalCase]:
    return [
        EvalCase(
            case_key="game-status-lol-ahri-vs-zed",
            feature=RunType.GAME_STATUS,
            description="Estimate kill cadence and push speed for Ahri into Zed.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-ahri",
                enemy_slugs=["lol-zed"],
                own_build=_slots(Game.LOL, "lol-luden-s-companion", None, None, None, None, None),
                own_runes=_runes(
                    primary=["lol-electrocute"],
                    secondary=["lol-manaflow-band"],
                ),
                tags=["ranked", "assassin-heavy"],
            ),
            payload={},
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="game-status-lol-jinx-vs-frontline",
            feature=RunType.GAME_STATUS,
            description="Estimate Jinx kill cadence and push speed into Malphite + Rammus.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-jinx",
                enemy_slugs=["lol-malphite", "lol-rammus"],
                own_build=_slots(
                    Game.LOL,
                    "lol-kraken-slayer",
                    "lol-berserker-s-greaves",
                    None,
                    None,
                    None,
                    None,
                ),
                own_runes=_runes(
                    primary=["lol-conqueror", "lol-triumph", "lol-legend-alacrity"],
                    secondary=[],
                ),
                tags=["ranked", "tank-heavy"],
            ),
            payload={},
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="game-status-lol-darius-vs-garen",
            feature=RunType.GAME_STATUS,
            description="Estimate Darius duel cadence and tower pressure into Garen.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-darius",
                enemy_slugs=["lol-garen"],
                own_build=_slots(
                    Game.LOL,
                    "lol-black-cleaver",
                    "lol-plated-steelcaps",
                    None,
                    None,
                    None,
                    None,
                ),
                own_runes=_runes(
                    primary=["lol-conqueror", "lol-triumph"],
                    secondary=[],
                ),
                tags=["normal", "early-game"],
            ),
            payload={},
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="game-status-wr-lucian-vs-ashe",
            feature=RunType.GAME_STATUS,
            description="Estimate Wild Rift Lucian status into Ashe.",
            context=_context(
                game=Game.WILD_RIFT,
                data_version=data_version,
                own_champion_slug="wr-lucian",
                enemy_slugs=["wr-ashe"],
                own_build=_slots(Game.WILD_RIFT, "wr-essence-reaver", None, None, None, None, None, None),
                own_runes=_runes(
                    primary=["wr-kraken-slayer", "wr-brutal"],
                    secondary=["wr-bone-plating"],
                ),
                tags=["normal"],
            ),
            payload={},
            response_preferences=prefs,
        ),
        EvalCase(
            case_key="game-status-wr-ashe-aram",
            feature=RunType.GAME_STATUS,
            description="Estimate ARAM Ashe status into Kai'Sa.",
            context=_context(
                game=Game.WILD_RIFT,
                data_version=data_version,
                own_champion_slug="wr-ashe",
                enemy_slugs=["wr-kai-sa"],
                own_build=_slots(Game.WILD_RIFT, "wr-manamune", None, None, None, None, None, None),
                own_runes=_runes(
                    primary=["wr-arcane-comet", "wr-scorch"],
                    secondary=["wr-manaflow-band"],
                ),
                tags=["aram"],
            ),
            payload={},
            response_preferences=prefs,
        ),
    ]


def _chat_followup_cases(data_version: str, prefs: ResponsePreferences) -> list[EvalCase]:
    return [
        EvalCase(
            case_key="chat-followup-lol-ahri-zed-why-zhonya",
            feature=RunType.CHAT_FOLLOWUP,
            description="Ask why Ahri should rush Zhonya into Zed.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-ahri",
                enemy_slugs=["lol-zed"],
                own_build=_slots(Game.LOL, "lol-luden-s-companion", None, None, None, None, None),
                own_runes=_runes(
                    primary=["lol-electrocute"],
                    secondary=["lol-manaflow-band"],
                ),
                tags=["ranked", "assassin-heavy"],
            ),
            payload={"user_message": "为什么这局第二件更适合先出中娅，而不是继续补纯法强？"},
            response_preferences=prefs,
            reply_seed=EvalSeedRun(run_type=RunType.RECOMMEND_FULL_BUILD, payload={}),
        ),
        EvalCase(
            case_key="chat-followup-lol-jinx-frontline-third-item",
            feature=RunType.CHAT_FOLLOWUP,
            description="Ask Jinx follow-up about third item into tanks.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-jinx",
                enemy_slugs=["lol-malphite", "lol-rammus"],
                own_build=_slots(Game.LOL, None, None, None, None, None, None),
                own_runes=_runes(
                    primary=["lol-conqueror", "lol-triumph"],
                    secondary=[],
                ),
                tags=["ranked", "tank-heavy"],
            ),
            payload={"user_message": "如果我这局第三件想更早打得动前排，应该优先补什么？"},
            response_preferences=prefs,
            reply_seed=EvalSeedRun(run_type=RunType.RECOMMEND_FULL_BUILD, payload={}),
        ),
        EvalCase(
            case_key="chat-followup-lol-orianna-dive-defense",
            feature=RunType.CHAT_FOLLOWUP,
            description="Ask Orianna follow-up about double-defense sequencing.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-orianna",
                enemy_slugs=["lol-yone", "lol-vi"],
                own_build=_slots(Game.LOL, None, None, None, None, None, None),
                own_runes=_runes(
                    primary=["lol-electrocute"],
                    secondary=["lol-transcendence"],
                ),
                tags=["ranked", "assassin-heavy", "cc-heavy"],
            ),
            payload={"user_message": "如果我对自己操作比较有信心，还需要这么早补两件防装吗？"},
            response_preferences=prefs,
            reply_seed=EvalSeedRun(run_type=RunType.RECOMMEND_FULL_BUILD, payload={}),
        ),
        EvalCase(
            case_key="chat-followup-wr-lucian-ashe-enchant-timing",
            feature=RunType.CHAT_FOLLOWUP,
            description="Ask Lucian follow-up about the timing of stasis enchant.",
            context=_context(
                game=Game.WILD_RIFT,
                data_version=data_version,
                own_champion_slug="wr-lucian",
                enemy_slugs=["wr-ashe"],
                own_build=_slots(Game.WILD_RIFT, None, None, None, None, None, None, None),
                own_runes=_runes(
                    primary=["wr-kraken-slayer", "wr-brutal"],
                    secondary=["wr-bone-plating"],
                ),
                tags=["normal"],
            ),
            payload={"user_message": "这局金身附魔为什么不放到更后面再做？"},
            response_preferences=prefs,
            reply_seed=EvalSeedRun(run_type=RunType.RECOMMEND_FULL_BUILD, payload={}),
        ),
        EvalCase(
            case_key="chat-followup-wr-ashe-aram-poke-vs-adc",
            feature=RunType.CHAT_FOLLOWUP,
            description="Ask Ashe ARAM follow-up about poke vs ADC direction.",
            context=_context(
                game=Game.WILD_RIFT,
                data_version=data_version,
                own_champion_slug="wr-ashe",
                enemy_slugs=["wr-kai-sa"],
                own_build=_slots(Game.WILD_RIFT, None, None, None, None, None, None, None),
                own_runes=_runes(
                    primary=["wr-arcane-comet", "wr-scorch"],
                    secondary=["wr-manaflow-band"],
                ),
                tags=["aram", "poke-heavy"],
            ),
            payload={"user_message": "如果我更想打持续输出，而不是纯消耗，这套思路要怎么改？"},
            response_preferences=prefs,
            reply_seed=EvalSeedRun(run_type=RunType.RECOMMEND_FULL_BUILD, payload={}),
        ),
    ]


# ---------------------------------------------------------------------------
# Context / slot / rune builder helpers
# ---------------------------------------------------------------------------


def _context(
    *,
    game: Game,
    data_version: str,
    own_champion_slug: str,
    enemy_slugs: list[str],
    own_build: list[str | None],
    own_runes: dict[str, list[str]],
    tags: list[str],
    free_text: str = "",
) -> MatchContext:
    return MatchContext(
        game=game,
        data_version=data_version,
        own_champion_slug=own_champion_slug,
        enemy_team=[
            {
                "champion_slug": slug,
                "build": [None] * build_slot_count_for_game(game),
                "runes": {"primary": [], "secondary": []},
            }
            for slug in enemy_slugs
        ],
        own_build=own_build,
        own_runes=own_runes,
        environment={"tags": tags, "free_text": free_text},
    )


def _slots(game: Game, *entries: str | None) -> list[str | None]:
    """Build a build-slot list, enforcing the correct slot count for *game*."""
    slot_count = build_slot_count_for_game(game)
    if len(entries) != slot_count:
        raise ValueError(f"{game.value} requires exactly {slot_count} slots.")
    return list(entries)


def _runes(*, primary: list[str], secondary: list[str]) -> dict[str, list[str]]:
    return {"primary": primary, "secondary": secondary}
