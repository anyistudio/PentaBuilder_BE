from typing import Any

from app.catalog.registry import CatalogEntity, CatalogSnapshot, GameCatalog
from app.domain.match_context import MatchContext

_OMIT = object()


def build_involved_entity_parameter_appendix(
    *,
    context: MatchContext,
    snapshot: CatalogSnapshot,
) -> dict[str, Any]:
    catalog = snapshot.catalogs[context.game]
    payload = {
        "own_side": {
            "champion": _champion_parameter_payload(
                catalog.champions_by_slug[context.own_champion_slug]
            ),
            "build": _build_parameter_slots(build=context.own_build, catalog=catalog),
            "runes": _rune_parameter_selection(
                rune_selection=context.own_runes.model_dump(mode="json"),
                catalog=catalog,
            ),
        },
        "enemy_team": [
            {
                "champion_slug": enemy.champion_slug,
                "champion": _champion_parameter_payload(
                    catalog.champions_by_slug[enemy.champion_slug]
                ),
                "build": _build_parameter_slots(build=enemy.build, catalog=catalog),
                "runes": _rune_parameter_selection(
                    rune_selection=enemy.runes.model_dump(mode="json"),
                    catalog=catalog,
                ),
            }
            for enemy in context.enemy_team
        ],
    }
    compacted = _compact_payload(payload)
    return compacted if isinstance(compacted, dict) else {}


def _build_parameter_slots(
    *,
    build: list[str | None],
    catalog: GameCatalog,
) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for slot_index, item_slug in enumerate(build):
        if not item_slug:
            continue
        item = catalog.items_by_slug.get(item_slug)
        slot_payload = {
            "slot_index": slot_index,
            "item_slug": item_slug,
            "item": _item_parameter_payload(item) if item is not None else None,
            "missing": item is None,
        }
        compacted = _compact_payload(slot_payload)
        if isinstance(compacted, dict):
            slots.append(compacted)
    return slots


def _rune_parameter_selection(
    *,
    rune_selection: dict[str, Any],
    catalog: GameCatalog,
) -> dict[str, list[dict[str, Any]]]:
    payload = {
        "primary": _rune_parameter_list(
            rune_slugs=list(rune_selection.get("primary") or []),
            catalog=catalog,
        ),
        "secondary": _rune_parameter_list(
            rune_slugs=list(rune_selection.get("secondary") or []),
            catalog=catalog,
        ),
    }
    compacted = _compact_payload(payload)
    return compacted if isinstance(compacted, dict) else {}


def _rune_parameter_list(
    *,
    rune_slugs: list[str],
    catalog: GameCatalog,
) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for rune_slug in rune_slugs:
        entity = catalog.runes_by_slug.get(rune_slug)
        if entity is None:
            payload.append({"slug": rune_slug, "missing": True})
            continue
        payload.append(_rune_parameter_payload(entity))
    return payload


def _champion_parameter_payload(entity: CatalogEntity) -> dict[str, Any]:
    raw_payload = entity.raw_payload if isinstance(entity.raw_payload, dict) else {}
    abilities = []
    for ability in raw_payload.get("abilities") or []:
        compacted_ability = _compact_payload(
            {
                "skill": ability.get("skill"),
                "name": ability.get("name"),
                "affects": ability.get("affects"),
                "description": ability.get("description"),
                "damage_type": ability.get("damage_type"),
                "cooldown": ability.get("cooldown"),
                "cost": ability.get("cost"),
                "targeting": ability.get("targeting"),
                "range": ability.get("range"),
                "effect_radius": ability.get("effect_radius"),
                "speed": ability.get("speed"),
                "width": ability.get("width"),
                "leveling": ability.get("leveling"),
                "parameters": ability.get("parameters") or {},
            }
        )
        if isinstance(compacted_ability, dict):
            abilities.append(compacted_ability)
    compacted = _compact_payload(
        {
            "slug": entity.slug,
            "english_name": entity.english_name,
            "display_names": dict(entity.display_names),
            "aliases": list(entity.aliases),
            "categories": list(raw_payload.get("categories") or []),
            "infobox": dict(raw_payload.get("infobox") or {}),
            "abilities": abilities,
        }
    )
    return compacted if isinstance(compacted, dict) else {"slug": entity.slug}


def _item_parameter_payload(entity: CatalogEntity) -> dict[str, Any]:
    raw_payload = entity.raw_payload if isinstance(entity.raw_payload, dict) else {}
    compacted = _compact_payload(
        {
            "slug": entity.slug,
            "english_name": entity.english_name,
            "display_names": dict(entity.display_names),
            "aliases": list(entity.aliases),
            "categories": list(raw_payload.get("categories") or []),
            "attributes": dict(raw_payload.get("attributes") or {}),
            "stats": list(raw_payload.get("stats") or []),
            "description": raw_payload.get("description"),
            "similar_items": list(raw_payload.get("similar_items") or []),
        }
    )
    return compacted if isinstance(compacted, dict) else {"slug": entity.slug}


def _rune_parameter_payload(entity: CatalogEntity) -> dict[str, Any]:
    raw_payload = entity.raw_payload if isinstance(entity.raw_payload, dict) else {}
    compacted = _compact_payload(
        {
            "slug": entity.slug,
            "english_name": entity.english_name,
            "display_names": dict(entity.display_names),
            "aliases": list(entity.aliases),
            "categories": list(raw_payload.get("categories") or []),
            "path": raw_payload.get("path"),
            "slot": raw_payload.get("slot"),
            "attributes": dict(raw_payload.get("attributes") or {}),
            "description": raw_payload.get("description"),
        }
    )
    return compacted if isinstance(compacted, dict) else {"slug": entity.slug}


def _compact_payload(value: Any) -> Any:
    if value is None:
        return _OMIT
    if isinstance(value, str):
        return value if value.strip() else _OMIT
    if isinstance(value, dict):
        compacted_dict: dict[str, Any] = {}
        for key, item in value.items():
            compacted_item = _compact_payload(item)
            if compacted_item is _OMIT:
                continue
            compacted_dict[key] = compacted_item
        return compacted_dict if compacted_dict else _OMIT
    if isinstance(value, list):
        compacted_list = [
            compacted_item
            for item in value
            if (compacted_item := _compact_payload(item)) is not _OMIT
        ]
        return compacted_list if compacted_list else _OMIT
    return value
