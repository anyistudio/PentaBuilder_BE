from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.catalog.registry import CatalogSnapshot
from app.core.errors import ApiError
from app.domain.enums import RunType
from app.domain.match_context import MatchContext, RuneSelection, validate_slug_for_game


class RuneSelectionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    primary: list[str] = Field(default_factory=list)
    secondary: list[str] = Field(default_factory=list)


class SlotNote(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slot_index: int = Field(ge=0, le=5)
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

    recommended_build: list[str] = Field(min_length=6, max_length=6)
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
                "recommended_build": _build_array_schema(
                    description="The single best six-slot build using canonical item slugs."
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
                                "maximum": 5,
                                "description": "The affected slot index.",
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
            "required": ["recommended_build", "recommended_runes", "summary", "slot_notes"],
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
        )
        recommended_runes = _validate_rune_selection(
            context=context,
            snapshot=snapshot,
            rune_selection=result["recommended_runes"],
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
        recommended_build = _validate_build_slots(
            context=context,
            snapshot=snapshot,
            build=result["recommended_build"],
            allow_null=False,
        )
        _ensure_filled_slots_preserved(
            current_build=context.own_build,
            proposed_build=recommended_build,
        )
        recommended_runes = _validate_rune_selection(
            context=context,
            snapshot=snapshot,
            rune_selection=result["recommended_runes"],
        )
        result["recommended_build"] = recommended_build
        result["recommended_runes"] = recommended_runes
        result["score"] = None
        result["build"] = recommended_build
        result["runes"] = recommended_runes
        result["explanations"] = [
            {"target": f"slot:{note['slot_index']}", "text": note["text"]}
            for note in result["slot_notes"]
        ]
        result["alternatives"] = []
        return result

    if run_type == RunType.RECOMMEND_SLOT:
        requested_slot_index = int(operation_context.get("slot_index", -1))
        if result["slot_index"] != requested_slot_index:
            raise ApiError("Invalid AI result.", code="provider_error", status_code=502)
        recommended_item_slug = _validate_item_slug(
            context=context,
            snapshot=snapshot,
            item_slug=result["recommended_item_slug"],
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
                ),
                "reason": alternative["reason"],
            }
            for alternative in result["alternatives"]
        ]
        return result

    if run_type == RunType.EXPLAIN_SLOT:
        requested_slot_index = int(operation_context.get("slot_index", -1))
        if result["slot_index"] != requested_slot_index:
            raise ApiError("Invalid AI result.", code="provider_error", status_code=502)
        current_item_slug = context.own_build[requested_slot_index]
        if result["current_item_slug"] is not None:
            validated_current_item = _validate_item_slug(
                context=context,
                snapshot=snapshot,
                item_slug=result["current_item_slug"],
            )
            if current_item_slug is not None and validated_current_item != current_item_slug:
                raise ApiError("Invalid AI result.", code="provider_error", status_code=502)
            result["current_item_slug"] = validated_current_item
        else:
            result["current_item_slug"] = current_item_slug
        if result["best_item_slug"] is not None:
            result["best_item_slug"] = _validate_item_slug(
                context=context,
                snapshot=snapshot,
                item_slug=result["best_item_slug"],
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
        )
        runes_b = _validate_rune_selection(
            context=context,
            snapshot=snapshot,
            rune_selection=comparison_context.get("own_runes") or {},
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


def _build_array_schema(*, description: str) -> dict[str, Any]:
    return {
        "type": "array",
        "description": description,
        "minItems": 6,
        "maxItems": 6,
        "items": {"type": "string"},
    }


def _nullable_build_array_schema(*, description: str) -> dict[str, Any]:
    return {
        "type": "array",
        "description": description,
        "minItems": 6,
        "maxItems": 6,
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


def _validate_item_slug(
    *,
    context: MatchContext,
    snapshot: CatalogSnapshot,
    item_slug: str,
) -> str:
    validated_slug = validate_slug_for_game(context.game, item_slug)
    if validated_slug not in snapshot.catalogs[context.game].items_by_slug:
        raise ApiError("Invalid AI result.", code="provider_error", status_code=502)
    return validated_slug


def _validate_rune_selection(
    *,
    context: MatchContext,
    snapshot: CatalogSnapshot,
    rune_selection: dict[str, Any],
) -> dict[str, Any]:
    selection = RuneSelection(**rune_selection)
    validated_primary = []
    validated_secondary = []
    for rune_slug in selection.primary:
        validated_slug = validate_slug_for_game(context.game, rune_slug)
        if validated_slug not in snapshot.catalogs[context.game].runes_by_slug:
            raise ApiError("Invalid AI result.", code="provider_error", status_code=502)
        validated_primary.append(validated_slug)
    for rune_slug in selection.secondary:
        validated_slug = validate_slug_for_game(context.game, rune_slug)
        if validated_slug not in snapshot.catalogs[context.game].runes_by_slug:
            raise ApiError("Invalid AI result.", code="provider_error", status_code=502)
        validated_secondary.append(validated_slug)
    return {"primary": validated_primary, "secondary": validated_secondary}


def _validate_build_slots(
    *,
    context: MatchContext,
    snapshot: CatalogSnapshot,
    build: list[str | None],
    allow_null: bool,
) -> list[str | None]:
    if len(build) != 6:
        raise ApiError("Invalid AI result.", code="provider_error", status_code=502)
    validated_build: list[str | None] = []
    for slot in build:
        if slot is None:
            if not allow_null:
                raise ApiError("Invalid AI result.", code="provider_error", status_code=502)
            validated_build.append(None)
            continue
        validated_slot = _validate_item_slug(
            context=context,
            snapshot=snapshot,
            item_slug=slot,
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
            raise ApiError("Invalid AI result.", code="provider_error", status_code=502)


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
            raise ApiError("Invalid AI result.", code="provider_error", status_code=502)
