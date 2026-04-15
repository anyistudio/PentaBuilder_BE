from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.domain.enums import Game, RunType
from app.domain.match_context import MatchContext, ResponsePreferences, build_slot_count_for_game
from app.main import create_app


@dataclass(frozen=True)
class EvalModelRef:
    provider_name: str
    model_name: str

    @property
    def label(self) -> str:
        return f"{self.provider_name}/{self.model_name}"


@dataclass(frozen=True)
class EvalSeedRun:
    run_type: RunType
    payload: dict[str, Any]


@dataclass(frozen=True)
class EvalCase:
    case_key: str
    feature: RunType
    description: str
    context: MatchContext
    payload: dict[str, Any]
    response_preferences: ResponsePreferences
    reply_seed: EvalSeedRun | None = None


def default_model_refs(settings: Settings) -> list[EvalModelRef]:
    if settings.all_models_list:
        return _parse_model_ref_strings(settings.all_models_list)

    ordered_refs = [
        EvalModelRef(settings.primary_reasoning_provider, settings.primary_reasoning_model),
        EvalModelRef(settings.fast_reasoning_provider, settings.fast_reasoning_model),
    ]
    if settings.openai_api_key.get_secret_value() not in {"", "replace-me"}:
        ordered_refs.extend(
            [
                EvalModelRef("openai", "gpt-4.1"),
                EvalModelRef("openai", "gpt-4.1-mini"),
            ]
        )

    unique_refs: list[EvalModelRef] = []
    seen: set[tuple[str, str]] = set()
    for ref in ordered_refs:
        key = (ref.provider_name, ref.model_name)
        if key in seen:
            continue
        seen.add(key)
        unique_refs.append(ref)
    return unique_refs


def parse_model_refs(model_args: list[str] | None, settings: Settings) -> list[EvalModelRef]:
    if not model_args:
        refs = default_model_refs(settings)
        if not refs:
            raise ValueError("No evaluation models are configured.")
        return refs

    return _parse_model_ref_strings(model_args)


def _parse_model_ref_strings(model_args: list[str]) -> list[EvalModelRef]:
    refs: list[EvalModelRef] = []
    for raw_ref in model_args:
        provider_name, separator, model_name = raw_ref.partition(":")
        provider_name = provider_name.strip()
        model_name = model_name.strip()
        if separator != ":" or not provider_name or not model_name:
            raise ValueError(
                f"Invalid model reference {raw_ref!r}. Use the format provider:model_name."
        )
        refs.append(EvalModelRef(provider_name=provider_name, model_name=model_name))

    unique_refs: list[EvalModelRef] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        key = (ref.provider_name, ref.model_name)
        if key in seen:
            continue
        seen.add(key)
        unique_refs.append(ref)
    return unique_refs


def build_eval_cases(data_version: str) -> list[EvalCase]:
    zh_official = ResponsePreferences(language="zh-CN", terminology_style="official")

    cases = [
        EvalCase(
            case_key="recommend-full-build-lol-ahri-vs-zed",
            feature=RunType.RECOMMEND_FULL_BUILD,
            description="LoL mid Ahri into Zed with assassin pressure.",
            context=_context(
                game=Game.LOL,
                data_version=data_version,
                own_champion_slug="lol-ahri",
                enemy_slugs=["lol-zed"],
                own_build=_slots(
                    Game.LOL,
                    "lol-luden-s-companion",
                    None,
                    None,
                    None,
                    None,
                    None,
                ),
                own_runes=_runes(
                    primary=["lol-electrocute", "lol-sudden-impact"],
                    secondary=["lol-manaflow-band", "lol-transcendence"],
                ),
                tags=["ranked", "assassin-heavy"],
            ),
            payload={},
            response_preferences=zh_official,
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
            response_preferences=zh_official,
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
            response_preferences=zh_official,
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
            response_preferences=zh_official,
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
            response_preferences=zh_official,
        ),
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
                own_runes=_runes(primary=["lol-electrocute"], secondary=["lol-manaflow-band"]),
                tags=["ranked", "assassin-heavy"],
            ),
            payload={},
            response_preferences=zh_official,
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
            response_preferences=zh_official,
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
                own_runes=_runes(primary=["lol-conqueror", "lol-triumph"], secondary=[]),
                tags=["ranked", "early-game"],
            ),
            payload={},
            response_preferences=zh_official,
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
            response_preferences=zh_official,
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
            response_preferences=zh_official,
        ),
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
                own_runes=_runes(primary=["lol-electrocute"], secondary=["lol-manaflow-band"]),
                tags=["ranked", "assassin-heavy"],
            ),
            payload={"slot_index": 1},
            response_preferences=zh_official,
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
                own_runes=_runes(primary=["lol-conqueror", "lol-triumph"], secondary=[]),
                tags=["ranked", "tank-heavy"],
            ),
            payload={"slot_index": 2},
            response_preferences=zh_official,
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
                own_runes=_runes(primary=["lol-electrocute"], secondary=["lol-transcendence"]),
                tags=["ranked", "assassin-heavy", "cc-heavy"],
            ),
            payload={"slot_index": 2},
            response_preferences=zh_official,
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
                own_runes=_runes(primary=["wr-kraken-slayer", "wr-brutal"], secondary=[]),
                tags=["normal"],
            ),
            payload={"slot_index": 3},
            response_preferences=zh_official,
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
                    primary=["wr-electrocute", "wr-brutal"], secondary=["wr-bone-plating"]
                ),
                tags=["ranked", "assassin-heavy"],
            ),
            payload={"slot_index": 4},
            response_preferences=zh_official,
        ),
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
                own_runes=_runes(primary=["lol-electrocute"], secondary=["lol-manaflow-band"]),
                tags=["ranked", "assassin-heavy"],
            ),
            payload={"slot_index": 1},
            response_preferences=zh_official,
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
                own_runes=_runes(primary=["lol-conqueror", "lol-triumph"], secondary=[]),
                tags=["ranked", "tank-heavy"],
            ),
            payload={"slot_index": 3},
            response_preferences=zh_official,
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
                own_runes=_runes(primary=["lol-electrocute"], secondary=["lol-transcendence"]),
                tags=["ranked", "assassin-heavy", "cc-heavy"],
            ),
            payload={"slot_index": 2},
            response_preferences=zh_official,
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
                    primary=["wr-kraken-slayer", "wr-brutal"], secondary=["wr-bone-plating"]
                ),
                tags=["normal"],
            ),
            payload={"slot_index": 3},
            response_preferences=zh_official,
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
                    primary=["wr-arcane-comet", "wr-scorch"], secondary=["wr-manaflow-band"]
                ),
                tags=["aram", "poke-heavy"],
            ),
            payload={"slot_index": 2},
            response_preferences=zh_official,
        ),
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
                own_runes=_runes(primary=["lol-electrocute"], secondary=["lol-manaflow-band"]),
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
            response_preferences=zh_official,
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
                own_runes=_runes(primary=["lol-conqueror", "lol-triumph"], secondary=[]),
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
                    "own_runes": {"primary": ["lol-conqueror", "lol-triumph"], "secondary": []},
                }
            },
            response_preferences=zh_official,
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
                own_runes=_runes(primary=["lol-electrocute"], secondary=["lol-transcendence"]),
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
            response_preferences=zh_official,
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
                    primary=["wr-kraken-slayer", "wr-brutal"], secondary=["wr-bone-plating"]
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
            response_preferences=zh_official,
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
                    primary=["wr-electrocute", "wr-brutal"], secondary=["wr-bone-plating"]
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
            response_preferences=zh_official,
        ),
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
                own_runes=_runes(primary=["lol-electrocute"], secondary=["lol-manaflow-band"]),
                tags=["ranked", "assassin-heavy"],
            ),
            payload={"user_message": "为什么这局第二件更适合先出中娅，而不是继续补纯法强？"},
            response_preferences=zh_official,
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
                own_runes=_runes(primary=["lol-conqueror", "lol-triumph"], secondary=[]),
                tags=["ranked", "tank-heavy"],
            ),
            payload={"user_message": "如果我这局第三件想更早打得动前排，应该优先补什么？"},
            response_preferences=zh_official,
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
                own_runes=_runes(primary=["lol-electrocute"], secondary=["lol-transcendence"]),
                tags=["ranked", "assassin-heavy", "cc-heavy"],
            ),
            payload={"user_message": "如果我对自己操作比较有信心，还需要这么早补两件防装吗？"},
            response_preferences=zh_official,
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
                    primary=["wr-kraken-slayer", "wr-brutal"], secondary=["wr-bone-plating"]
                ),
                tags=["normal"],
            ),
            payload={"user_message": "这局金身附魔为什么不放到更后面再做？"},
            response_preferences=zh_official,
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
                    primary=["wr-arcane-comet", "wr-scorch"], secondary=["wr-manaflow-band"]
                ),
                tags=["aram", "poke-heavy"],
            ),
            payload={"user_message": "如果我更想打持续输出，而不是纯消耗，这套思路要怎么改？"},
            response_preferences=zh_official,
            reply_seed=EvalSeedRun(run_type=RunType.RECOMMEND_FULL_BUILD, payload={}),
        ),
    ]
    return cases


def run_local_workflow_eval(
    *,
    session_factory: sessionmaker[Session],
    ai_run_service,
    data_version: str,
    model_refs: list[EvalModelRef],
    output_path: Path,
    feature_filter: set[RunType] | None = None,
) -> dict[str, Any]:
    cases = build_eval_cases(data_version)
    if feature_filter:
        cases = [case for case in cases if case.feature in feature_filter]
    results: list[dict[str, Any]] = []

    for model_ref in model_refs:
        for case in cases:
            record = _run_one_case(
                session_factory=session_factory,
                ai_run_service=ai_run_service,
                case=case,
                model_ref=model_ref,
            )
            results.append(record)

    report = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "data_version": data_version,
        "models": [
            {"provider_name": ref.provider_name, "model_name": ref.model_name, "label": ref.label}
            for ref in model_refs
        ],
        "summary": _summarize_results(results),
        "results": results,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_markdown_report(report), encoding="utf-8")
    return report


def render_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# AI Workflow Evaluation Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Data version: `{report['data_version']}`",
        f"- Models: {', '.join(model['label'] for model in report['models'])}",
        "",
        "## Average Latency by Feature and Model",
        "",
        "| Feature | Model | Success | Avg latency (ms) |",
        "| --- | --- | --- | ---: |",
    ]

    for summary in report["summary"]["feature_model_summaries"]:
        lines.append(
            f"| `{summary['feature']}` | `{summary['model_label']}` | "
            f"{summary['completed_count']}/{summary['total_count']} | "
            f"{summary['avg_latency_ms'] if summary['avg_latency_ms'] is not None else '-'} |"
        )

    lines.extend(["", "## Per Case Results", ""])

    results_by_feature: dict[str, list[dict[str, Any]]] = {}
    for record in report["results"]:
        results_by_feature.setdefault(record["feature"], []).append(record)

    for feature in [run_type.value for run_type in RunType]:
        feature_records = results_by_feature.get(feature, [])
        if not feature_records:
            continue
        lines.extend([f"### `{feature}`", ""])
        cases_by_key: dict[str, list[dict[str, Any]]] = {}
        for record in feature_records:
            cases_by_key.setdefault(record["case_key"], []).append(record)
        for case_key, case_records in cases_by_key.items():
            first = case_records[0]
            lines.extend(
                [
                    f"#### `{case_key}`",
                    "",
                    f"- Description: {first['description']}",
                    f"- Context: {first['context_brief']}",
                    "",
                ]
            )
            if first.get("payload"):
                lines.extend(
                    [
                        "**Payload**",
                        "",
                        "```json",
                        json.dumps(first["payload"], ensure_ascii=False, indent=2),
                        "```",
                        "",
                    ]
                )
            for record in case_records:
                lines.extend(
                    [
                        f"##### `{record['model_label']}`",
                        "",
                        f"- Status: `{record['status']}`",
                        f"- Latency: `{record.get('latency_ms')}` ms",
                        (
                            f"- Tokens in/out: `{record.get('tokens_input')}` / "
                            f"`{record.get('tokens_output')}`"
                        ),
                        "",
                    ]
                )
                if record.get("error"):
                    lines.extend(
                        [
                            "```text",
                            record["error"],
                            "```",
                            "",
                        ]
                    )
                else:
                    lines.extend(
                        [
                            "```json",
                            json.dumps(record.get("result"), ensure_ascii=False, indent=2),
                            "```",
                            "",
                        ]
                    )
    return "\n".join(lines)


def build_default_output_path(data_version: str) -> Path:
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Path("evaluation_reports") / f"ai_workflow_eval_{data_version}_{timestamp}.md"


def create_eval_app(*, debug_llm: bool = False) -> FastAPI:
    settings = get_settings()
    settings.debug_llm = debug_llm
    return create_app()


def _run_one_case(
    *,
    session_factory: sessionmaker[Session],
    ai_run_service,
    case: EvalCase,
    model_ref: EvalModelRef,
) -> dict[str, Any]:
    payload = dict(case.payload)
    with session_factory() as session:
        try:
            if case.reply_seed is not None:
                seed_run, _ = ai_run_service.create_run(
                    session,
                    user=None,
                    session_id=None,
                    run_type=case.reply_seed.run_type,
                    context=case.context,
                    response_preferences=case.response_preferences,
                    operation_context=dict(case.reply_seed.payload),
                    stream=False,
                    use_cache=False,
                )
                ai_run_service.execute_run(
                    session,
                    run=seed_run,
                    context=case.context,
                    response_preferences=case.response_preferences,
                    operation_context=dict(case.reply_seed.payload),
                    provider_name_override=model_ref.provider_name,
                    model_name_override=model_ref.model_name,
                )
                payload["reply_to_run_id"] = str(seed_run.id)

            run, _ = ai_run_service.create_run(
                session,
                user=None,
                session_id=None,
                run_type=case.feature,
                context=case.context,
                response_preferences=case.response_preferences,
                operation_context=payload,
                stream=False,
                use_cache=False,
            )
            result = ai_run_service.execute_run(
                session,
                run=run,
                context=case.context,
                response_preferences=case.response_preferences,
                operation_context=payload,
                provider_name_override=model_ref.provider_name,
                model_name_override=model_ref.model_name,
            )
            return {
                "case_key": case.case_key,
                "feature": case.feature.value,
                "description": case.description,
                "model_label": model_ref.label,
                "provider_name": model_ref.provider_name,
                "model_name": model_ref.model_name,
                "status": run.status,
                "latency_ms": run.latency_ms,
                "tokens_input": run.tokens_input,
                "tokens_output": run.tokens_output,
                "cost_usd": float(run.cost_usd) if run.cost_usd is not None else None,
                "payload": payload,
                "context_brief": _context_brief(case.context),
                "result": result,
            }
        except Exception as exc:
            session.rollback()
            return {
                "case_key": case.case_key,
                "feature": case.feature.value,
                "description": case.description,
                "model_label": model_ref.label,
                "provider_name": model_ref.provider_name,
                "model_name": model_ref.model_name,
                "status": "failed",
                "latency_ms": None,
                "tokens_input": None,
                "tokens_output": None,
                "cost_usd": None,
                "payload": payload,
                "context_brief": _context_brief(case.context),
                "error": str(exc),
                "result": None,
            }


def _summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in results:
        grouped.setdefault((record["feature"], record["model_label"]), []).append(record)

    feature_model_summaries: list[dict[str, Any]] = []
    for (feature, model_label), records in sorted(grouped.items()):
        completed = [record for record in records if record["status"] == "completed"]
        latencies = [
            record["latency_ms"] for record in completed if record["latency_ms"] is not None
        ]
        feature_model_summaries.append(
            {
                "feature": feature,
                "model_label": model_label,
                "total_count": len(records),
                "completed_count": len(completed),
                "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else None,
            }
        )
    return {"feature_model_summaries": feature_model_summaries}


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
    slot_count = build_slot_count_for_game(game)
    if len(entries) != slot_count:
        raise ValueError(f"{game.value} requires exactly {slot_count} slots.")
    return list(entries)


def _runes(*, primary: list[str], secondary: list[str]) -> dict[str, list[str]]:
    return {"primary": primary, "secondary": secondary}


def _context_brief(context: MatchContext) -> str:
    enemies = ", ".join(enemy.champion_slug for enemy in context.enemy_team) or "none"
    tags = ", ".join(context.environment.tags) or "none"
    return (
        f"game={context.game.value}, own={context.own_champion_slug}, "
        f"enemies={enemies}, tags={tags}"
    )
