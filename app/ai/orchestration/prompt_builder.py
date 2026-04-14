from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.catalog.registry import CatalogEntity, CatalogSnapshot
from app.domain.enums import Language, RunType
from app.domain.match_context import MatchContext, ResponsePreferences, RuneSelection

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
    streamed_text: str | None = None,
    validation_errors: list[str] | None = None,
    candidate_result: dict[str, Any] | None = None,
) -> PromptPackage:
    stream_channel = _stream_channel_for_run_type(run_type)
    prompt_files = [
        "shared/system_base.md",
        "shared/tool_rules.md",
        "shared/output_rules.md",
        "shared/generation_language_rules.md",
        "shared/localized_name_rules.md",
    ]
    if output_mode == "tool_plan":
        prompt_files.append("shared/tool_planning_rules.md")
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
            context=context,
            response_preferences=response_preferences,
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
    streamed_text: str | None,
) -> str:
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
            "- Return only the next minimal JSON tool plan.\n"
            "- Fill `reasoning_summary` with a short user-visible progress update.\n"
            "- The summary must explain what facts are missing and why these tool calls help.\n"
            "- Never reveal hidden chain-of-thought or private reasoning; keep it concise.\n"
            "- If the injected context and current tool facts are already enough, return "
            "`done=true` and an empty `tool_calls` list.\n"
            "- Prefer one or two high-value calls over broad fishing."
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
        f"- Target language: {response_preferences.language.value}",
        f"- Terminology style: {response_preferences.terminology_style.value}",
        f"- Own champion slug: {context.own_champion_slug}",
        f"- Enemy champion slugs: {enemy_labels}",
        f"- Environment tags: {environment_tags}",
    ]
    if context.environment.free_text:
        lines.append(f"- Environment free text: {context.environment.free_text}")
    return "\n".join(lines)


def _context_bundle_block(
    *,
    context: MatchContext,
    response_preferences: ResponsePreferences,
    snapshot: CatalogSnapshot,
) -> str:
    catalog = snapshot.catalogs[context.game]
    sections = [
        "## Injected Context Bundle",
        "### Own Champion",
        _format_champion(
            entity=catalog.champions_by_slug[context.own_champion_slug],
            response_preferences=response_preferences,
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
                )
            )

    sections.append("### Current Build")
    sections.extend(
        _format_build_slots(
            build=context.own_build,
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
        )
    )
    sections.append("### Current Runes")
    sections.extend(
        _format_rune_lines(
            rune_selection=context.own_runes.model_dump(mode="json"),
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
        )
    )
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
        sections.append("### Build A")
        sections.extend(
            _format_build_slots(
                build=context.own_build,
                context=context,
                response_preferences=response_preferences,
                snapshot=snapshot,
            )
        )
        sections.append("### Build A Runes")
        sections.extend(
            _format_rune_lines(
                rune_selection=context.own_runes.model_dump(mode="json"),
                context=context,
                response_preferences=response_preferences,
                snapshot=snapshot,
            )
        )
        sections.append("### Build B")
        sections.extend(
            _format_build_slots(
                build=comparison_context.get("own_build") or [],
                context=context,
                response_preferences=response_preferences,
                snapshot=snapshot,
            )
        )
        sections.append("### Build B Runes")
        sections.extend(
            _format_rune_lines(
                rune_selection=_normalize_rune_selection(comparison_context.get("own_runes")),
                context=context,
                response_preferences=response_preferences,
                snapshot=snapshot,
            )
        )

    if run_type == RunType.CHAT_FOLLOWUP:
        sections.append(f"- User follow-up question: {operation_context.get('user_message', '')}")
        if operation_context.get("reply_to_run_id"):
            sections.append(f"- Reply-to run id: {operation_context['reply_to_run_id']}")
        if reply_to_run_summary:
            sections.append("### Reply-To Run Summary")
            sections.append(reply_to_run_summary)
    return "\n".join(sections)


def _baseline_block(
    *,
    baseline: dict[str, Any] | None,
    context: MatchContext,
    response_preferences: ResponsePreferences,
    snapshot: CatalogSnapshot,
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
    sections.append("### Baseline Runes")
    sections.extend(
        _format_rune_lines(
            rune_selection=baseline.get("recommended_runes") or {},
            context=context,
            response_preferences=response_preferences,
            snapshot=snapshot,
        )
    )
    if baseline.get("summary"):
        sections.append(f"- Baseline note: {baseline['summary']}")
    return "\n".join(sections)


def _optional_text_block(title: str, content: str | None) -> str:
    if not content:
        return ""
    return f"## {title}\n{content}"


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
            "- `get_champion`: read one champion ToolView by canonical slug.",
            "- `get_item`: read one item ToolView by canonical slug.",
            "- `get_rune`: read one rune ToolView by canonical slug.",
            "- `batch_get_entities`: read up to 12 entities of the same type in one round.",
            (
                "- `search_catalog`: fuzzy search one entity type and return "
                "light candidate summaries."
            ),
            (
                "- `list_catalog_candidates`: list filtered candidate slugs for one "
                "entity type. Requires `game`, `entity_type`, and at least one filter."
            ),
            (
                "- `resolve_catalog_slug`: resolve one raw name into a canonical slug "
                "using exact match, deterministic ranking, filtered candidate listing, "
                "and an internal selector model if needed."
            ),
            (
                "- Prefer `resolve_catalog_slug` before any direct slug lookup "
                "when the slug is not already confirmed."
            ),
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
        *(context.own_runes.primary or []),
        *(context.own_runes.secondary or []),
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
        lines = []
        for match in matches:
            base = (
                f"- {match.get('name', 'Unknown')} (`{match.get('slug', '')}`) | "
                f"matched={', '.join(match.get('matched_fields') or ['name'])}"
            )
            aliases = match.get("aliases") or []
            if aliases:
                base += f" | aliases={', '.join(str(alias) for alias in aliases[:4])}"
            if match.get("cost"):
                base += f" | cost={match['cost']}"
            if match.get("stats"):
                base += f" | stats={', '.join(str(item) for item in match['stats'][:3])}"
            if match.get("path"):
                base += f" | path={match['path']}"
            if match.get("slot"):
                base += f" | slot={match['slot']}"
            if match.get("class_text"):
                base += f" | class={match['class_text']}"
            if match.get("position_tags"):
                base += f" | positions={', '.join(str(tag) for tag in match['position_tags'][:4])}"
            lines.append(base)
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
        preview = candidates[:12]
        for candidate in preview:
            lines.extend(_format_candidate_tool_view(candidate))
        remaining = len(candidates) - len(preview)
        if remaining > 0:
            lines.append(f"- ... plus {remaining} more filtered candidates.")
        return lines
    if tool_name == "resolve_catalog_slug":
        lines = [
            f"- Resolution status: {result.get('resolution_status', 'unknown')}",
        ]
        if result.get("raw_name"):
            lines.append(f"- Raw name: {result['raw_name']}")
        if result.get("resolved_slug"):
            lines.append(
                f"- Resolved slug: `{result['resolved_slug']}` "
                f"({result.get('resolved_name') or 'Unknown'})"
            )
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
            lines.append("- Candidate preview:")
            for candidate in candidates[:8]:
                lines.extend(
                    [
                        f"  {line.removeprefix('- ')}"
                        for line in _format_candidate_tool_view(candidate)
                    ]
                )
        return lines
    if tool_name == "batch_get_entities":
        entities = result.get("entities") or []
        missing_slugs = result.get("missing_slugs") or []
        lines = []
        for entity in entities:
            lines.extend(_format_entity_tool_view(entity))
        if missing_slugs:
            lines.append("- Missing slugs: " + ", ".join(f"`{slug}`" for slug in missing_slugs))
        return lines or ["- No entities returned."]
    payload = (
        result.get("champion")
        or result.get("item")
        or result.get("rune")
        or {}
    )
    return _format_entity_tool_view(payload)


def _format_entity_tool_view(entity: dict[str, Any]) -> list[str]:
    if not entity:
        return ["- No entity returned."]
    lines = [f"- {entity.get('name', 'Unknown')} (`{entity.get('slug', '')}`)"]
    if entity.get("class_text"):
        lines.append(f"  - Class: {entity['class_text']}")
    if entity.get("position_text"):
        lines.append(f"  - Positions: {entity['position_text']}")
    if entity.get("adaptive_type"):
        lines.append(f"  - Adaptive type: {entity['adaptive_type']}")
    if entity.get("range_type"):
        lines.append(f"  - Range: {entity['range_type']}")
    if entity.get("resource"):
        lines.append(f"  - Resource: {entity['resource']}")
    if entity.get("cost"):
        lines.append(f"  - Cost: {entity['cost']}")
    if entity.get("sell"):
        lines.append(f"  - Sell: {entity['sell']}")
    if entity.get("stats"):
        lines.append("  - Stats: " + ", ".join(str(value) for value in entity["stats"][:4]))
    if entity.get("description"):
        lines.append(f"  - Description: {_trim_text(str(entity['description']), 180)}")
    if entity.get("similar_item_names"):
        lines.append(
            "  - Similar items: "
            + ", ".join(str(value) for value in entity["similar_item_names"][:4])
        )
    if entity.get("path"):
        lines.append(f"  - Path: {entity['path']}")
    if entity.get("slot"):
        lines.append(f"  - Slot: {entity['slot']}")
    abilities = entity.get("abilities") or []
    for ability in abilities[:3]:
        lines.append(
            "  - Ability: "
            + " | ".join(
                part
                for part in [
                    str(ability.get("skill") or "?"),
                    str(ability.get("name") or "Unnamed"),
                    str(ability.get("damage_type") or "mixed"),
                    _trim_text(str(ability.get("blurb") or ""), 120),
                ]
                if part
            )
        )
    return lines


def _format_candidate_tool_view(candidate: dict[str, Any]) -> list[str]:
    if not candidate:
        return ["- No candidate returned."]
    lines = [f"- {candidate.get('name', 'Unknown')} (`{candidate.get('slug', '')}`)"]
    aliases = candidate.get("aliases") or []
    if aliases:
        lines.append("  - Aliases: " + ", ".join(str(value) for value in aliases[:4]))
    if candidate.get("class_text"):
        lines.append(f"  - Class: {candidate['class_text']}")
    if candidate.get("position_tags"):
        lines.append(
            "  - Positions: "
            + ", ".join(str(tag) for tag in candidate["position_tags"][:4])
        )
    if candidate.get("path"):
        lines.append(f"  - Path: {candidate['path']}")
    if candidate.get("slot"):
        lines.append(f"  - Slot: {candidate['slot']}")
    if candidate.get("cost"):
        lines.append(f"  - Cost: {candidate['cost']}")
    if candidate.get("main_attributes"):
        lines.append(
            "  - Main attributes: "
            + ", ".join(str(value) for value in candidate["main_attributes"][:4])
        )
    if candidate.get("description"):
        lines.append(f"  - Description: {_trim_text(str(candidate['description']), 160)}")
    if candidate.get("match_score") is not None:
        lines.append(f"  - Match score: {candidate['match_score']}")
    return lines


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
    if isinstance(value, dict) and tool_name in {"list_catalog_candidates", "resolve_catalog_slug"}:
        slugs: set[str] = set()
        resolved_slug = value.get("resolved_slug")
        if isinstance(resolved_slug, str) and resolved_slug.startswith(("lol-", "wr-")):
            slugs.add(resolved_slug)
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
) -> str:
    header = f"{index}. {_entity_label(entity, response_preferences)}"
    body = [
        f"   - Summary: {_champion_summary_line(entity)}",
        "   - Known build slots:",
        *[
            f"     - {line.removeprefix('- ')}"
            for line in _format_build_slots(
                build=build,
                context=MatchContext(
                    game=entity.game,
                    data_version=snapshot.data_version,
                    own_champion_slug=entity.slug,
                ),
                response_preferences=response_preferences,
                snapshot=snapshot,
            )
        ],
        "   - Known runes:",
        *[
            f"     - {line.removeprefix('- ')}"
            for line in _format_rune_lines(
                rune_selection=runes,
                context=MatchContext(
                    game=entity.game,
                    data_version=snapshot.data_version,
                    own_champion_slug=entity.slug,
                ),
                response_preferences=response_preferences,
                snapshot=snapshot,
            )
        ],
    ]
    return "\n".join([header, *body])


def _format_champion(
    *,
    entity: CatalogEntity,
    response_preferences: ResponsePreferences,
) -> str:
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
    slots = list(build[:6]) + [None] * max(0, 6 - len(build))
    lines: list[str] = []
    for slot_index, item_slug in enumerate(slots[:6], start=1):
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
    lines: list[str] = []
    for step_index, item_slug in enumerate(build_order[:7], start=1):
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
    return [
        f"- Primary: {_format_rune_list(primary, context, response_preferences, snapshot)}",
        f"- Secondary: {_format_rune_list(secondary, context, response_preferences, snapshot)}",
    ]


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


def _trim_text(value: str, limit: int) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."
