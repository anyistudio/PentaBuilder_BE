from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

from app.ai.orchestration.entity_appendix import build_involved_entity_parameter_appendix
from app.ai.tools.catalog_tools import CatalogToolset, best_catalog_entity_fuzzy_match
from app.catalog.registry import CatalogSnapshot
from app.core.errors import ApiError
from app.domain.enums import Game, RunType
from app.domain.match_context import (
    MAX_BUILD_SLOT_COUNT,
    MatchContext,
    RuneSelection,
    build_slot_count_for_game,
    normalize_lookup_text,
    validate_slug_for_game,
)

RECOMMEND_FULL_BUILD_MIN_STEPS = build_slot_count_for_game(Game.LOL)
RECOMMEND_FULL_BUILD_MAX_STEPS = build_slot_count_for_game(Game.WILD_RIFT)
HERO_BASE_STAT_KEYS = (
    "health",
    "physical_attack",
    "magic_attack",
    "armor",
    "magic_resist",
    "armor_penetration",
    "magic_penetration",
)
ITEM_RATING_VALUES = ("S", "A", "B", "C", "F")
ItemRating = Literal["S", "A", "B", "C", "F"]


class RuneSelectionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    primary: list[str] = Field(default_factory=list)
    secondary: list[str] = Field(default_factory=list)


class SlotNote(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slot_index: int = Field(ge=0, le=MAX_BUILD_SLOT_COUNT - 1)
    text: str = Field(min_length=1)


class SlotAlternative(BaseModel):
    model_config = ConfigDict(extra="ignore")

    item_slug: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ExplanationAdjustment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    target: str = Field(min_length=1)
    text: str = Field(min_length=1)


class KeyDifference(BaseModel):
    model_config = ConfigDict(extra="ignore")

    target: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class EvaluateBuildResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    score: int = Field(ge=0, le=100)
    summary: str = Field(min_length=1)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    recommended_build: list[str | None] = Field(
        min_length=RECOMMEND_FULL_BUILD_MIN_STEPS,
        max_length=RECOMMEND_FULL_BUILD_MAX_STEPS,
    )
    recommended_runes: RuneSelectionResult = Field(default_factory=RuneSelectionResult)


class RecommendFullBuildResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    recommended_build_order: list[str | None] = Field(
        min_length=RECOMMEND_FULL_BUILD_MIN_STEPS,
        max_length=RECOMMEND_FULL_BUILD_MAX_STEPS,
        validation_alias=AliasChoices("recommended_build_order", "recommended_build"),
    )
    recommended_runes: RuneSelectionResult = Field(default_factory=RuneSelectionResult)
    summary: str = Field(min_length=1)
    slot_notes: list[SlotNote] = Field(default_factory=list)


class RecommendSlotResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slot_index: int = Field(ge=0, le=MAX_BUILD_SLOT_COUNT - 1)
    recommended_item_slug: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    reasoning: list[str] = Field(default_factory=list)
    alternatives: list[SlotAlternative] = Field(default_factory=list)


class ExplainSlotResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slot_index: int = Field(ge=0, le=MAX_BUILD_SLOT_COUNT - 1)
    current_item_slug: str | None = None
    is_current_choice_good: bool
    item_rating: ItemRating
    item_rating_reason: str = Field(min_length=1)
    best_item_slug: str | None = None
    summary: str = Field(min_length=1)
    why_current_choice: str = Field(min_length=1)
    why_best_choice: str = Field(min_length=1)
    linked_adjustments: list[ExplanationAdjustment] = Field(default_factory=list)


class CompareBuildsResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    winner: Literal["build_a", "build_b"]
    score_delta: int = Field(ge=0, le=100)
    summary: str = Field(min_length=1)
    key_differences: list[KeyDifference] = Field(default_factory=list)
    when_build_b_is_better: list[str] = Field(default_factory=list)


class ChatFollowupResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    followup_suggestions: list[str] = Field(default_factory=list)


class OwnKillEstimateResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enemy_champion_slug: str = Field(min_length=1)
    estimated_minutes_per_kill: float = Field(gt=0)
    reason: str = Field(min_length=1)


class HeroBaseStatsEstimateResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    health: float = Field(ge=0, le=10)
    physical_attack: float = Field(ge=0, le=10)
    magic_attack: float = Field(ge=0, le=10)
    armor: float = Field(ge=0, le=10)
    magic_resist: float = Field(ge=0, le=10)
    armor_penetration: float = Field(ge=0, le=10)
    magic_penetration: float = Field(ge=0, le=10)


class HeroStatusEstimateResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    champion_slug: str = Field(min_length=1)
    base_stats: HeroBaseStatsEstimateResult
    status_evaluation: str = Field(min_length=1)


class EnemyChampionStatusResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    champion_slug: str = Field(min_length=1)
    base_stats: HeroBaseStatsEstimateResult
    status_evaluation: str = Field(min_length=1)
    estimated_minutes_per_kill_on_user: float = Field(gt=0)
    kill_reason: str = Field(min_length=1)
    tower_push_percent_per_minute: float = Field(ge=0, le=100)
    tower_push_reason: str = Field(min_length=1)


class GameStatusResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = Field(min_length=1)
    assumed_match_duration_minutes: int = Field(ge=1, le=60)
    own_status: HeroStatusEstimateResult
    own_kill_frequency_vs_enemies: list[OwnKillEstimateResult] = Field(default_factory=list)
    own_tower_push_percent_per_minute: float = Field(ge=0, le=100)
    own_tower_push_reason: str = Field(min_length=1)
    enemy_statuses: list[EnemyChampionStatusResult] = Field(default_factory=list)


CONTRACT_MODELS: dict[RunType, type[BaseModel]] = {
    RunType.EVALUATE_BUILD: EvaluateBuildResult,
    RunType.RECOMMEND_FULL_BUILD: RecommendFullBuildResult,
    RunType.RECOMMEND_SLOT: RecommendSlotResult,
    RunType.EXPLAIN_SLOT: ExplainSlotResult,
    RunType.COMPARE_BUILDS: CompareBuildsResult,
    RunType.GAME_STATUS: GameStatusResult,
    RunType.CHAT_FOLLOWUP: ChatFollowupResult,
}


def get_result_response_schema(
    *,
    run_type: RunType,
    context: MatchContext,
    operation_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    build_slot_count = build_slot_count_for_game(context.game)
    if run_type == RunType.EVALUATE_BUILD:
        return {
            "type": "object",
            "properties": {
                "score": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                    "description": "Overall build score for the current match context.",
                },
                "summary": {
                    "type": "string",
                    "description": "One short paragraph summarizing the build evaluation.",
                },
                "strengths": {
                    "type": "array",
                    "description": "Main strengths of the current build under this context.",
                    "items": {"type": "string"},
                },
                "weaknesses": {
                    "type": "array",
                    "description": "Main weaknesses or risks in the current build.",
                    "items": {"type": "string"},
                },
                "recommended_build": _nullable_build_array_schema(
                    description=(
                        "A better build direction for this match context. "
                        "Use canonical slugs or null."
                    ),
                    min_items=build_slot_count,
                    max_items=build_slot_count,
                ),
                "recommended_runes": _rune_selection_schema(
                    description="A better rune direction for this match context."
                ),
            },
            "required": [
                "score",
                "summary",
                "strengths",
                "weaknesses",
                "recommended_build",
                "recommended_runes",
            ],
            "additionalProperties": False,
        }
    if run_type == RunType.RECOMMEND_FULL_BUILD:
        recommendation_count = (operation_context or {}).get("recommendation_count")
        if isinstance(recommendation_count, int):
            build_description = (
                "Ordered build array using canonical item slugs. Keep current filled steps "
                "unchanged, "
                f"fill exactly the next {recommendation_count} empty step(s), and leave all later "
                "empty steps as null."
            )
        else:
            build_description = (
                "Ordered build array using canonical item slugs. Keep current filled steps "
                "unchanged "
                "and fill every remaining empty step."
            )
        return {
            "type": "object",
            "properties": {
                "recommended_build_order": _nullable_build_array_schema(
                    description=build_description,
                    min_items=build_slot_count,
                    max_items=build_slot_count,
                ),
                "recommended_runes": _rune_selection_schema(
                    description=(
                        "Temporary placeholder. Leave both arrays empty for this workflow: "
                        "`primary=[]`, `secondary=[]`."
                    )
                ),
                "summary": {
                    "type": "string",
                    "description": "Short build-direction summary.",
                },
                "slot_notes": {
                    "type": "array",
                    "description": "Optional short notes for high-value steps.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "slot_index": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": build_slot_count - 1,
                                "description": "0-based build-order step index.",
                            },
                            "text": {
                                "type": "string",
                                "description": "Short timing or sequencing note.",
                            },
                        },
                        "required": ["slot_index", "text"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["recommended_build_order", "recommended_runes", "summary", "slot_notes"],
            "additionalProperties": False,
        }
    if run_type == RunType.RECOMMEND_SLOT:
        return {
            "type": "object",
            "properties": {
                "slot_index": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": build_slot_count - 1,
                    "description": "The requested slot index. It must match the requested payload.",
                },
                "recommended_item_slug": {
                    "type": "string",
                    "description": "The best item slug for the requested slot.",
                },
                "summary": {
                    "type": "string",
                    "description": "One short paragraph explaining the best item choice.",
                },
                "reasoning": {
                    "type": "array",
                    "description": "Main reasons the recommended item is best right now.",
                    "items": {"type": "string"},
                },
                "alternatives": {
                    "type": "array",
                    "description": "Optional secondary choices if the user needs an alternative.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item_slug": {
                                "type": "string",
                                "description": "Alternative item slug.",
                            },
                            "reason": {
                                "type": "string",
                                "description": "Why this alternative is viable but secondary.",
                            },
                        },
                        "required": ["item_slug", "reason"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "slot_index",
                "recommended_item_slug",
                "summary",
                "reasoning",
                "alternatives",
            ],
            "additionalProperties": False,
        }
    if run_type == RunType.EXPLAIN_SLOT:
        return {
            "type": "object",
            "properties": {
                "slot_index": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": build_slot_count - 1,
                    "description": "The explained slot index. It must match the requested payload.",
                },
                "current_item_slug": {
                    "type": ["string", "null"],
                    "description": "The current item in that slot, or null if the slot is empty.",
                },
                "is_current_choice_good": {
                    "type": "boolean",
                    "description": "Whether the current choice is good enough for this context.",
                },
                "item_rating": {
                    "type": "string",
                    "enum": list(ITEM_RATING_VALUES),
                    "description": (
                        "System item grade for the current choice: S, A, B, C, or F."
                    ),
                },
                "item_rating_reason": {
                    "type": "string",
                    "description": (
                        "One concise reason for the item grade, grounded in matchup, "
                        "current build state, and better alternatives when relevant."
                    ),
                },
                "best_item_slug": {
                    "type": ["string", "null"],
                    "description": "The best item for this slot if a better option exists.",
                },
                "summary": {
                    "type": "string",
                    "description": "Short top-line explanation for the slot judgement.",
                },
                "why_current_choice": {
                    "type": "string",
                    "description": "Why the current item works or fails under this context.",
                },
                "why_best_choice": {
                    "type": "string",
                    "description": "Why the best item is better for this context.",
                },
                "linked_adjustments": {
                    "type": "array",
                    "description": "Optional adjacent-slot adjustments caused by this decision.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "target": {
                                "type": "string",
                                "description": "The affected follow-on target such as slot:2.",
                            },
                            "text": {
                                "type": "string",
                                "description": "Short explanation for that linked adjustment.",
                            },
                        },
                        "required": ["target", "text"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "slot_index",
                "current_item_slug",
                "is_current_choice_good",
                "item_rating",
                "item_rating_reason",
                "best_item_slug",
                "summary",
                "why_current_choice",
                "why_best_choice",
                "linked_adjustments",
            ],
            "additionalProperties": False,
        }
    if run_type == RunType.COMPARE_BUILDS:
        return {
            "type": "object",
            "properties": {
                "winner": {
                    "type": "string",
                    "enum": ["build_a", "build_b"],
                    "description": "Which build is better in the current match context.",
                },
                "score_delta": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                    "description": "A rough confidence delta between the two builds.",
                },
                "summary": {
                    "type": "string",
                    "description": "Short comparison summary naming the winning build.",
                },
                "key_differences": {
                    "type": "array",
                    "description": (
                        "The most important item or rune differences driving the result."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "target": {
                                "type": "string",
                                "description": "The target slot or concept being compared.",
                            },
                            "reason": {
                                "type": "string",
                                "description": "Why that difference matters in this context.",
                            },
                        },
                        "required": ["target", "reason"],
                        "additionalProperties": False,
                    },
                },
                "when_build_b_is_better": {
                    "type": "array",
                    "description": "Optional situations where build B would be preferable.",
                    "items": {"type": "string"},
                },
            },
            "required": [
                "winner",
                "score_delta",
                "summary",
                "key_differences",
                "when_build_b_is_better",
            ],
            "additionalProperties": False,
        }
    if run_type == RunType.GAME_STATUS:
        base_stats_description = (
            "Relative 0-10 hero state estimate after considering the champion's normal baseline, "
            "current owned items, and runes. These are comparative ratings across champions, "
            "not exact game stats."
        )
        return {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Short overview of current kill and tower pressure.",
                },
                "assumed_match_duration_minutes": {
                    "type": "integer",
                    "enum": [15, 30],
                    "description": "15 for ARAM, otherwise 30.",
                },
                "own_status": {
                    "type": "object",
                    "description": (
                        "User-side champion state estimate used as an input before estimating "
                        "kill and tower pressure."
                    ),
                    "properties": {
                        "champion_slug": {
                            "type": "string",
                            "description": "Own champion slug from the current context.",
                        },
                        "base_stats": _hero_base_stats_schema(
                            description=base_stats_description
                        ),
                        "status_evaluation": {
                            "type": "string",
                            "description": (
                                "One short causal status evaluation for the own champion. "
                                "Explain which champion baseline traits, current state signals, "
                                "and specific owned items most affect the 0-10 stat comparison "
                                "against the relevant enemy profile."
                            ),
                        },
                    },
                    "required": ["champion_slug", "base_stats", "status_evaluation"],
                    "additionalProperties": False,
                },
                "own_kill_frequency_vs_enemies": {
                    "type": "array",
                    "description": "User kill cadence versus each enemy.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "enemy_champion_slug": {
                                "type": "string",
                                "description": "Enemy champion slug from the current context.",
                            },
                            "estimated_minutes_per_kill": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": (
                                    "Minutes per kill within the assumed "
                                    "match duration."
                                ),
                            },
                            "reason": {
                                "type": "string",
                                "description": "Short reason grounded in current items first.",
                            },
                        },
                        "required": [
                            "enemy_champion_slug",
                            "estimated_minutes_per_kill",
                            "reason",
                        ],
                        "additionalProperties": False,
                    },
                },
                "own_tower_push_percent_per_minute": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 100,
                    "description": (
                        "Percent of the user's current target objective "
                        "pushed per minute."
                    ),
                },
                "own_tower_push_reason": {
                    "type": "string",
                    "description": "Short reason for the user's tower pressure estimate.",
                },
                "enemy_statuses": {
                    "type": "array",
                    "description": "Enemy kill cadence versus the user and enemy tower pressure.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "champion_slug": {
                                "type": "string",
                                "description": "Enemy champion slug from the current context.",
                            },
                            "base_stats": _hero_base_stats_schema(
                                description=base_stats_description
                            ),
                            "status_evaluation": {
                                "type": "string",
                                "description": (
                                    "One short causal status evaluation for this enemy "
                                    "champion. "
                                    "Explain which champion baseline traits, current state "
                                    "signals, "
                                    "and specific owned items most affect the 0-10 stat comparison "
                                    "against the user's current profile."
                                ),
                            },
                            "estimated_minutes_per_kill_on_user": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": (
                                    "Minutes per kill on the user within the "
                                    "assumed match duration."
                                ),
                            },
                            "kill_reason": {
                                "type": "string",
                                "description": "Short reason for this kill cadence estimate.",
                            },
                            "tower_push_percent_per_minute": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 100,
                                "description": (
                                    "Percent of that enemy's current target "
                                    "objective pushed per minute."
                                ),
                            },
                            "tower_push_reason": {
                                "type": "string",
                                "description": "Short reason for this tower pressure estimate.",
                            },
                        },
                        "required": [
                            "champion_slug",
                            "base_stats",
                            "status_evaluation",
                            "estimated_minutes_per_kill_on_user",
                            "kill_reason",
                            "tower_push_percent_per_minute",
                            "tower_push_reason",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "summary",
                "assumed_match_duration_minutes",
                "own_status",
                "own_kill_frequency_vs_enemies",
                "own_tower_push_percent_per_minute",
                "own_tower_push_reason",
                "enemy_statuses",
            ],
            "additionalProperties": False,
        }
    return {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "A short answer summary that matches the full answer.",
            },
            "answer": {
                "type": "string",
                "description": "The full natural-language answer to the user's follow-up question.",
            },
            "followup_suggestions": {
                "type": "array",
                "description": "Optional next questions the user may want to ask.",
                "items": {"type": "string"},
            },
        },
        "required": ["summary", "answer", "followup_suggestions"],
        "additionalProperties": False,
    }


def validate_run_result(
    *,
    run_type: RunType,
    raw_result: dict[str, Any],
    context: MatchContext,
    operation_context: dict[str, Any],
    snapshot: CatalogSnapshot,
    slug_resolution_toolset: CatalogToolset | None = None,
    provider_usage_payloads: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    model_cls = CONTRACT_MODELS[run_type]
    try:
        parsed = model_cls.model_validate(raw_result)
    except ValidationError as exc:
        raise ApiError(
            "Invalid AI result.",
            code="provider_error",
            status_code=502,
            details={"issues": exc.errors()},
        ) from exc

    result = parsed.model_dump(mode="json")
    if run_type == RunType.EVALUATE_BUILD:
        recommended_build = _validate_build_slots(
            context=context,
            snapshot=snapshot,
            build=result["recommended_build"],
            allow_null=True,
            loc=["recommended_build"],
            slug_resolution_toolset=slug_resolution_toolset,
            provider_usage_payloads=provider_usage_payloads,
        )
        recommended_runes = _validate_rune_selection(
            context=context,
            snapshot=snapshot,
            rune_selection=result["recommended_runes"],
            loc=["recommended_runes"],
        )
        result["recommended_build"] = recommended_build
        result["recommended_runes"] = recommended_runes
        result["build"] = recommended_build
        result["runes"] = recommended_runes
        result["explanations"] = (
            [{"target": "strength", "text": text} for text in result["strengths"]]
            + [{"target": "weakness", "text": text} for text in result["weaknesses"]]
        )
        result["alternatives"] = []
        return result

    if run_type == RunType.RECOMMEND_FULL_BUILD:
        recommended_build_order = _validate_build_slots(
            context=context,
            snapshot=snapshot,
            build=result["recommended_build_order"],
            allow_null=True,
            loc=["recommended_build_order"],
            slug_resolution_toolset=slug_resolution_toolset,
            provider_usage_payloads=provider_usage_payloads,
        )
        resolved_recommendation_count = _resolve_recommend_full_build_target_count(
            current_build=context.own_build,
            recommendation_count=operation_context.get("recommendation_count"),
        )
        _ensure_filled_slots_preserved(
            current_build=context.own_build,
            proposed_build=recommended_build_order,
        )
        _ensure_recommend_full_build_fills_target_span(
            current_build=context.own_build,
            proposed_build=recommended_build_order,
            target_recommendation_count=resolved_recommendation_count,
        )
        _ensure_recommend_full_build_order_is_consistent(
            context=context,
            snapshot=snapshot,
            build_order=recommended_build_order,
            loc=["recommended_build_order"],
            require_complete_shape=resolved_recommendation_count
            >= len(_remaining_build_slot_indices(context.own_build)),
        )
        _ensure_slot_notes_fit_build_order(
            slot_notes=result["slot_notes"],
            build_order=recommended_build_order,
        )
        recommended_runes = _validate_rune_selection(
            context=context,
            snapshot=snapshot,
            rune_selection=result["recommended_runes"],
            loc=["recommended_runes"],
        )
        result["recommended_build_order"] = recommended_build_order
        result["recommended_build"] = recommended_build_order
        result["recommended_runes"] = recommended_runes
        result["score"] = None
        result["build"] = recommended_build_order
        result["runes"] = recommended_runes
        result["explanations"] = [
            {"target": f"step:{note['slot_index'] + 1}", "text": note["text"]}
            for note in result["slot_notes"]
        ]
        result["alternatives"] = []
        return result

    if run_type == RunType.RECOMMEND_SLOT:
        requested_slot_index = int(operation_context.get("slot_index", -1))
        if result["slot_index"] != requested_slot_index:
            _raise_invalid_ai_result(
                message=f"slot_index must equal requested slot {requested_slot_index}.",
                loc=["slot_index"],
            )
        recommended_item_slug = _validate_item_slug(
            context=context,
            snapshot=snapshot,
            item_slug=result["recommended_item_slug"],
            loc=["recommended_item_slug"],
            slug_resolution_toolset=slug_resolution_toolset,
            provider_usage_payloads=provider_usage_payloads,
        )
        build = list(context.own_build)
        build[requested_slot_index] = recommended_item_slug
        _ensure_only_target_slot_changed(
            current_build=context.own_build,
            proposed_build=build,
            slot_index=requested_slot_index,
        )
        result["recommended_item_slug"] = recommended_item_slug
        result["score"] = None
        result["build"] = build
        result["runes"] = None
        result["explanations"] = [
            {"target": f"slot:{requested_slot_index}", "text": text} for text in result["reasoning"]
        ]
        result["alternatives"] = [
            {
                "target": f"slot:{requested_slot_index}",
                "item_slug": _validate_item_slug(
                    context=context,
                    snapshot=snapshot,
                    item_slug=alternative["item_slug"],
                    loc=["alternatives", index, "item_slug"],
                    slug_resolution_toolset=slug_resolution_toolset,
                    provider_usage_payloads=provider_usage_payloads,
                ),
                "reason": alternative["reason"],
            }
            for index, alternative in enumerate(result["alternatives"])
        ]
        return result

    if run_type == RunType.EXPLAIN_SLOT:
        requested_slot_index = int(operation_context.get("slot_index", -1))
        if result["slot_index"] != requested_slot_index:
            _raise_invalid_ai_result(
                message=f"slot_index must equal requested slot {requested_slot_index}.",
                loc=["slot_index"],
            )
        current_item_slug = context.own_build[requested_slot_index]
        if result["current_item_slug"] is not None:
            validated_current_item = _validate_item_slug(
                context=context,
                snapshot=snapshot,
                item_slug=result["current_item_slug"],
                loc=["current_item_slug"],
                slug_resolution_toolset=slug_resolution_toolset,
                provider_usage_payloads=provider_usage_payloads,
            )
            if current_item_slug is not None and validated_current_item != current_item_slug:
                _raise_invalid_ai_result(
                    message="current_item_slug must match the injected current slot item.",
                    loc=["current_item_slug"],
                )
            result["current_item_slug"] = validated_current_item
        else:
            result["current_item_slug"] = current_item_slug
        if result["best_item_slug"] is not None:
            result["best_item_slug"] = _validate_item_slug(
                context=context,
                snapshot=snapshot,
                item_slug=result["best_item_slug"],
                loc=["best_item_slug"],
                slug_resolution_toolset=slug_resolution_toolset,
                provider_usage_payloads=provider_usage_payloads,
            )
        result["score"] = None
        result["build"] = list(context.own_build)
        result["runes"] = None
        result["explanations"] = [
            {
                "target": f"slot:{requested_slot_index}:rating",
                "text": result["item_rating_reason"],
            },
            {
                "target": f"slot:{requested_slot_index}",
                "text": result["why_current_choice"],
            },
            {
                "target": f"slot:{requested_slot_index}:best",
                "text": result["why_best_choice"],
            },
            *result["linked_adjustments"],
        ]
        result["alternatives"] = (
            [
                {
                    "target": f"slot:{requested_slot_index}",
                    "item_slug": result["best_item_slug"],
                    "reason": result["why_best_choice"],
                }
            ]
            if result["best_item_slug"]
            and result["best_item_slug"] != result["current_item_slug"]
            else []
        )
        return result

    if run_type == RunType.COMPARE_BUILDS:
        comparison_context = operation_context.get("comparison_context", {})
        build_b = _validate_build_slots(
            context=context,
            snapshot=snapshot,
            build=comparison_context.get("own_build") or [],
            allow_null=True,
            loc=["comparison_context", "own_build"],
        )
        runes_b = _validate_rune_selection(
            context=context,
            snapshot=snapshot,
            rune_selection=comparison_context.get("own_runes") or {},
            loc=["comparison_context", "own_runes"],
        )
        result["score"] = None
        result["build"] = list(context.own_build if result["winner"] == "build_a" else build_b)
        result["runes"] = (
            context.own_runes.model_dump(mode="json")
            if result["winner"] == "build_a"
            else runes_b
        )
        result["explanations"] = [
            {"target": item["target"], "text": item["reason"]}
            for item in result["key_differences"]
        ] + [
            {"target": "build_b_future", "text": text} for text in result["when_build_b_is_better"]
        ]
        result["alternatives"] = []
        return result

    if run_type == RunType.GAME_STATUS:
        assumed_duration = _assumed_match_duration_minutes(context)
        if result["assumed_match_duration_minutes"] != assumed_duration:
            _raise_invalid_ai_result(
                message=(
                    "assumed_match_duration_minutes must be 15 for ARAM contexts "
                    "or 30 otherwise."
                ),
                loc=["assumed_match_duration_minutes"],
            )

        normalized_own_status = _normalize_hero_status_estimate(
            context=context,
            snapshot=snapshot,
            status=result["own_status"],
            expected_champion_slug=context.own_champion_slug,
            loc=["own_status"],
        )
        enemy_slugs_in_order = [enemy.champion_slug for enemy in context.enemy_team]
        own_kill_by_enemy = {
            item["enemy_champion_slug"]: item for item in result["own_kill_frequency_vs_enemies"]
        }
        enemy_status_by_slug = {
            item["champion_slug"]: item for item in result["enemy_statuses"]
        }
        if set(own_kill_by_enemy) != set(enemy_slugs_in_order):
            _raise_invalid_ai_result(
                message=(
                    "own_kill_frequency_vs_enemies must contain exactly one entry for each "
                    "enemy champion in the current context."
                ),
                loc=["own_kill_frequency_vs_enemies"],
            )
        if set(enemy_status_by_slug) != set(enemy_slugs_in_order):
            _raise_invalid_ai_result(
                message=(
                    "enemy_statuses must contain exactly one entry for each enemy champion "
                    "in the current context."
                ),
                loc=["enemy_statuses"],
            )
        if len(own_kill_by_enemy) != len(result["own_kill_frequency_vs_enemies"]):
            _raise_invalid_ai_result(
                message="Duplicate enemy_champion_slug entries are not allowed.",
                loc=["own_kill_frequency_vs_enemies"],
            )
        if len(enemy_status_by_slug) != len(result["enemy_statuses"]):
            _raise_invalid_ai_result(
                message="Duplicate champion_slug entries are not allowed.",
                loc=["enemy_statuses"],
            )

        normalized_own_kills: list[dict[str, Any]] = []
        normalized_enemy_statuses: list[dict[str, Any]] = []
        for enemy_slug in enemy_slugs_in_order:
            validated_enemy_slug = _validate_champion_slug(
                context=context,
                snapshot=snapshot,
                champion_slug=enemy_slug,
            )
            own_kill_entry = own_kill_by_enemy[enemy_slug]
            own_kill_minutes = float(own_kill_entry["estimated_minutes_per_kill"])
            if own_kill_minutes > assumed_duration:
                _raise_invalid_ai_result(
                    message=(
                        "estimated_minutes_per_kill must stay within the assumed match duration."
                    ),
                    loc=["own_kill_frequency_vs_enemies", enemy_slug, "estimated_minutes_per_kill"],
                )
            normalized_own_kills.append(
                {
                    "enemy_champion_slug": validated_enemy_slug,
                    "estimated_minutes_per_kill": own_kill_minutes,
                    "reason": own_kill_entry["reason"],
                }
            )

            enemy_status = enemy_status_by_slug[enemy_slug]
            enemy_minutes = float(enemy_status["estimated_minutes_per_kill_on_user"])
            if enemy_minutes > assumed_duration:
                _raise_invalid_ai_result(
                    message=(
                        "estimated_minutes_per_kill_on_user must stay within the assumed match "
                        "duration."
                    ),
                    loc=["enemy_statuses", enemy_slug, "estimated_minutes_per_kill_on_user"],
                )
            tower_push = float(enemy_status["tower_push_percent_per_minute"])
            normalized_enemy_statuses.append(
                {
                    "champion_slug": validated_enemy_slug,
                    "base_stats": _normalize_hero_status_estimate(
                        context=context,
                        snapshot=snapshot,
                        status=enemy_status,
                        expected_champion_slug=enemy_slug,
                        loc=["enemy_statuses", enemy_slug],
                    )["base_stats"],
                    "status_evaluation": enemy_status["status_evaluation"],
                    "estimated_minutes_per_kill_on_user": enemy_minutes,
                    "kill_reason": enemy_status["kill_reason"],
                    "tower_push_percent_per_minute": tower_push,
                    "tower_push_reason": enemy_status["tower_push_reason"],
                }
            )

        result["assumed_match_duration_minutes"] = assumed_duration
        result["own_champion_slug"] = context.own_champion_slug
        result["own_status"] = normalized_own_status
        result["own_kill_frequency_vs_enemies"] = normalized_own_kills
        result["enemy_statuses"] = normalized_enemy_statuses
        result["parameter_appendix"] = build_involved_entity_parameter_appendix(
            context=context,
            snapshot=snapshot,
        )
        result["score"] = None
        result["build"] = list(context.own_build)
        result["runes"] = context.own_runes.model_dump(mode="json")
        result["explanations"] = [
            {"target": "summary", "text": result["summary"]},
            {
                "target": "own_status",
                "text": normalized_own_status["status_evaluation"],
            },
            {
                "target": "own_tower_push",
                "text": result["own_tower_push_reason"],
            },
            *[
                {
                    "target": f"own_vs:{item['enemy_champion_slug']}",
                    "text": item["reason"],
                }
                for item in normalized_own_kills
            ],
            *[
                {
                    "target": f"enemy_vs:{item['champion_slug']}",
                    "text": item["kill_reason"],
                }
                for item in normalized_enemy_statuses
            ],
            *[
                {
                    "target": f"enemy_status:{item['champion_slug']}",
                    "text": item["status_evaluation"],
                }
                for item in normalized_enemy_statuses
            ],
            *[
                {
                    "target": f"enemy_push:{item['champion_slug']}",
                    "text": item["tower_push_reason"],
                }
                for item in normalized_enemy_statuses
            ],
        ]
        result["alternatives"] = []
        return result

    answer = result["answer"]
    result["summary"] = answer if not result["summary"] else result["summary"]
    result["score"] = None
    result["build"] = list(context.own_build)
    result["runes"] = context.own_runes.model_dump(mode="json")
    result["explanations"] = [{"target": "answer", "text": answer}]
    result["alternatives"] = []
    return result


def _build_array_schema(
    *,
    description: str,
    min_items: int = 6,
    max_items: int = 6,
) -> dict[str, Any]:
    return {
        "type": "array",
        "description": description,
        "minItems": min_items,
        "maxItems": max_items,
        "items": {"type": "string"},
    }


def _nullable_build_array_schema(
    *,
    description: str,
    min_items: int = 6,
    max_items: int = 6,
) -> dict[str, Any]:
    return {
        "type": "array",
        "description": description,
        "minItems": min_items,
        "maxItems": max_items,
        "items": {"type": ["string", "null"]},
    }


def _rune_selection_schema(*, description: str) -> dict[str, Any]:
    return {
        "type": "object",
        "description": description,
        "properties": {
            "primary": {
                "type": "array",
                "description": "Primary rune slugs.",
                "items": {"type": "string"},
            },
            "secondary": {
                "type": "array",
                "description": "Secondary rune slugs.",
                "items": {"type": "string"},
            },
        },
        "required": ["primary", "secondary"],
        "additionalProperties": False,
    }


def _hero_base_stats_schema(*, description: str) -> dict[str, Any]:
    return {
        "type": "object",
        "description": description,
        "properties": {
            "health": _ten_point_stat_schema("Relative health and raw durability."),
            "physical_attack": _ten_point_stat_schema("Relative physical damage output."),
            "magic_attack": _ten_point_stat_schema("Relative magic damage output."),
            "armor": _ten_point_stat_schema("Relative resistance to physical damage."),
            "magic_resist": _ten_point_stat_schema("Relative resistance to magic damage."),
            "armor_penetration": _ten_point_stat_schema(
                "Relative ability to bypass enemy armor."
            ),
            "magic_penetration": _ten_point_stat_schema(
                "Relative ability to bypass enemy magic resistance."
            ),
        },
        "required": [
            "health",
            "physical_attack",
            "magic_attack",
            "armor",
            "magic_resist",
            "armor_penetration",
            "magic_penetration",
        ],
        "additionalProperties": False,
    }


def _ten_point_stat_schema(description: str) -> dict[str, Any]:
    return {
        "type": "number",
        "minimum": 0,
        "maximum": 10,
        "description": f"{description} Use a 0-10 relative scale.",
    }


def _raise_invalid_ai_result(
    *,
    message: str,
    loc: list[str | int] | None = None,
) -> None:
    details = {
        "issues": [
            {
                "loc": loc or [],
                "msg": message,
            }
        ]
    }
    raise ApiError(
        "Invalid AI result.",
        code="provider_error",
        status_code=502,
        details=details,
    )


def _validate_item_slug(
    *,
    context: MatchContext,
    snapshot: CatalogSnapshot,
    item_slug: str,
    loc: list[str | int] | None = None,
    slug_resolution_toolset: CatalogToolset | None = None,
    provider_usage_payloads: list[dict[str, Any]] | None = None,
) -> str:
    try:
        validated_slug = validate_slug_for_game(context.game, item_slug)
    except ValueError as exc:
        _raise_invalid_ai_result(message=str(exc), loc=loc)
    if validated_slug not in snapshot.catalogs[context.game].items_by_slug:
        auto_fixed_slug = _autofix_unknown_item_slug(
            context=context,
            snapshot=snapshot,
            item_slug=validated_slug,
            slug_resolution_toolset=slug_resolution_toolset,
            provider_usage_payloads=provider_usage_payloads,
        )
        if auto_fixed_slug is None:
            _raise_invalid_ai_result(
                message=f"Unknown item slug `{validated_slug}` for game `{context.game.value}`.",
                loc=loc,
            )
        validated_slug = auto_fixed_slug
    return validated_slug


def _autofix_unknown_item_slug(
    *,
    context: MatchContext,
    snapshot: CatalogSnapshot,
    item_slug: str,
    slug_resolution_toolset: CatalogToolset | None,
    provider_usage_payloads: list[dict[str, Any]] | None,
) -> str | None:
    if slug_resolution_toolset is not None:
        resolved_slug, usage_payloads = slug_resolution_toolset.resolve_catalog_slug_with_selector(
            snapshot,
            game=context.game,
            entity_type="item",
            raw_name=item_slug,
            filters=None,
        )
        if provider_usage_payloads is not None and usage_payloads:
            provider_usage_payloads.extend(usage_payloads)
        if resolved_slug is not None:
            return resolved_slug

    top_match = best_catalog_entity_fuzzy_match(
        raw_name=item_slug,
        entities=list(snapshot.catalogs[context.game].items_by_slug.values()),
    )
    if top_match is None:
        return None
    return top_match.entity.slug


def _validate_champion_slug(
    *,
    context: MatchContext,
    snapshot: CatalogSnapshot,
    champion_slug: str,
    loc: list[str | int] | None = None,
) -> str:
    try:
        validated_slug = validate_slug_for_game(context.game, champion_slug)
    except ValueError as exc:
        _raise_invalid_ai_result(message=str(exc), loc=loc)
    if validated_slug not in snapshot.catalogs[context.game].champions_by_slug:
        _raise_invalid_ai_result(
            message=f"Unknown champion slug `{validated_slug}` for game `{context.game.value}`.",
            loc=loc,
        )
    return validated_slug


def _normalize_hero_status_estimate(
    *,
    context: MatchContext,
    snapshot: CatalogSnapshot,
    status: dict[str, Any],
    expected_champion_slug: str,
    loc: list[str | int] | None = None,
) -> dict[str, Any]:
    validated_slug = _validate_champion_slug(
        context=context,
        snapshot=snapshot,
        champion_slug=status["champion_slug"],
        loc=[*(loc or []), "champion_slug"],
    )
    if validated_slug != expected_champion_slug:
        _raise_invalid_ai_result(
            message="champion_slug must match the current context subject.",
            loc=[*(loc or []), "champion_slug"],
        )
    base_stats = status["base_stats"]
    return {
        "champion_slug": validated_slug,
        "base_stats": {
            stat_key: float(base_stats[stat_key])
            for stat_key in HERO_BASE_STAT_KEYS
        },
        "status_evaluation": status["status_evaluation"],
    }


def _assumed_match_duration_minutes(context: MatchContext) -> int:
    return 15 if "aram" in context.environment.tags else 30


def _validate_rune_selection(
    *,
    context: MatchContext,
    snapshot: CatalogSnapshot,
    rune_selection: dict[str, Any],
    loc: list[str | int] | None = None,
) -> dict[str, Any]:
    selection = RuneSelection(**rune_selection)
    validated_primary = []
    validated_secondary = []
    for index, rune_slug in enumerate(selection.primary):
        try:
            validated_slug = validate_slug_for_game(context.game, rune_slug)
        except ValueError as exc:
            _raise_invalid_ai_result(
                message=str(exc),
                loc=[*(loc or []), "primary", index],
            )
        if validated_slug not in snapshot.catalogs[context.game].runes_by_slug:
            _raise_invalid_ai_result(
                message=f"Unknown rune slug `{validated_slug}` for game `{context.game.value}`.",
                loc=[*(loc or []), "primary", index],
            )
        validated_primary.append(validated_slug)
    for index, rune_slug in enumerate(selection.secondary):
        try:
            validated_slug = validate_slug_for_game(context.game, rune_slug)
        except ValueError as exc:
            _raise_invalid_ai_result(
                message=str(exc),
                loc=[*(loc or []), "secondary", index],
            )
        if validated_slug not in snapshot.catalogs[context.game].runes_by_slug:
            _raise_invalid_ai_result(
                message=f"Unknown rune slug `{validated_slug}` for game `{context.game.value}`.",
                loc=[*(loc or []), "secondary", index],
            )
        validated_secondary.append(validated_slug)
    return {"primary": validated_primary, "secondary": validated_secondary}


def _validate_build_slots(
    *,
    context: MatchContext,
    snapshot: CatalogSnapshot,
    build: list[str | None],
    allow_null: bool,
    loc: list[str | int] | None = None,
    min_slots: int | None = None,
    max_slots: int | None = None,
    slug_resolution_toolset: CatalogToolset | None = None,
    provider_usage_payloads: list[dict[str, Any]] | None = None,
) -> list[str | None]:
    expected_slot_count = build_slot_count_for_game(context.game)
    resolved_min_slots = expected_slot_count if min_slots is None else min_slots
    resolved_max_slots = expected_slot_count if max_slots is None else max_slots
    if len(build) < resolved_min_slots or len(build) > resolved_max_slots:
        expected = (
            f"exactly {resolved_min_slots} slots"
            if resolved_min_slots == resolved_max_slots
            else f"between {resolved_min_slots} and {resolved_max_slots} slots"
        )
        _raise_invalid_ai_result(
            message=f"Build arrays must contain {expected}.",
            loc=loc,
        )
    validated_build: list[str | None] = []
    for index, slot in enumerate(build):
        if slot is None:
            if not allow_null:
                _raise_invalid_ai_result(
                    message="Build slot cannot be null for this run type.",
                    loc=[*(loc or []), index],
                )
            validated_build.append(None)
            continue
        validated_slot = _validate_item_slug(
            context=context,
            snapshot=snapshot,
            item_slug=slot,
            loc=[*(loc or []), index],
            slug_resolution_toolset=slug_resolution_toolset,
            provider_usage_payloads=provider_usage_payloads,
        )
        validated_build.append(validated_slot)
    return validated_build


def _ensure_filled_slots_preserved(
    *,
    current_build: list[str | None],
    proposed_build: list[str | None],
) -> None:
    for index, current_item in enumerate(current_build):
        if current_item is not None and proposed_build[index] != current_item:
            _raise_invalid_ai_result(
                message="Filled build slots must stay unchanged.",
                loc=["recommended_build_order", index],
            )


def _remaining_build_slot_indices(build: list[str | None]) -> list[int]:
    return [index for index, item_slug in enumerate(build) if item_slug is None]


def _resolve_recommend_full_build_target_count(
    *,
    current_build: list[str | None],
    recommendation_count: Any,
) -> int:
    remaining_slot_count = len(_remaining_build_slot_indices(current_build))
    if recommendation_count is None:
        return remaining_slot_count
    return int(recommendation_count)


def _ensure_recommend_full_build_fills_target_span(
    *,
    current_build: list[str | None],
    proposed_build: list[str | None],
    target_recommendation_count: int,
) -> None:
    remaining_slot_indices = _remaining_build_slot_indices(current_build)
    target_indices = set(remaining_slot_indices[:target_recommendation_count])
    trailing_indices = remaining_slot_indices[target_recommendation_count:]

    for index in target_indices:
        if proposed_build[index] is None:
            _raise_invalid_ai_result(
                message="The requested next recommendation steps must be filled.",
                loc=["recommended_build_order", index],
            )

    for index in trailing_indices:
        if proposed_build[index] is not None:
            _raise_invalid_ai_result(
                message="Later empty steps must remain null when recommendation_count is limited.",
                loc=["recommended_build_order", index],
            )


def _ensure_only_target_slot_changed(
    *,
    current_build: list[str | None],
    proposed_build: list[str | None],
    slot_index: int,
) -> None:
    for index, current_item in enumerate(current_build):
        if index == slot_index:
            continue
        if current_item != proposed_build[index]:
            _raise_invalid_ai_result(
                message="Only the requested slot may change.",
                loc=["build", index],
            )


def _ensure_slot_notes_fit_build_order(
    *,
    slot_notes: list[dict[str, Any]],
    build_order: list[str | None],
) -> None:
    build_length = len(build_order)
    for index, note in enumerate(slot_notes):
        slot_index = int(note["slot_index"])
        if not 0 <= slot_index < build_length:
            _raise_invalid_ai_result(
                message=f"slot_notes.slot_index must be between 0 and {build_length - 1}.",
                loc=["slot_notes", index, "slot_index"],
            )
        if build_order[slot_index] is None:
            _raise_invalid_ai_result(
                message="slot_notes can only reference populated build steps.",
                loc=["slot_notes", index, "slot_index"],
            )


def _ensure_recommend_full_build_order_is_consistent(
    *,
    context: MatchContext,
    snapshot: CatalogSnapshot,
    build_order: list[str | None],
    loc: list[str | int] | None = None,
    require_complete_shape: bool = True,
) -> None:
    boots_indices: list[int] = []
    enchant_indices: list[int] = []

    for index, item_slug in enumerate(build_order):
        if item_slug is None:
            continue
        item_kind = _item_kind(
            context=context,
            snapshot=snapshot,
            item_slug=item_slug,
        )
        if item_kind == "boots":
            boots_indices.append(index)
        elif item_kind == "enchant":
            enchant_indices.append(index)

    if len(boots_indices) > 1:
        _raise_invalid_ai_result(
            message="recommended_build_order can contain at most one boots item.",
            loc=[*(loc or []), boots_indices[1]],
        )
    if len(enchant_indices) > 1:
        _raise_invalid_ai_result(
            message="recommended_build_order can contain at most one enchant item.",
            loc=[*(loc or []), enchant_indices[1]],
        )

    has_boots = bool(boots_indices)
    has_enchant = bool(enchant_indices)

    if context.game == Game.WILD_RIFT:
        if not require_complete_shape:
            if has_enchant and not has_boots:
                _raise_invalid_ai_result(
                    message=(
                        "In Wild Rift partial build recommendations, an enchant step cannot "
                        "appear before a boots step exists."
                    ),
                    loc=loc,
                )
            if has_boots and has_enchant and boots_indices[0] > enchant_indices[0]:
                _raise_invalid_ai_result(
                    message=(
                        "In Wild Rift partial build recommendations, the boots step must "
                        "still appear before the enchant step."
                    ),
                    loc=[*(loc or []), enchant_indices[0]],
                )
            return
        if not has_boots:
            _raise_invalid_ai_result(
                message=(
                    "Wild Rift recommended_build_order must include exactly one boots step."
                ),
                loc=loc,
            )
        if not has_enchant:
            _raise_invalid_ai_result(
                message=(
                    "Wild Rift recommended_build_order must include exactly one enchant step."
                ),
                loc=loc,
            )
        if boots_indices[0] > enchant_indices[0]:
            _raise_invalid_ai_result(
                message=(
                    "In Wild Rift, the boots item must appear before the enchant step "
                    "in recommended_build_order."
                ),
                loc=[*(loc or []), enchant_indices[0]],
            )
        return

    if has_enchant:
        _raise_invalid_ai_result(
            message=(
                "League of Legends PC recommended_build_order must not include a separate "
                "enchant step."
            ),
            loc=[*(loc or []), enchant_indices[0]],
        )


def _item_kind(
    *,
    context: MatchContext,
    snapshot: CatalogSnapshot,
    item_slug: str,
) -> Literal["boots", "enchant"] | None:
    entity = snapshot.catalogs[context.game].items_by_slug.get(item_slug)
    if entity is None:
        return None

    raw_tokens = normalize_lookup_text(
        " ".join(
            part
            for part in [
                entity.slug,
                entity.source_slug,
                entity.english_name,
                str(entity.raw_payload.get("name") or ""),
                *entity.display_names.values(),
                *entity.aliases,
            ]
            if part
        )
    )
    if "enchant" in raw_tokens:
        return "enchant"
    if any(
        token in raw_tokens
        for token in ("boots", "greaves", "shoes", "treads", "steelcaps", "鞋", "靴")
    ):
        return "boots"
    return None
