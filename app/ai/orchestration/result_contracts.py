from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

from app.catalog.registry import CatalogSnapshot
from app.core.errors import ApiError
from app.domain.enums import RunType
from app.domain.match_context import (
    MatchContext,
    RuneSelection,
    normalize_lookup_text,
    validate_slug_for_game,
)

RECOMMEND_FULL_BUILD_MIN_STEPS = 6
RECOMMEND_FULL_BUILD_MAX_STEPS = 7


class RuneSelectionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    primary: list[str] = Field(default_factory=list)
    secondary: list[str] = Field(default_factory=list)


class SlotNote(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slot_index: int = Field(ge=0, le=RECOMMEND_FULL_BUILD_MAX_STEPS - 1)
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
    recommended_build: list[str | None] = Field(min_length=6, max_length=6)
    recommended_runes: RuneSelectionResult = Field(default_factory=RuneSelectionResult)


class RecommendFullBuildResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    recommended_build_order: list[str] = Field(
        min_length=RECOMMEND_FULL_BUILD_MIN_STEPS,
        max_length=RECOMMEND_FULL_BUILD_MAX_STEPS,
        validation_alias=AliasChoices("recommended_build_order", "recommended_build"),
    )
    recommended_runes: RuneSelectionResult = Field(default_factory=RuneSelectionResult)
    summary: str = Field(min_length=1)
    slot_notes: list[SlotNote] = Field(default_factory=list)


class RecommendSlotResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slot_index: int = Field(ge=0, le=5)
    recommended_item_slug: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    reasoning: list[str] = Field(default_factory=list)
    alternatives: list[SlotAlternative] = Field(default_factory=list)


class ExplainSlotResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slot_index: int = Field(ge=0, le=5)
    current_item_slug: str | None = None
    is_current_choice_good: bool
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


CONTRACT_MODELS: dict[RunType, type[BaseModel]] = {
    RunType.EVALUATE_BUILD: EvaluateBuildResult,
    RunType.RECOMMEND_FULL_BUILD: RecommendFullBuildResult,
    RunType.RECOMMEND_SLOT: RecommendSlotResult,
    RunType.EXPLAIN_SLOT: ExplainSlotResult,
    RunType.COMPARE_BUILDS: CompareBuildsResult,
    RunType.CHAT_FOLLOWUP: ChatFollowupResult,
}


def get_result_response_schema(run_type: RunType) -> dict[str, Any]:
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
                    )
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
        return {
            "type": "object",
            "properties": {
                "recommended_build_order": _build_array_schema(
                    description=(
                        "The single best ordered item purchase path using canonical item slugs. "
                        "Return 6 steps for a standard path, or 7 steps only when a boots item "
                        "and a separate enchant item both appear."
                    ),
                    min_items=RECOMMEND_FULL_BUILD_MIN_STEPS,
                    max_items=RECOMMEND_FULL_BUILD_MAX_STEPS,
                ),
                "recommended_runes": _rune_selection_schema(
                    description="The single best rune setup using canonical rune slugs."
                ),
                "summary": {
                    "type": "string",
                    "description": "Short overall explanation for the full build choice.",
                },
                "slot_notes": {
                    "type": "array",
                    "description": "Optional short notes for specific slots.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "slot_index": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": RECOMMEND_FULL_BUILD_MAX_STEPS - 1,
                                "description": "The affected build-order step index.",
                            },
                            "text": {
                                "type": "string",
                                "description": "Short note for that slot.",
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
                    "maximum": 5,
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
                    "maximum": 5,
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
            allow_null=False,
            loc=["recommended_build_order"],
            min_slots=RECOMMEND_FULL_BUILD_MIN_STEPS,
            max_slots=RECOMMEND_FULL_BUILD_MAX_STEPS,
        )
        _ensure_filled_slots_preserved(
            current_build=context.own_build,
            proposed_build=recommended_build_order,
        )
        _ensure_recommend_full_build_order_is_consistent(
            context=context,
            snapshot=snapshot,
            build_order=recommended_build_order,
            loc=["recommended_build_order"],
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
            )
        result["score"] = None
        result["build"] = list(context.own_build)
        result["runes"] = None
        result["explanations"] = [
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
) -> str:
    try:
        validated_slug = validate_slug_for_game(context.game, item_slug)
    except ValueError as exc:
        _raise_invalid_ai_result(message=str(exc), loc=loc)
    if validated_slug not in snapshot.catalogs[context.game].items_by_slug:
        _raise_invalid_ai_result(
            message=f"Unknown item slug `{validated_slug}` for game `{context.game.value}`.",
            loc=loc,
        )
    return validated_slug


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
    min_slots: int = 6,
    max_slots: int = 6,
) -> list[str | None]:
    if len(build) < min_slots or len(build) > max_slots:
        expected = (
            f"exactly {min_slots} slots"
            if min_slots == max_slots
            else f"between {min_slots} and {max_slots} slots"
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


def _ensure_recommend_full_build_order_is_consistent(
    *,
    context: MatchContext,
    snapshot: CatalogSnapshot,
    build_order: list[str | None],
    loc: list[str | int] | None = None,
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

    if has_enchant and not has_boots:
        _raise_invalid_ai_result(
            message="An enchant step requires a boots item in the same recommended_build_order.",
            loc=[*(loc or []), enchant_indices[0]],
        )
    if has_boots and has_enchant and boots_indices[0] > enchant_indices[0]:
        _raise_invalid_ai_result(
            message=(
                "The boots item must appear before the enchant step "
                "in recommended_build_order."
            ),
            loc=[*(loc or []), enchant_indices[0]],
        )
    if len(build_order) == RECOMMEND_FULL_BUILD_MAX_STEPS and not (has_boots and has_enchant):
        _raise_invalid_ai_result(
            message=(
                "A 7-step recommended_build_order is allowed only when it includes "
                "one boots item and one separate enchant item."
            ),
            loc=loc,
        )
    if len(build_order) == RECOMMEND_FULL_BUILD_MIN_STEPS and has_boots and has_enchant:
        _raise_invalid_ai_result(
            message=(
                "When both boots and enchant are present, recommended_build_order must "
                "use 7 separate steps."
            ),
            loc=loc,
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
            ]
            if part
        )
    )
    if "enchant" in raw_tokens:
        return "enchant"
    if any(token in raw_tokens for token in ("boots", "greaves", "shoes")):
        return "boots"
    return None
