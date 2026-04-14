from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.api.schemas.catalog import CatalogEntityType
from app.catalog.registry import CatalogEntity, CatalogSnapshot
from app.domain.enums import Game, Language, TerminologyStyle
from app.domain.match_context import normalize_lookup_text
from app.services.catalog_service import CatalogService

MAX_BATCH_SLUGS = 12
MAX_SEARCH_LIMIT = 8


@dataclass
class CatalogToolset:
    catalog_service: CatalogService

    def get_champion(self, snapshot: CatalogSnapshot, slug: str) -> dict[str, Any]:
        entity = snapshot.catalogs[self._game_from_slug(slug)].champions_by_slug.get(slug)
        return {"champion": self._champion_tool_view(entity)}

    def get_item(self, snapshot: CatalogSnapshot, slug: str) -> dict[str, Any]:
        entity = snapshot.catalogs[self._game_from_slug(slug)].items_by_slug.get(slug)
        return {"item": self._item_tool_view(entity)}

    def get_rune(self, snapshot: CatalogSnapshot, slug: str) -> dict[str, Any]:
        entity = snapshot.catalogs[self._game_from_slug(slug)].runes_by_slug.get(slug)
        return {"rune": self._rune_tool_view(entity)}

    def batch_get_entities(
        self,
        snapshot: CatalogSnapshot,
        *,
        entity_type: str,
        slugs: list[str],
    ) -> dict[str, Any]:
        resolved_type = CatalogEntityType(entity_type)
        entities: list[dict[str, Any]] = []
        missing_slugs: list[str] = []
        for slug in slugs[:MAX_BATCH_SLUGS]:
            entity = self._lookup_entity(snapshot=snapshot, slug=slug, entity_type=resolved_type)
            if entity is None:
                missing_slugs.append(slug)
                continue
            tool_view = self._entity_tool_view(entity)
            if tool_view is None:
                missing_slugs.append(slug)
                continue
            entities.append(tool_view)
        return {
            "entity_type": resolved_type.value,
            "entities": entities,
            "missing_slugs": missing_slugs,
        }

    def search_catalog(
        self,
        session: Session,
        *,
        game: Game,
        snapshot: CatalogSnapshot,
        entity_type: str,
        query: str,
        limit: int = 5,
    ) -> dict[str, Any]:
        resolved_type = CatalogEntityType(entity_type)
        bounded_limit = max(1, min(limit, MAX_SEARCH_LIMIT))
        _, results = self.catalog_service.lookup(
            session,
            game=game,
            query=query,
            entity_type=resolved_type,
            data_version=snapshot.data_version,
            language=Language.ZH_CN,
            terminology_style=TerminologyStyle.OFFICIAL,
            limit=bounded_limit,
        )
        matches: list[dict[str, Any]] = []
        for result in results:
            entity = self._lookup_entity(
                snapshot=snapshot,
                slug=result.slug,
                entity_type=resolved_type,
            )
            if entity is None:
                continue
            matches.append(
                self._search_match_view(
                    entity=entity,
                    matched_fields=self._matched_fields(entity=entity, query=query),
                )
            )
        return {"entity_type": resolved_type.value, "matches": matches}

    def _entity_tool_view(self, entity: CatalogEntity | None) -> dict[str, Any] | None:
        if entity is None:
            return None
        if entity.entity_type == CatalogEntityType.CHAMPION.value:
            return self._champion_tool_view(entity)
        if entity.entity_type == CatalogEntityType.ITEM.value:
            return self._item_tool_view(entity)
        return self._rune_tool_view(entity)

    def _champion_tool_view(self, entity: CatalogEntity | None) -> dict[str, Any] | None:
        if entity is None:
            return None
        raw_payload = entity.raw_payload if isinstance(entity.raw_payload, dict) else {}
        infobox = raw_payload.get("infobox", {})
        return {
            "slug": entity.slug,
            "name": entity.english_name,
            "adaptive_type": infobox.get("Adaptive type"),
            "class_text": infobox.get("Class(es)"),
            "position_text": infobox.get("Position(s)"),
            "range_type": infobox.get("Range type") or infobox.get("Attack range"),
            "resource": infobox.get("Resource"),
            "abilities": [
                {
                    "skill": ability.get("skill"),
                    "name": ability.get("name"),
                    "blurb": ability.get("blurb"),
                    "damage_type": ability.get("damage_type"),
                    "affects": ability.get("affects"),
                    "targeting": ability.get("targeting"),
                    "range": ability.get("range"),
                    "effect_radius": ability.get("effect_radius"),
                    "leveling": ability.get("leveling"),
                }
                for ability in (raw_payload.get("abilities") or [])[:5]
            ],
        }

    def _item_tool_view(self, entity: CatalogEntity | None) -> dict[str, Any] | None:
        if entity is None:
            return None
        raw_payload = entity.raw_payload if isinstance(entity.raw_payload, dict) else {}
        attributes = raw_payload.get("attributes") or {}
        return {
            "slug": entity.slug,
            "name": entity.english_name,
            "cost": attributes.get("Cost"),
            "sell": attributes.get("Sell"),
            "stats": raw_payload.get("stats") or [],
            "description": raw_payload.get("description"),
            "similar_item_names": self._similar_item_names(raw_payload.get("similar_items")),
        }

    def _rune_tool_view(self, entity: CatalogEntity | None) -> dict[str, Any] | None:
        if entity is None:
            return None
        raw_payload = entity.raw_payload if isinstance(entity.raw_payload, dict) else {}
        attributes = raw_payload.get("attributes") or {}
        return {
            "slug": entity.slug,
            "name": entity.english_name,
            "path": raw_payload.get("path") or attributes.get("Path"),
            "slot": raw_payload.get("slot") or attributes.get("Slot"),
            "description": raw_payload.get("description"),
        }

    def _search_match_view(
        self,
        *,
        entity: CatalogEntity,
        matched_fields: list[str],
    ) -> dict[str, Any]:
        if entity.entity_type == CatalogEntityType.CHAMPION.value:
            raw_payload = entity.raw_payload if isinstance(entity.raw_payload, dict) else {}
            infobox = raw_payload.get("infobox", {})
            return {
                "slug": entity.slug,
                "name": entity.english_name,
                "class_text": infobox.get("Class(es)"),
                "position_text": infobox.get("Position(s)"),
                "matched_fields": matched_fields,
            }
        if entity.entity_type == CatalogEntityType.ITEM.value:
            raw_payload = entity.raw_payload if isinstance(entity.raw_payload, dict) else {}
            attributes = raw_payload.get("attributes") or {}
            return {
                "slug": entity.slug,
                "name": entity.english_name,
                "cost": attributes.get("Cost"),
                "stats": raw_payload.get("stats") or [],
                "matched_fields": matched_fields,
            }
        raw_payload = entity.raw_payload if isinstance(entity.raw_payload, dict) else {}
        attributes = raw_payload.get("attributes") or {}
        return {
            "slug": entity.slug,
            "name": entity.english_name,
            "path": raw_payload.get("path") or attributes.get("Path"),
            "slot": raw_payload.get("slot") or attributes.get("Slot"),
            "matched_fields": matched_fields,
        }

    def _lookup_entity(
        self,
        *,
        snapshot: CatalogSnapshot,
        slug: str,
        entity_type: CatalogEntityType,
    ) -> CatalogEntity | None:
        game_catalog = snapshot.catalogs[self._game_from_slug(slug)]
        if entity_type == CatalogEntityType.CHAMPION:
            return game_catalog.champions_by_slug.get(slug)
        if entity_type == CatalogEntityType.ITEM:
            return game_catalog.items_by_slug.get(slug)
        return game_catalog.runes_by_slug.get(slug)

    def _matched_fields(self, *, entity: CatalogEntity, query: str) -> list[str]:
        normalized_query = normalize_lookup_text(query)
        if not normalized_query:
            return ["name"]
        query_terms = [term for term in normalized_query.split() if term]
        raw_payload = entity.raw_payload if isinstance(entity.raw_payload, dict) else {}
        name_blob = " ".join(
            [entity.english_name, *entity.display_names.values(), *entity.aliases]
        )
        fields: dict[str, str] = {
            "name": name_blob,
            "stats": " ".join(str(item) for item in raw_payload.get("stats") or []),
            "description": str(raw_payload.get("description") or ""),
            "blurb": " ".join(
                str(ability.get("blurb") or "") for ability in (raw_payload.get("abilities") or [])
            ),
        }
        matched: list[str] = []
        for field_name, field_value in fields.items():
            normalized_value = normalize_lookup_text(field_value)
            if normalized_value and all(term in normalized_value for term in query_terms):
                matched.append(field_name)
        if not matched:
            matched.append("name")
        return matched

    def _similar_item_names(self, payload: Any) -> list[str]:
        if not isinstance(payload, list):
            return []
        names: list[str] = []
        for item in payload:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                name = item.get("name") or item.get("display_name") or item.get("slug")
                if name:
                    names.append(str(name))
        return names[:5]

    def _game_from_slug(self, slug: str) -> Game:
        return Game.LOL if slug.startswith("lol-") else Game.WILD_RIFT
