from dataclasses import dataclass
from typing import Any

from app.catalog.registry import CatalogSnapshot
from app.domain.enums import Game, RunType
from app.domain.match_context import MatchContext, ResponsePreferences

AP_POOL = {
    Game.LOL: [
        "lol-luden-s-companion",
        "lol-sorcerer-s-shoes",
        "lol-shadowflame",
        "lol-zhonya-s-hourglass",
        "lol-rabadon-s-deathcap",
        "lol-void-staff",
    ],
    Game.WILD_RIFT: [
        "wr-luden-s-echo",
        "wr-ionian-boots-of-lucidity",
        "wr-infinity-orb",
        "wr-stormsurge",
        "wr-rabadon-s-deathcap",
        "wr-void-staff",
    ],
}
AD_POOL = {
    Game.LOL: [
        "lol-kraken-slayer",
        "lol-berserker-s-greaves",
        "lol-infinity-edge",
        "lol-runaan-s-hurricane",
        "lol-bloodthirster",
        "lol-mortal-reminder",
    ],
    Game.WILD_RIFT: [
        "wr-kraken-slayer",
        "wr-berserker-s-greaves",
        "wr-infinity-edge",
        "wr-runaan-s-hurricane",
        "wr-bloodthirster",
        "wr-mortal-reminder",
    ],
}
BRUISER_POOL = {
    Game.LOL: [
        "lol-eclipse",
        "lol-black-cleaver",
        "lol-sterak-s-gage",
        "lol-sundered-sky",
        "lol-death-s-dance",
        "lol-guardian-angel",
    ],
    Game.WILD_RIFT: [
        "wr-eclipse",
        "wr-black-cleaver",
        "wr-sterak-s-gage",
        "wr-sundered-sky",
        "wr-death-s-dance",
        "wr-guardian-angel",
    ],
}
TANK_POOL = {
    Game.LOL: [
        "lol-sunfire-aegis",
        "lol-thornmail",
        "lol-spirit-visage",
        "lol-force-of-nature",
        "lol-frozen-heart",
        "lol-warmog-s-armor",
    ],
    Game.WILD_RIFT: [
        "wr-sunfire-aegis",
        "wr-thornmail",
        "wr-spirit-visage",
        "wr-force-of-nature",
        "wr-frozen-heart",
        "wr-warmog-s-armor",
    ],
}
SUPPORT_POOL = {
    Game.LOL: [
        "lol-redemption",
        "lol-ardent-censer",
        "lol-staff-of-flowing-waters",
        "lol-imperial-mandate",
        "lol-mikael-s-blessing",
        "lol-chemtech-putrifier",
    ],
    Game.WILD_RIFT: [
        "wr-redemption",
        "wr-ardent-censer",
        "wr-staff-of-flowing-waters",
        "wr-imperial-mandate",
        "wr-protector-s-vow",
        "wr-harmonic-echo",
    ],
}


@dataclass
class HeuristicRunResult:
    result: dict[str, Any]
    reasoning_text: str


def generate_run_result(
    *,
    run_type: RunType,
    context: MatchContext,
    response_preferences: ResponsePreferences,
    operation_context: dict[str, Any],
    snapshot: CatalogSnapshot,
    baseline: dict[str, Any] | None,
    reference_summary: str | None,
    calibration_summary: str | None,
) -> HeuristicRunResult:
    del response_preferences, calibration_summary
    recommended_build = _select_build(context=context, snapshot=snapshot, baseline=baseline)
    slot_index = operation_context.get("slot_index", 0)
    summary = _build_summary(context=context, recommended_build=recommended_build)
    if reference_summary and context.environment.free_text:
        summary = f"{summary} 另外我参考了相近局面的历史结果。"

    if run_type == RunType.RECOMMEND_FULL_BUILD:
        return HeuristicRunResult(
            result={
                "score": None,
                "summary": summary,
                "build": recommended_build,
                "runes": _select_runes(context),
                "explanations": [],
                "alternatives": [],
            },
            reasoning_text=summary,
        )

    if run_type == RunType.RECOMMEND_SLOT:
        slot_index = int(slot_index)
        build = list(context.own_build)
        build[slot_index] = recommended_build[slot_index]
        target_item = recommended_build[slot_index]
        explanation = _build_slot_explanation(
            context,
            target_item=target_item,
            slot_index=slot_index,
        )
        return HeuristicRunResult(
            result={
                "score": None,
                "summary": explanation,
                "build": build,
                "runes": None,
                "explanations": [{"target": f"slot:{slot_index}", "text": explanation}],
                "alternatives": _build_alternatives(
                    context,
                    target_item=target_item,
                    slot_index=slot_index,
                ),
            },
            reasoning_text=explanation,
        )

    if run_type == RunType.EVALUATE_BUILD:
        overlap = len(
            {item for item in context.own_build if item}
            & {item for item in recommended_build if item}
        )
        score = min(100, 55 + overlap * 8 + (5 if context.environment.free_text else 0))
        return HeuristicRunResult(
            result={
                "score": score,
                "summary": f"当前出装有 {overlap} 件和推荐方案一致，整体稳定性还可以。",
                "build": context.own_build,
                "runes": context.own_runes.model_dump(mode="json"),
                "explanations": [
                    {
                        "target": "build",
                        "text": "如果你想更稳，可以优先向推荐模板靠拢。",
                    }
                ],
                "alternatives": [],
            },
            reasoning_text=f"当前方案评分 {score} 分。",
        )

    if run_type == RunType.EXPLAIN_SLOT:
        target_item = recommended_build[slot_index]
        text = _build_slot_explanation(
            context,
            target_item=target_item,
            slot_index=slot_index,
        )
        return HeuristicRunResult(
            result={
                "score": None,
                "summary": text,
                "build": context.own_build,
                "runes": None,
                "explanations": [{"target": f"slot:{slot_index}", "text": text}],
                "alternatives": _build_alternatives(
                    context,
                    target_item=target_item,
                    slot_index=slot_index,
                ),
            },
            reasoning_text=text,
        )

    if run_type == RunType.COMPARE_BUILDS:
        comparison_context = operation_context.get("comparison_context", {})
        other_build = comparison_context.get("own_build") or []
        current_overlap = len(
            {item for item in context.own_build if item}
            & {item for item in recommended_build if item}
        )
        other_overlap = len(
            {item for item in other_build if item} & {item for item in recommended_build if item}
        )
        better = "当前 build" if current_overlap >= other_overlap else "对比 build"
        text = f"从模板接近度看，{better} 更稳。"
        return HeuristicRunResult(
            result={
                "score": None,
                "summary": text,
                "build": context.own_build,
                "runes": context.own_runes.model_dump(mode="json"),
                "explanations": [
                    {
                        "target": "comparison",
                        "text": (
                            f"当前方案命中 {current_overlap} 件，对比方案命中 {other_overlap} 件。"
                        ),
                    }
                ],
                "alternatives": [],
            },
            reasoning_text=text,
        )

    if run_type == RunType.CHAT_FOLLOWUP:
        user_message = operation_context.get("user_message", "")
        text = f"围绕你问的“{user_message}”，当前更推荐先保证成型节奏，再补针对性防装。"
        return HeuristicRunResult(
            result={
                "score": None,
                "summary": text,
                "build": context.own_build,
                "runes": context.own_runes.model_dump(mode="json"),
                "explanations": [{"target": "answer", "text": text}],
                "alternatives": [],
            },
            reasoning_text=text,
        )

    raise ValueError(f"Unsupported run_type {run_type.value}")


def _select_build(
    *,
    context: MatchContext,
    snapshot: CatalogSnapshot,
    baseline: dict[str, Any] | None,
) -> list[str | None]:
    if baseline and baseline.get("recommended_build"):
        return list(baseline["recommended_build"])

    archetype = _infer_archetype(context, snapshot)
    pool = {
        "ap": AP_POOL,
        "ad": AD_POOL,
        "bruiser": BRUISER_POOL,
        "tank": TANK_POOL,
        "support": SUPPORT_POOL,
    }[archetype][context.game]
    pool = [slug for slug in pool if slug in snapshot.catalogs[context.game].items_by_slug]
    build = list(pool[:6])
    while len(build) < 6:
        build.append(None)

    if "assassin-heavy" in context.environment.tags and archetype in {"ap", "support"}:
        _replace_if_present(build, snapshot, context.game, 3, defense_candidates(context.game))
    if "healing-heavy" in context.environment.tags:
        _replace_if_present(
            build,
            snapshot,
            context.game,
            4,
            anti_heal_candidates(context.game, archetype),
        )
    if "tank-heavy" in context.environment.tags:
        _replace_if_present(
            build,
            snapshot,
            context.game,
            5,
            anti_tank_candidates(context.game, archetype),
        )

    return build[:6]


def _infer_archetype(context: MatchContext, snapshot: CatalogSnapshot) -> str:
    champion = snapshot.catalogs[context.game].champions_by_slug.get(context.own_champion_slug)
    raw_payload = champion.raw_payload if champion else {}
    infobox = raw_payload.get("infobox", {})
    abilities = raw_payload.get("abilities", [])
    magic_hits = sum(
        1
        for ability in abilities
        if str(ability.get("damage_type", "")).lower().startswith("magic")
    )
    physical_hits = sum(
        1
        for ability in abilities
        if str(ability.get("damage_type", "")).lower().startswith("physical")
    )
    attack_range = _parse_first_number(infobox.get("Attack range") or infobox.get("Range type"))
    hp = _parse_first_number(infobox.get("HP"))
    ar = _parse_first_number(infobox.get("AR"))
    mr = _parse_first_number(infobox.get("MR"))
    classes = str(infobox.get("Class(es)", "")).lower()

    if "support" in classes or "shield" in " ".join(raw_payload.get("categories", [])).lower():
        return "support"
    if "tank" in classes or (attack_range < 250 and hp >= 600 and (ar + mr) >= 60):
        return "tank"
    if magic_hits > physical_hits:
        return "ap"
    if attack_range >= 450:
        return "ad"
    if "fighter" in classes or "assassin" in classes:
        return "bruiser"
    return "bruiser"


def _select_runes(context: MatchContext) -> dict[str, list[str]]:
    if context.game == Game.LOL:
        return {
            "primary": [
                "lol-electrocute",
                "lol-sudden-impact",
                "lol-eyeball-collection",
                "lol-ultimate-hunter",
            ],
            "secondary": ["lol-manaflow-band", "lol-transcendence"],
        }
    return {
        "primary": ["wr-electrocute", "wr-brutal", "wr-bone-plating", "wr-sweet-tooth"],
        "secondary": [],
    }


def _build_summary(context: MatchContext, recommended_build: list[str | None]) -> str:
    first_item = recommended_build[0] or "核心装"
    game_label = "LoL PC" if context.game == Game.LOL else "Wild Rift"
    return f"{game_label} 这局先按 {first_item} 的成型节奏推进，整体会更稳。"


def _build_slot_explanation(
    context: MatchContext,
    *,
    target_item: str | None,
    slot_index: int,
) -> str:
    item_name = target_item or "该装备"
    if "assassin-heavy" in context.environment.tags:
        return f"{item_name} 更适合这个第 {slot_index + 1} 槽位，因为对面爆发高，需要先补容错。"
    if "tank-heavy" in context.environment.tags:
        return f"{item_name} 更适合这个第 {slot_index + 1} 槽位，因为你需要更早补穿透或持续输出。"
    return f"{item_name} 作为第 {slot_index + 1} 件更顺，因为它能把当前节奏和伤害曲线接上。"


def _build_alternatives(
    context: MatchContext,
    *,
    target_item: str | None,
    slot_index: int,
) -> list[dict[str, str]]:
    alternatives: list[dict[str, str]] = []
    if "ap-heavy" in context.environment.tags:
        alternative = defense_candidates(context.game)[-1]
        alternatives.append(
            {
                "target": f"slot:{slot_index}",
                "name": alternative,
                "reason": "如果更担心法伤和控制，可以转成更保守的魔抗项。",
            }
        )
    if target_item:
        alternatives.append(
            {
                "target": f"slot:{slot_index}",
                "name": target_item,
                "reason": "如果你想保持当前节奏，也可以继续沿着这条主线做。",
            }
        )
    return alternatives[:2]


def defense_candidates(game: Game) -> list[str]:
    return {
        Game.LOL: ["lol-zhonya-s-hourglass", "lol-banshee-s-veil", "lol-guardian-angel"],
        Game.WILD_RIFT: ["wr-stasis-enchant", "wr-banshee-s-veil", "wr-guardian-angel"],
    }[game]


def anti_heal_candidates(game: Game, archetype: str) -> list[str]:
    if archetype == "ap":
        return {
            Game.LOL: ["lol-morellonomicon"],
            Game.WILD_RIFT: ["wr-morellonomicon"],
        }[game]
    return {
        Game.LOL: ["lol-mortal-reminder"],
        Game.WILD_RIFT: ["wr-mortal-reminder"],
    }[game]


def anti_tank_candidates(game: Game, archetype: str) -> list[str]:
    if archetype == "ap":
        return {
            Game.LOL: ["lol-void-staff", "lol-liandry-s-torment"],
            Game.WILD_RIFT: ["wr-void-staff", "wr-liandry-s-torment"],
        }[game]
    return {
        Game.LOL: ["lol-black-cleaver", "lol-mortal-reminder"],
        Game.WILD_RIFT: ["wr-black-cleaver", "wr-mortal-reminder"],
    }[game]


def _replace_if_present(
    build: list[str | None],
    snapshot: CatalogSnapshot,
    game: Game,
    index: int,
    candidates: list[str],
) -> None:
    for candidate in candidates:
        if candidate in snapshot.catalogs[game].items_by_slug:
            build[index] = candidate
            return


def _parse_first_number(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value)
    current = ""
    for character in text:
        if character.isdigit() or character == ".":
            current += character
        elif current:
            break
    return float(current) if current else 0.0
