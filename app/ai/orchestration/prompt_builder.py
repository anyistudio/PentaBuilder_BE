import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.ai.orchestration.entity_appendix import build_involved_entity_parameter_appendix
from app.catalog.registry import CatalogEntity, CatalogSnapshot
from app.domain.enums import Game, Language, RunType
from app.domain.match_context import (
    MatchContext,
    ResponsePreferences,
    RuneSelection,
    build_slot_count_for_game,
)

PROMPTS_ROOT = Path(__file__).resolve().parents[1] / "prompts"


@dataclass(frozen=True)
class PromptPackage:
    system_prompt: str
    user_prompt: str
    stream_channel: str | None = None


def build_prompt_package(
    *,
    run_type: RunType,
    context: MatchContext,
    response_preferences: ResponsePreferences,
    operation_context: dict[str, Any],
    baseline: dict[str, Any] | None,
    reference_summary: str | None,
    calibration_summary: str | None,
    session_memory_summary: str | None,
    reply_to_run_summary: str | None,
    snapshot: CatalogSnapshot,
    tool_facts: dict[str, list[dict[str, Any]]] | None = None,
    output_mode: str = "json",
    response_schema: dict[str, Any] | None = None,
    streamed_text: str | None = None,
    validation_errors: list[str] | None = None,
    candidate_result: dict[str, Any] | None = None,
) -> PromptPackage:
    stream_channel = _stream_channel_for_run_type(run_type)
    prompt_files = [
        "shared/system_base.md",
        "shared/output_rules.md",
        "shared/generation_language_rules.md",
        "shared/localized_name_rules.md",
    ]
    if output_mode == "tool_plan":
        prompt_files.extend(
            [
                "shared/tool_rules.md",
                "shared/tool_planning_rules.md",
            ]
        )
    if output_mode == "repair_json":
        prompt_files.append("shared/repair_rules.md")
    prompt_files.append(f"{run_type.value}.md")

    system_sections = []
    for relative_path in prompt_files:
        prompt_text = _load_prompt(relative_path)
        if relative_path.endswith("generation_language_rules.md"):
            prompt_text = prompt_text.format(
                language=response_preferences.language.value,
                terminology_style=response_preferences.terminology_style.value,
            )
        system_sections.append(prompt_text)
    system_sections.append(
        _output_mode_block(
            output_mode=output_mode,
            stream_channel=stream_channel,
            response_schema=response_schema,
            streamed_text=streamed_text,
        )
    )
    system_prompt = "\n\n".join(section for section in system_sections if section)

    user_sections = [
        _match_overview_block(
            run_type=run_type,
            context=context,
            response_preferences=response_preferences,
        ),
        _context_bundle_block(
            run_type=run_type,
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
            operation_context=operation_context,
        ),
        _game_status_parameter_block(
            run_type=run_type,
            context=context,
            snapshot=snapshot,
        ),
        _operation_block(
            run_type=run_type,
            context=context,
            response_preferences=response_preferences,
            operation_context=operation_context,
            snapshot=snapshot,
            reply_to_run_summary=reply_to_run_summary,
        ),
        _baseline_block(
            baseline=baseline,
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
            operation_context=operation_context,
        ),
        _optional_text_block("Calibration Summary", calibration_summary),
        _optional_text_block("Reference Cache Summary", reference_summary),
        _optional_text_block("Session Memory Summary", session_memory_summary),
        _tool_facts_block(tool_facts=tool_facts),
        _available_tools_block(
            context=context,
            output_mode=output_mode,
        ),
        _repair_context_block(
            validation_errors=validation_errors,
            candidate_result=candidate_result,
        ),
        _localization_bundle_block(
            context=context,
            response_preferences=response_preferences,
            operation_context=operation_context,
            baseline=baseline,
            snapshot=snapshot,
            tool_facts=tool_facts,
        ),
    ]
    user_prompt = "\n\n".join(section for section in user_sections if section)
    return PromptPackage(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        stream_channel=stream_channel,
    )


@lru_cache(maxsize=64)
def _load_prompt(relative_path: str) -> str:
    return (PROMPTS_ROOT / relative_path).read_text(encoding="utf-8").strip()


def _stream_channel_for_run_type(run_type: RunType) -> str | None:
    if run_type == RunType.RECOMMEND_FULL_BUILD:
        return "summary"
    if run_type == RunType.EXPLAIN_SLOT:
        return "summary"
    if run_type == RunType.CHAT_FOLLOWUP:
        return "answer"
    return None


def _output_mode_block(
    *,
    output_mode: str,
    stream_channel: str | None,
    response_schema: dict[str, Any] | None,
    streamed_text: str | None,
) -> str:
    if output_mode == "stream_sections":
        if stream_channel is None:
            raise ValueError("stream_sections mode requires a streamable run type.")
        if response_schema is None:
            raise ValueError("stream_sections mode requires a response schema.")
        compact_schema = json.dumps(response_schema, ensure_ascii=False, separators=(",", ":"))
        return (
            "Streaming + structured mode:\n"
            "- Output exactly two top-level HTML-like sections in this exact order.\n"
            f"- First output `<display>` then only the final user-visible `{stream_channel}` text, "
            f"then `</display>`.\n"
            "- After that, output `<json>` then one valid JSON object, then `</json>`.\n"
            "- Do not output any text before `<display>`, between `</display>` and `<json>`, "
            "or after `</json>`.\n"
            f"- The JSON object's `{stream_channel}` field must exactly match the text inside "
            f"`<display>...</display>`.\n"
            "- Do not wrap the JSON in markdown fences.\n"
            f"- The JSON object must match this schema exactly:\n{compact_schema}"
        )
    if output_mode == "stream_text":
        if stream_channel is None:
            raise ValueError("stream_text mode requires a streamable run type.")
        return (
            "Streaming mode:\n"
            f"- Do not output JSON for this call.\n"
            f"- Output only the final user-visible `{stream_channel}` text.\n"
            "- Write plain natural language in the target output language.\n"
            "- Keep the wording consistent with the final structured answer."
        )
    if output_mode == "tool_plan":
        return (
            "Tool planning mode:\n"
            "- Return one JSON object only.\n"
            "- Do not output markdown fences or extra text.\n"
            "- Keep `reasoning_summary` short and user-visible. "
            "Do not reveal hidden chain-of-thought."
        )
    if output_mode == "repair_json":
        return (
            "Repair mode:\n"
            "- Return valid JSON that matches the provided response schema.\n"
            "- Fix only schema, slug, enum, slot, or contract issues from the failed candidate.\n"
            "- Preserve the same target language and the same grounded intent."
        )
    if streamed_text:
        return (
            "Structured generation mode:\n"
            "- Return valid JSON that matches the provided response schema.\n"
            f"- The `{stream_channel}` field has already been drafted.\n"
            f"- You must preserve this exact `{stream_channel}` text verbatim:\n"
            f"{streamed_text}"
        )
    return (
        "Structured generation mode:\n"
        "- Return valid JSON that matches the provided response schema.\n"
        "- Do not wrap the JSON in markdown fences."
    )


def _match_overview_block(
    *,
    run_type: RunType,
    context: MatchContext,
    response_preferences: ResponsePreferences,
) -> str:
    game_label = _game_label(context.game.value)
    enemy_labels = (
        ", ".join(enemy.champion_slug for enemy in context.enemy_team)
        if context.enemy_team
        else "none"
    )
    environment_tags = ", ".join(context.environment.tags) if context.environment.tags else "none"
    lines = [
        "## Match Overview",
        f"- Run type: {run_type.value}",
        f"- Game: {game_label}",
        f"- Data version: {context.data_version}",
        f"- Own champion slug: {context.own_champion_slug}",
        f"- Enemy champion slugs: {enemy_labels}",
        f"- Environment tags: {environment_tags}",
    ]
    if context.environment.free_text:
        lines.append(f"- Environment free text: {context.environment.free_text}")
    return "\n".join(lines)


def _context_bundle_block(
    *,
    run_type: RunType,
    context: MatchContext,
    response_preferences: ResponsePreferences,
    snapshot: CatalogSnapshot,
    operation_context: dict[str, Any],
) -> str:
    catalog = snapshot.catalogs[context.game]
    include_champion_profile = run_type != RunType.GAME_STATUS
    sections = [
        "## Injected Context Bundle",
        "### Own Champion",
        _format_champion(
            entity=catalog.champions_by_slug[context.own_champion_slug],
            response_preferences=response_preferences,
            include_profile=include_champion_profile,
        ),
    ]

    if context.enemy_team:
        sections.append("### Enemy Champions")
        for index, enemy in enumerate(context.enemy_team, start=1):
            sections.append(
                _format_enemy_context(
                    index=index,
                    entity=catalog.champions_by_slug[enemy.champion_slug],
                    build=enemy.build,
                    runes=enemy.runes.model_dump(mode="json"),
                    response_preferences=response_preferences,
                    snapshot=snapshot,
                    include_champion_summary=include_champion_profile,
                )
            )

    own_build_lines = _format_build_slots(
        build=context.own_build,
        context=context,
        response_preferences=response_preferences,
        snapshot=snapshot,
    )
    if own_build_lines:
        sections.append("### Current Build")
        sections.extend(own_build_lines)

    own_rune_lines = _format_rune_lines(
        rune_selection=context.own_runes.model_dump(mode="json"),
        context=context,
        response_preferences=response_preferences,
        snapshot=snapshot,
    )
    if own_rune_lines:
        sections.append("### Current Runes")
        sections.extend(own_rune_lines)
    return "\n".join(sections)


def _operation_block(
    *,
    run_type: RunType,
    context: MatchContext,
    response_preferences: ResponsePreferences,
    operation_context: dict[str, Any],
    snapshot: CatalogSnapshot,
    reply_to_run_summary: str | None,
) -> str:
    sections = ["## Task-Specific Context"]
    if run_type == RunType.RECOMMEND_FULL_BUILD:
        if context.game == Game.WILD_RIFT:
            sections.extend(
                [
                    "- Build order contract: return exactly 7 steps.",
                    (
                        "- Wild Rift build shape: 5 normal items + 1 boots item + "
                        "1 separate enchant item."
                    ),
                    "- In Wild Rift, boots and enchant are two separate ordered steps.",
                    "- The boots step must appear before the enchant step.",
                ]
            )
        else:
            sections.extend(
                [
                    "- Build order contract: return exactly 6 item steps.",
                    "- League of Legends PC does not use a separate enchant step in this contract.",
                ]
            )
    if run_type in {RunType.RECOMMEND_SLOT, RunType.EXPLAIN_SLOT}:
        slot_index = int(operation_context.get("slot_index", 0))
        current_item = context.own_build[slot_index]
        sections.append(f"- Target slot index: {slot_index}")
        sections.append(
            "- Current slot item: "
            + _format_item_reference(
                current_item,
                context,
                response_preferences,
                snapshot,
            )
        )

    if run_type == RunType.COMPARE_BUILDS:
        comparison_context = operation_context.get("comparison_context", {})
        build_a_lines = _format_build_slots(
            build=context.own_build,
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
        )
        if build_a_lines:
            sections.append("### Build A")
            sections.extend(build_a_lines)

        build_a_rune_lines = _format_rune_lines(
            rune_selection=context.own_runes.model_dump(mode="json"),
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
        )
        if build_a_rune_lines:
            sections.append("### Build A Runes")
            sections.extend(build_a_rune_lines)

        build_b_lines = _format_build_slots(
            build=comparison_context.get("own_build") or [],
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
        )
        if build_b_lines:
            sections.append("### Build B")
            sections.extend(build_b_lines)

        build_b_rune_lines = _format_rune_lines(
            rune_selection=_normalize_rune_selection(comparison_context.get("own_runes")),
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
        )
        if build_b_rune_lines:
            sections.append("### Build B Runes")
            sections.extend(build_b_rune_lines)

    if run_type == RunType.CHAT_FOLLOWUP:
        sections.append(f"- User follow-up question: {operation_context.get('user_message', '')}")
        if operation_context.get("reply_to_run_id"):
            sections.append(f"- Reply-to run id: {operation_context['reply_to_run_id']}")
        if reply_to_run_summary:
            sections.append("### Reply-To Run Summary")
            sections.append(reply_to_run_summary)
    if run_type == RunType.GAME_STATUS:
        own_tower_target = _tower_target_label(
            str(operation_context.get("own_current_tower_target", "outer_tower"))
        )
        enemy_tower_targets = _game_status_enemy_tower_targets(
            context=context,
            operation_context=operation_context,
        )
        sections.extend(
            [
                (
                    "- Assumed match duration: "
                    f"{_assumed_match_duration_minutes(context)} minutes"
                ),
                f"- Own current tower target: {own_tower_target}",
                (
                    "- Enemy current tower targets: "
                    + (
                        ", ".join(enemy_tower_targets)
                        if enemy_tower_targets
                        else "default to first tower for every enemy"
                    )
                ),
                (
                    "- Estimation contract: output the user's kill cadence versus each enemy, "
                    "each enemy's kill cadence versus the user, each enemy's tower push rate, "
                    "and the user's tower push rate against each subject's current tower target. "
                    "Keep the reasons anchored in currently owned items first, then explain how "
                    "those items interact with kit and matchup."
                ),
            ]
        )
    return "\n".join(sections)


def _baseline_block(
    *,
    baseline: dict[str, Any] | None,
    context: MatchContext,
    response_preferences: ResponsePreferences,
    snapshot: CatalogSnapshot,
    operation_context: dict[str, Any],
) -> str:
    if not baseline:
        return ""
    sections = ["## Baseline Build Reference"]
    baseline_build_order = (
        baseline.get("recommended_build_order")
        or baseline.get("recommended_build")
        or []
    )
    sections.extend(
        _format_build_order(
            build_order=baseline_build_order,
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
        )
    )
    baseline_rune_lines = _format_rune_lines(
        rune_selection=baseline.get("recommended_runes") or {},
        context=context,
        response_preferences=response_preferences,
        snapshot=snapshot,
    )
    if baseline_rune_lines:
        sections.append("### Baseline Runes")
        sections.extend(baseline_rune_lines)
    if baseline.get("summary"):
        sections.append(f"- Baseline note: {baseline['summary']}")
    return "\n".join(sections)


def _optional_text_block(title: str, content: str | None) -> str:
    if not content:
        return ""
    return f"## {title}\n{content}"


def _game_status_parameter_block(
    *,
    run_type: RunType,
    context: MatchContext,
    snapshot: CatalogSnapshot,
) -> str:
    if run_type != RunType.GAME_STATUS:
        return ""
    appendix = _compact_game_status_prompt_appendix(
        build_involved_entity_parameter_appendix(context=context, snapshot=snapshot)
    )
    return "\n".join(
        [
            "## Detailed Parameter Appendix",
            (
                "Use this appendix as grounded structured data for the estimates. "
                "These parameters come directly from the current catalog snapshot."
            ),
            json.dumps(appendix, ensure_ascii=False, indent=2),
        ]
    )


def _compact_game_status_prompt_appendix(appendix: dict[str, Any]) -> dict[str, Any]:
    return _compact_mapping(
        {
            "own_side": _compact_game_status_side(appendix.get("own_side") or {}),
            "enemy_team": [
                _compact_mapping(
                    {
                        "champion_slug": enemy.get("champion_slug"),
                        "champion": _compact_game_status_champion(enemy.get("champion") or {}),
                        "build": [
                            _compact_game_status_build_slot(slot)
                            for slot in enemy.get("build") or []
                        ],
                        "runes": _compact_game_status_runes(enemy.get("runes") or {}),
                    }
                )
                for enemy in appendix.get("enemy_team") or []
            ],
        }
    )


def _compact_game_status_side(side: dict[str, Any]) -> dict[str, Any]:
    return _compact_mapping(
        {
            "champion": _compact_game_status_champion(side.get("champion") or {}),
            "build": [
                _compact_game_status_build_slot(slot)
                for slot in side.get("build") or []
            ],
            "runes": _compact_game_status_runes(side.get("runes") or {}),
        }
    )


def _compact_game_status_champion(champion: dict[str, Any]) -> dict[str, Any]:
    infobox = champion.get("infobox") or {}
    return _compact_mapping(
        {
            "slug": champion.get("slug"),
            "infobox": _compact_mapping(
                {
                    "Adaptive type": infobox.get("Adaptive type"),
                    "Class(es)": infobox.get("Class(es)"),
                    "Position(s)": infobox.get("Position(s)"),
                    "Range type": infobox.get("Range type"),
                    "Resource": infobox.get("Resource"),
                }
            ),
            "abilities": [
                _compact_mapping(
                    {
                        "skill": ability.get("skill"),
                        "name": ability.get("name"),
                        "damage_type": ability.get("damage_type"),
                        "targeting": ability.get("targeting"),
                        "range": ability.get("range"),
                        "effect_radius": ability.get("effect_radius"),
                        "width": ability.get("width"),
                        "cooldown": ability.get("cooldown"),
                        "cost": ability.get("cost"),
                        "leveling": _trim_text(str(ability.get("leveling") or ""), 140),
                        "description": _trim_text(
                            str(ability.get("description") or ""),
                            180,
                        ),
                    }
                )
                for ability in champion.get("abilities") or []
            ],
        }
    )


def _compact_game_status_build_slot(slot: dict[str, Any]) -> dict[str, Any]:
    item = slot.get("item") or {}
    return _compact_mapping(
        {
            "slot_index": slot.get("slot_index"),
            "item_slug": slot.get("item_slug"),
            "item": _compact_mapping(
                {
                    "slug": item.get("slug"),
                    "stats": item.get("stats"),
                    "description": _trim_text(str(item.get("description") or ""), 180),
                }
            ),
            "missing": slot.get("missing"),
        }
    )


def _compact_game_status_runes(runes: dict[str, Any]) -> dict[str, Any]:
    return _compact_mapping(
        {
            "primary": [
                _compact_game_status_rune(rune)
                for rune in runes.get("primary") or []
            ],
            "secondary": [
                _compact_game_status_rune(rune)
                for rune in runes.get("secondary") or []
            ],
        }
    )


def _compact_game_status_rune(rune: dict[str, Any]) -> dict[str, Any]:
    return _compact_mapping(
        {
            "slug": rune.get("slug"),
            "path": rune.get("path"),
            "slot": rune.get("slot"),
            "description": _trim_text(str(rune.get("description") or ""), 140),
            "missing": rune.get("missing"),
        }
    )


def _compact_mapping(value: dict[str, Any]) -> dict[str, Any]:
    compacted: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, dict):
            nested = _compact_mapping(item)
            if nested:
                compacted[key] = nested
            continue
        if isinstance(item, list):
            nested_list = []
            for list_item in item:
                if isinstance(list_item, dict):
                    nested = _compact_mapping(list_item)
                    if nested:
                        nested_list.append(nested)
                    continue
                if isinstance(list_item, str):
                    compact = " ".join(list_item.split())
                    if compact:
                        nested_list.append(compact)
                    continue
                if list_item is not None:
                    nested_list.append(list_item)
            if nested_list:
                compacted[key] = nested_list
            continue
        if isinstance(item, str):
            compact = " ".join(item.split())
            if compact:
                compacted[key] = compact
            continue
        if item is not None:
            compacted[key] = item
    return compacted


def _tower_target_label(value: str) -> str:
    if value == "inner_tower":
        return "second tower"
    if value == "nexus":
        return "nexus"
    return "first tower"


def _game_status_enemy_tower_targets(
    *,
    context: MatchContext,
    operation_context: dict[str, Any],
) -> list[str]:
    targets_by_slug = {
        str(item.get("champion_slug")): _tower_target_label(
            str(item.get("tower_target", "outer_tower"))
        )
        for item in operation_context.get("enemy_current_tower_targets", [])
        if isinstance(item, dict)
    }
    lines: list[str] = []
    for enemy in context.enemy_team:
        lines.append(
            f"{enemy.champion_slug} -> "
            f"{targets_by_slug.get(enemy.champion_slug, 'first tower')}"
        )
    return lines


def _tool_facts_block(tool_facts: dict[str, list[dict[str, Any]]] | None) -> str:
    if not tool_facts:
        return ""
    sections = ["## Tool Facts"]
    for tool_name in sorted(tool_facts):
        for index, result in enumerate(tool_facts[tool_name], start=1):
            sections.append(f"### {tool_name} #{index}")
            sections.extend(_format_tool_result(tool_name=tool_name, result=result))
    return "\n".join(section for section in sections if section)


def _available_tools_block(*, context: MatchContext, output_mode: str) -> str:
    if output_mode != "tool_plan":
        return ""
    return "\n".join(
        [
            "## Available Tools",
            f"- Current game for every tool call: {context.game.value}",
            f"- Current data version for every tool call: {context.data_version}",
            "- `get_champion` / `get_item` / `get_rune`: read one entity by canonical slug.",
            "- `batch_get_entities`: read up to 12 entities of the same type in one round.",
            (
                "- `search_catalog`: fuzzy search one or more entity names or aliases "
                "and highlight the best-ranked real ID."
            ),
            (
                "- `list_catalog_candidates`: list filtered candidate slugs. "
                "Requires at least one filter."
            ),
            (
                "- `list_item_ids`: list real item IDs for one or more broad item categories "
                "such as `physical`, `magic`, `boots`, or `enchant`."
            ),
            (
                "- Supported filters: `position`, `lane`, `role`, `class`, "
                "`category`, `subtype`, `path`, `slot`, `keyword`, `keywords`."
            ),
            "- `resolve_catalog_slug`: map one raw name or alias to a canonical slug.",
            "- Direct canonical slugs are allowed only when you are already highly confident.",
            "- If the slug is uncertain or a lookup may fail, call `resolve_catalog_slug` first.",
            "- Prefer one search plus one batch lookup when you need to compare candidates.",
        ]
    )


def _repair_context_block(
    *,
    validation_errors: list[str] | None,
    candidate_result: dict[str, Any] | None,
) -> str:
    if not validation_errors and not candidate_result:
        return ""
    sections = ["## Repair Context"]
    if validation_errors:
        sections.append("### Validation Errors")
        sections.extend(f"- {error}" for error in validation_errors)
    if candidate_result:
        sections.append("### Candidate Result")
        sections.extend(_format_candidate_lines(candidate_result))
    return "\n".join(sections)


def _localization_bundle_block(
    *,
    context: MatchContext,
    response_preferences: ResponsePreferences,
    operation_context: dict[str, Any],
    baseline: dict[str, Any] | None,
    snapshot: CatalogSnapshot,
    tool_facts: dict[str, list[dict[str, Any]]] | None,
) -> str:
    relevant_slugs = {
        context.own_champion_slug,
        *(enemy.champion_slug for enemy in context.enemy_team),
        *(slot for slot in context.own_build if slot),
        *(
            slot
            for enemy in context.enemy_team
            for slot in enemy.build
            if slot
        ),
        *(context.own_runes.primary or []),
        *(context.own_runes.secondary or []),
        *(
            rune_slug
            for enemy in context.enemy_team
            for rune_slug in [*(enemy.runes.primary or []), *(enemy.runes.secondary or [])]
        ),
    }
    if baseline:
        relevant_slugs.update(
            slug
            for slug in (
                baseline.get("recommended_build_order")
                or baseline.get("recommended_build")
                or []
            )
            if slug
        )
        rune_selection = baseline.get("recommended_runes") or {}
        relevant_slugs.update(rune_selection.get("primary") or [])
        relevant_slugs.update(rune_selection.get("secondary") or [])
    comparison_context = operation_context.get("comparison_context", {})
    relevant_slugs.update(slug for slug in comparison_context.get("own_build") or [] if slug)
    comparison_runes = _normalize_rune_selection(comparison_context.get("own_runes"))
    relevant_slugs.update(comparison_runes.get("primary") or [])
    relevant_slugs.update(comparison_runes.get("secondary") or [])
    relevant_slugs.update(_slugs_from_tool_facts(tool_facts))

    lines = ["## Localization Bundle"]
    for slug in sorted(relevant_slugs):
        entity = _lookup_entity(snapshot=snapshot, context=context, slug=slug)
        if entity is None:
            continue
        target_name = entity.preferred_name(
            response_preferences.language,
            response_preferences.terminology_style,
        )
        zh_name = entity.display_names.get(Language.ZH_CN.value) or entity.english_name
        aliases = ", ".join(entity.aliases[:4]) if entity.aliases else "none"
        lines.append(
            f"- {slug}: target=`{target_name}`, zh=`{zh_name}`, "
            f"en=`{entity.english_name}`, aliases={aliases}"
        )
    return "\n".join(lines)


def _format_tool_result(tool_name: str, result: dict[str, Any]) -> list[str]:
    if tool_name == "search_catalog":
        matches = result.get("matches") or []
        if not matches:
            return ["- No matches returned."]
        lines = [f"- Match count: {result.get('match_count', len(matches))}"]
        top_match = result.get("top_match") or {}
        if top_match:
            lines.append("- Top match:")
            lines.append("  " + _entity_fact_line(top_match).removeprefix("- "))
        remaining_matches = matches
        if top_match and matches:
            top_match_id = top_match.get("id") or top_match.get("slug")
            remaining_matches = [
                match
                for match in matches
                if (match.get("id") or match.get("slug")) != top_match_id
            ]
        if remaining_matches:
            lines.append("- Alternative candidates:")
        for index, match in enumerate(remaining_matches, start=1):
            matched_fields = ", ".join(match.get("matched_fields") or ["name"])
            hints: list[str] = [f"matched={matched_fields}"]
            if match.get("fuzzy_score"):
                hints.append(f"fuzzy={match['fuzzy_score']}")
            if match.get("match_score"):
                hints.append(f"score={match['match_score']}")
            if match.get("cost"):
                hints.append(f"cost={match['cost']}")
            if match.get("stats"):
                hints.append("stats=" + ", ".join(str(item) for item in match["stats"][:2]))
            if match.get("path"):
                hints.append(f"path={match['path']}")
            if match.get("slot"):
                hints.append(f"slot={match['slot']}")
            if match.get("class_text"):
                hints.append(f"class={match['class_text']}")
            if match.get("position_tags"):
                hints.append(
                    "positions=" + ", ".join(str(tag) for tag in match["position_tags"][:3])
                )
            if match.get("matched_term"):
                hints.append(f"matched_term={match['matched_term']}")
            lines.append(
                f"- #{index} {match.get('name', 'Unknown')} | "
                f"ID=`{match.get('id') or match.get('slug', '')}` | "
                + " | ".join(hints)
            )
        return lines
    if tool_name == "list_catalog_candidates":
        candidates = result.get("candidates") or []
        lines = [
            f"- Candidate count: {result.get('candidate_count', len(candidates))}",
        ]
        applied_filters = result.get("applied_filters") or {}
        if applied_filters:
            filter_text = ", ".join(
                f"{key}={', '.join(value) if isinstance(value, list) else value}"
                for key, value in applied_filters.items()
            )
            lines.append(f"- Applied filters: {filter_text}")
        preview = candidates[:10]
        if preview:
            lines.append("- Candidate preview: " + _inline_candidate_preview(preview))
        remaining = len(candidates) - len(preview)
        if remaining > 0:
            lines.append(f"- ... plus {remaining} more filtered candidates.")
        return lines
    if tool_name == "list_item_ids":
        items = result.get("items") or []
        categories = result.get("requested_categories") or []
        category_text = ", ".join(str(category) for category in categories) or "all"
        lines = [
            f"- Requested categories: {category_text}",
            f"- Item count: {result.get('item_count', len(items))}",
        ]
        for item in items:
            lines.append(_compact_item_id_line(item))
        return lines
    if tool_name == "resolve_catalog_slug":
        lines = [f"- Resolution status: {result.get('resolution_status', 'unknown')}"]
        if result.get("raw_name"):
            lines.append(f"- Raw name: {result['raw_name']}")
        if result.get("resolved_slug"):
            lines.append(
                f"- Resolved ID: `{result.get('resolved_id') or result['resolved_slug']}` "
                f"({result.get('resolved_name') or 'Unknown'})"
            )
        resolved_entity = result.get("resolved_entity") or {}
        if resolved_entity:
            lines.append("- Resolved entity:")
            lines.append("  " + _entity_fact_line(resolved_entity).removeprefix("- "))
        if result.get("resolved_by"):
            lines.append(
                "- Resolved by: "
                f"{result['resolved_by']} | confidence={result.get('confidence', 'unknown')}"
            )
        if result.get("selector_summary"):
            lines.append(f"- Selector note: {result['selector_summary']}")
        applied_filters = result.get("applied_filters") or {}
        if applied_filters:
            filter_text = ", ".join(
                f"{key}={', '.join(value) if isinstance(value, list) else value}"
                for key, value in applied_filters.items()
            )
            lines.append(f"- Applied filters: {filter_text}")
        candidates = result.get("candidates") or []
        if candidates:
            lines.append("- Candidate preview: " + _inline_candidate_preview(candidates[:8]))
        return lines
    if tool_name == "batch_get_entities":
        entities = result.get("entities") or []
        missing_slugs = result.get("missing_slugs") or []
        lines = []
        for entity in entities:
            lines.append(_entity_fact_line(entity))
        if missing_slugs:
            lines.append("- Missing slugs: " + ", ".join(f"`{slug}`" for slug in missing_slugs))
        return lines or ["- No entities returned."]
    payload = (
        result.get("champion")
        or result.get("item")
        or result.get("rune")
        or {}
    )
    return [_entity_fact_line(payload)]


def _entity_fact_line(entity: dict[str, Any]) -> str:
    if not entity:
        return "- No entity returned."
    entity_id = entity.get("id") or entity.get("slug", "")
    parts = [f"- {entity.get('name', 'Unknown')} | ID=`{entity_id}`"]
    if entity.get("match_score"):
        parts.append(f"score={entity['match_score']}")
    if entity.get("fuzzy_score"):
        parts.append(f"fuzzy={entity['fuzzy_score']}")
    if entity.get("matched_term"):
        parts.append(f"matched_term={entity['matched_term']}")
    if entity.get("class_text"):
        parts.append(f"class={entity['class_text']}")
    if entity.get("position_text"):
        parts.append(f"positions={entity['position_text']}")
    if entity.get("adaptive_type"):
        parts.append(f"adaptive={entity['adaptive_type']}")
    if entity.get("range_type"):
        parts.append(f"range={entity['range_type']}")
    if entity.get("resource"):
        parts.append(f"resource={entity['resource']}")
    if entity.get("cost"):
        parts.append(f"cost={entity['cost']}")
    if entity.get("stats"):
        parts.append("stats=" + ", ".join(str(value) for value in entity["stats"][:2]))
    if entity.get("path"):
        parts.append(f"path={entity['path']}")
    if entity.get("slot"):
        parts.append(f"slot={entity['slot']}")
    short_effect = _short_effect_text(entity)
    if short_effect:
        parts.append(f"effect={short_effect}")
    abilities = entity.get("abilities") or []
    for ability in abilities[:3]:
        parts.append(
            "ability="
            + " | ".join(
                value
                for value in [
                    str(ability.get("skill") or "?"),
                    str(ability.get("name") or "Unnamed"),
                    str(ability.get("damage_type") or "mixed"),
                ]
                if value
            )
        )
    return " | ".join(parts)

def _inline_candidate_preview(candidates: list[dict[str, Any]]) -> str:
    preview_parts: list[str] = []
    for candidate in candidates:
        if not candidate:
            continue
        hints: list[str] = []
        if candidate.get("class_text"):
            hints.append(str(candidate["class_text"]))
        if candidate.get("position_tags"):
            hints.append("/".join(str(tag) for tag in candidate["position_tags"][:2]))
        if candidate.get("path"):
            hints.append(str(candidate["path"]))
        if candidate.get("slot"):
            hints.append(str(candidate["slot"]))
        if candidate.get("cost"):
            hints.append(f"cost={candidate['cost']}")
        if candidate.get("fuzzy_score"):
            hints.append(f"fuzzy={candidate['fuzzy_score']}")
        if candidate.get("main_attributes"):
            hints.append(", ".join(str(value) for value in candidate["main_attributes"][:2]))
        label = (
            f"{candidate.get('name', 'Unknown')} "
            f"(ID=`{candidate.get('id') or candidate.get('slug', '')}`)"
        )
        if hints:
            label += f" [{'; '.join(hints)}]"
        preview_parts.append(label)
    return " || ".join(preview_parts) if preview_parts else "none"


def _compact_item_id_line(item: dict[str, Any]) -> str:
    if not item:
        return "- No item returned."
    hints: list[str] = []
    if item.get("cost"):
        hints.append(f"cost={item['cost']}")
    if item.get("main_attributes"):
        hints.append(", ".join(str(value) for value in item["main_attributes"][:2]))
    return (
        f"- {item.get('name', 'Unknown')} | ID=`{item.get('id') or item.get('slug', '')}`"
        + (f" | {' | '.join(hints)}" if hints else "")
    )


def _short_effect_text(entity: dict[str, Any]) -> str | None:
    raw_text = str(entity.get("description") or "").strip()
    if not raw_text:
        return None
    first_sentence = raw_text.split(". ", 1)[0].strip()
    return _trim_text(first_sentence, 90) if first_sentence else None


def _format_candidate_lines(
    candidate_result: dict[str, Any],
    *,
    indent: int = 0,
) -> list[str]:
    lines: list[str] = []
    prefix = "  " * indent
    for key, value in candidate_result.items():
        label = f"{prefix}- {key}:"
        if isinstance(value, dict):
            lines.append(label)
            lines.extend(_format_candidate_lines(value, indent=indent + 1))
            continue
        if isinstance(value, list):
            if not value:
                lines.append(f"{label} []")
                continue
            lines.append(label)
            for item in value:
                if isinstance(item, dict):
                    lines.extend(_format_candidate_lines(item, indent=indent + 1))
                else:
                    lines.append(f"{prefix}  - {item}")
            continue
        lines.append(f"{label} {value}")
    return lines


def _slugs_from_tool_facts(tool_facts: dict[str, list[dict[str, Any]]] | None) -> set[str]:
    if not tool_facts:
        return set()
    slugs: set[str] = set()
    for tool_name, tool_results in tool_facts.items():
        for result in tool_results:
            slugs.update(_extract_slugs(result, tool_name=tool_name))
    return slugs


def _extract_slugs(value: Any, *, tool_name: str | None = None) -> set[str]:
    if isinstance(value, dict) and tool_name in {
        "list_catalog_candidates",
        "list_item_ids",
        "resolve_catalog_slug",
    }:
        slugs: set[str] = set()
        resolved_slug = value.get("resolved_slug")
        if isinstance(resolved_slug, str) and resolved_slug.startswith(("lol-", "wr-")):
            slugs.add(resolved_slug)
        for item in (value.get("items") or [])[:40]:
            slugs.update(_extract_slugs(item))
        for candidate in (value.get("candidates") or [])[:20]:
            slugs.update(_extract_slugs(candidate))
        return slugs
    if isinstance(value, str):
        return {value} if value.startswith(("lol-", "wr-")) else set()
    if isinstance(value, dict):
        slugs: set[str] = set()
        for item in value.values():
            slugs.update(_extract_slugs(item))
        return slugs
    if isinstance(value, list):
        slugs: set[str] = set()
        for item in value:
            slugs.update(_extract_slugs(item))
        return slugs
    return set()


def _normalize_rune_selection(value: Any) -> dict[str, Any]:
    if isinstance(value, RuneSelection):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {
            "primary": list(value.get("primary") or []),
            "secondary": list(value.get("secondary") or []),
        }
    return {"primary": [], "secondary": []}


def _format_enemy_context(
    *,
    index: int,
    entity: CatalogEntity,
    build: list[str | None],
    runes: dict[str, Any],
    response_preferences: ResponsePreferences,
    snapshot: CatalogSnapshot,
    include_champion_summary: bool = True,
) -> str:
    header = f"{index}. {_entity_label(entity, response_preferences)}"
    enemy_context = MatchContext(
        game=entity.game,
        data_version=snapshot.data_version,
        own_champion_slug=entity.slug,
    )
    build_lines = _format_build_slots(
        build=build,
        context=enemy_context,
        response_preferences=response_preferences,
        snapshot=snapshot,
    )
    rune_lines = _format_rune_lines(
        rune_selection=runes,
        context=enemy_context,
        response_preferences=response_preferences,
        snapshot=snapshot,
    )
    body: list[str] = []
    if include_champion_summary:
        body.append(f"   - Summary: {_champion_summary_line(entity)}")
    if build_lines:
        body.append("   - Known build slots:")
        body.extend(f"     - {line.removeprefix('- ')}" for line in build_lines)
    if rune_lines:
        body.append("   - Known runes:")
        body.extend(f"     - {line.removeprefix('- ')}" for line in rune_lines)
    return "\n".join([header, *body]) if body else header


def _format_champion(
    *,
    entity: CatalogEntity,
    response_preferences: ResponsePreferences,
    include_profile: bool = True,
) -> str:
    if not include_profile:
        return f"- {_entity_label(entity, response_preferences)}"
    raw_payload = entity.raw_payload if isinstance(entity.raw_payload, dict) else {}
    infobox = raw_payload.get("infobox", {})
    positions = infobox.get("Position(s)") or "unknown"
    class_text = infobox.get("Class(es)") or "unknown"
    range_type = infobox.get("Range type") or infobox.get("Attack range") or "unknown"
    resource = infobox.get("Resource") or "unknown"
    lines = [
        f"- {_entity_label(entity, response_preferences)}",
        f"- Role / class: {class_text}",
        f"- Positions: {positions}",
        f"- Range info: {range_type}",
        f"- Resource: {resource}",
    ]
    abilities = raw_payload.get("abilities") or []
    if abilities:
        lines.append("- Ability hooks:")
        for ability in abilities[:4]:
            lines.append(
                "  - "
                + " | ".join(
                    part
                    for part in [
                        str(ability.get("skill") or "?"),
                        str(ability.get("name") or "Unnamed"),
                        str(ability.get("damage_type") or "mixed"),
                        _trim_text(str(ability.get("blurb") or ""), 160),
                    ]
                    if part
                )
            )
    return "\n".join(lines)


def _format_build_slots(
    *,
    build: list[str | None],
    context: MatchContext,
    response_preferences: ResponsePreferences,
    snapshot: CatalogSnapshot,
) -> list[str]:
    build_slot_count = build_slot_count_for_game(context.game)
    slots = list(build[:build_slot_count]) + [None] * max(0, build_slot_count - len(build))
    lines: list[str] = []
    for slot_index, item_slug in enumerate(slots[:build_slot_count], start=1):
        if not item_slug:
            continue
        lines.append(
            f"- Slot {slot_index}: "
            + _format_item_reference(
                item_slug,
                context,
                response_preferences,
                snapshot,
            )
        )
    return lines


def _format_build_order(
    *,
    build_order: list[str | None],
    context: MatchContext,
    response_preferences: ResponsePreferences,
    snapshot: CatalogSnapshot,
) -> list[str]:
    build_slot_count = build_slot_count_for_game(context.game)
    lines: list[str] = []
    for step_index, item_slug in enumerate(build_order[:build_slot_count], start=1):
        lines.append(
            f"- Step {step_index}: "
            + _format_item_reference(
                item_slug,
                context,
                response_preferences,
                snapshot,
            )
        )
    return lines or ["- No ordered build steps provided."]


def _format_rune_lines(
    *,
    rune_selection: dict[str, Any],
    context: MatchContext,
    response_preferences: ResponsePreferences,
    snapshot: CatalogSnapshot,
) -> list[str]:
    primary = rune_selection.get("primary") or []
    secondary = rune_selection.get("secondary") or []
    lines: list[str] = []
    if primary:
        lines.append(
            f"- Primary: {_format_rune_list(primary, context, response_preferences, snapshot)}"
        )
    if secondary:
        lines.append(
            f"- Secondary: {_format_rune_list(secondary, context, response_preferences, snapshot)}"
        )
    return lines


def _format_rune_list(
    rune_slugs: list[str],
    context: MatchContext,
    response_preferences: ResponsePreferences,
    snapshot: CatalogSnapshot,
) -> str:
    if not rune_slugs:
        return "none"
    rendered = []
    for rune_slug in rune_slugs:
        entity = _lookup_entity(snapshot=snapshot, context=context, slug=rune_slug)
        if entity is None:
            rendered.append(rune_slug)
            continue
        description = _trim_text(str(entity.raw_payload.get("description") or ""), 120)
        path = entity.raw_payload.get("path") or entity.raw_payload.get(
            "attributes",
            {},
        ).get("Path")
        extra = f"; path={path}" if path else ""
        rendered.append(f"{_entity_label(entity, response_preferences)}{extra}; {description}")
    return " || ".join(rendered)


def _format_item_reference(
    item_slug: str | None,
    context: MatchContext,
    response_preferences: ResponsePreferences,
    snapshot: CatalogSnapshot,
) -> str:
    if not item_slug:
        return "empty"
    entity = _lookup_entity(snapshot=snapshot, context=context, slug=item_slug)
    if entity is None:
        return item_slug
    stats = entity.raw_payload.get("stats") or []
    description = _trim_text(str(entity.raw_payload.get("description") or ""), 120)
    stats_text = ", ".join(str(stat) for stat in stats[:3]) if stats else "no short stats"
    return (
        f"{_entity_label(entity, response_preferences)} | stats={stats_text} | "
        f"note={description or 'none'}"
    )


def _lookup_entity(
    *,
    snapshot: CatalogSnapshot,
    context: MatchContext,
    slug: str,
) -> CatalogEntity | None:
    catalog = snapshot.catalogs[context.game]
    return (
        catalog.champions_by_slug.get(slug)
        or catalog.items_by_slug.get(slug)
        or catalog.runes_by_slug.get(slug)
    )


def _entity_label(entity: CatalogEntity, response_preferences: ResponsePreferences) -> str:
    name = entity.preferred_name(
        response_preferences.language,
        response_preferences.terminology_style,
    )
    return f"{name} (`{entity.slug}`)"


def _champion_summary_line(entity: CatalogEntity) -> str:
    raw_payload = entity.raw_payload if isinstance(entity.raw_payload, dict) else {}
    infobox = raw_payload.get("infobox", {})
    class_text = infobox.get("Class(es)") or "unknown class"
    positions = infobox.get("Position(s)") or "unknown position"
    return f"{class_text}; {positions}"


def _game_label(game_value: str) -> str:
    return "LoL PC" if game_value == "lol" else "Wild Rift"


def _assumed_match_duration_minutes(context: MatchContext) -> int:
    return 15 if "aram" in context.environment.tags else 30


def _trim_text(value: str, limit: int) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."
