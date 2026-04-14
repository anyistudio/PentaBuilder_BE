import json
from dataclasses import dataclass
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.ai.providers.base import BaseLLMClient, LLMResult
from app.api.schemas.catalog import CatalogEntitySummary, CatalogEntityType
from app.catalog.registry import CatalogEntity, CatalogSnapshot
from app.core.errors import ApiError
from app.domain.enums import Game, Language, TerminologyStyle
from app.domain.match_context import canonicalize_catalog_slug, normalize_lookup_text
from app.services.catalog_service import CatalogService

MAX_BATCH_SLUGS = 12
MAX_SEARCH_LIMIT = 8
MAX_SELECTOR_CANDIDATES = 80
MAX_PROMPT_CANDIDATES = 20

FILTER_KEY_ALIASES = {
    "position": "position",
    "lane": "position",
    "role": "position",
    "class": "class_name",
    "class_name": "class_name",
    "category": "category",
    "subtype": "subtype",
    "path": "path",
    "slot": "slot",
    "keyword": "keywords",
    "keywords": "keywords",
}

FILTER_TOKEN_EXPANSIONS = {
    "top": ("top", "baron lane", "solo lane", "上路"),
    "jungle": ("jungle", "jungler", "打野"),
    "mid": ("mid", "middle", "中路"),
    "adc": ("adc", "dragon lane", "marksman", "射手"),
    "support": ("support", "辅助"),
    "ap": ("ability power", "magic"),
    "ad": ("attack damage", "physical"),
    "ah": ("ability haste",),
    "mr": ("magic resistance",),
    "armor": ("armor",),
    "boots": ("boots", "shoes", "靴"),
    "enchant": ("enchant", "附魔"),
    "mage": ("mage", "ability power", "magic"),
    "tank": ("tank", "health", "armor", "magic resistance"),
    "fighter": ("fighter", "diver", "skirmisher", "juggernaut"),
    "assassin": ("assassin", "burst"),
    "marksman": ("marksman", "attack speed", "critical strike", "physical"),
    "support_item": ("support", "heal", "shield"),
    "keystone": ("keystone", "基石"),
    "domination": ("domination",),
    "precision": ("precision",),
    "resolve": ("resolve",),
    "sorcery": ("sorcery",),
    "inspiration": ("inspiration",),
}

SLUG_SELECTOR_SYSTEM_PROMPT = """Slug resolver selector mode:
- You resolve one canonical catalog slug for League of Legends PC or Wild Rift.
- Read the requested game, entity type, raw name, optional filters, and candidate list literally.
- You may only select a slug that already appears inside the candidate list.
- Never invent, rewrite, or guess a new slug outside the provided candidates.
- Prefer `not_found` over a weak guess when the candidates do not really match the raw name.
- Prefer `ambiguous` when multiple candidates are still plausible after applying the filters.
- Use aliases, official names, common abbreviations, lane filters,
  rune path filters, and item subtype hints.
- If a candidate matches only by game prefix but not by name semantics, reject it.
- Return short user-safe reasoning in `reasoning_summary`. Do not reveal hidden chain-of-thought.
"""


class SlugSelectorDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resolution_status: Literal["selected", "ambiguous", "not_found"]
    selected_slug: str | None = None
    reasoning_summary: str = Field(default="")


@dataclass
class CatalogToolset:
    catalog_service: CatalogService
    selector_llm_client: BaseLLMClient | None = None

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
                    snapshot=snapshot,
                    matched_fields=self._matched_fields(entity=entity, query=query),
                )
            )
        return {"entity_type": resolved_type.value, "matches": matches}

    def list_catalog_candidates(
        self,
        snapshot: CatalogSnapshot,
        *,
        game: Game,
        entity_type: str,
        filters: dict[str, Any] | None,
    ) -> dict[str, Any]:
        resolved_type = CatalogEntityType(entity_type)
        normalized_filters = self._normalize_filters(filters)
        candidates = self._filtered_entities(
            snapshot=snapshot,
            game=game,
            entity_type=resolved_type,
            filters=normalized_filters,
        )
        return {
            "game": game.value,
            "entity_type": resolved_type.value,
            "applied_filters": normalized_filters,
            "candidate_count": len(candidates),
            "candidates": [
                self._candidate_summary_view(entity=entity, snapshot=snapshot)
                for entity in candidates
            ],
        }

    def resolve_catalog_slug(
        self,
        snapshot: CatalogSnapshot,
        *,
        game: Game,
        entity_type: str,
        raw_name: str,
        filters: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        resolved_type = CatalogEntityType(entity_type)
        cleaned_name = " ".join(str(raw_name).split())[:120]
        normalized_filters = self._normalize_filters(filters)
        filtered_entities = self._filtered_entities(
            snapshot=snapshot,
            game=game,
            entity_type=resolved_type,
            filters=normalized_filters,
        )
        candidate_scope = filtered_entities or self._all_entities(
            snapshot=snapshot,
            game=game,
            entity_type=resolved_type,
        )

        exact_match = self._resolve_exact_match(
            snapshot=snapshot,
            game=game,
            entity_type=resolved_type,
            raw_name=cleaned_name,
            candidate_scope=candidate_scope,
        )
        if exact_match is not None:
            return (
                self._resolved_slug_payload(
                    snapshot=snapshot,
                    game=game,
                    entity_type=resolved_type,
                    raw_name=cleaned_name,
                    filters=normalized_filters,
                    entity=exact_match,
                    resolved_by="exact_match",
                    confidence="high",
                    candidates=[exact_match],
                    selector_summary=None,
                ),
                [],
            )

        ranked_candidates = self._rank_entities(raw_name=cleaned_name, entities=candidate_scope)
        auto_selected = self._select_top_ranked_candidate(ranked_candidates)
        if auto_selected is not None:
            return (
                self._resolved_slug_payload(
                    snapshot=snapshot,
                    game=game,
                    entity_type=resolved_type,
                    raw_name=cleaned_name,
                    filters=normalized_filters,
                    entity=auto_selected,
                    resolved_by="deterministic_rank",
                    confidence="medium",
                    candidates=[
                        auto_selected,
                        *(entity for _, entity in ranked_candidates[1:4]),
                    ],
                    selector_summary=None,
                ),
                [],
            )

        selector_pool = self._selector_candidate_pool(
            filtered_entities=filtered_entities,
            ranked_candidates=ranked_candidates,
        )
        selector_usage: list[dict[str, Any]] = []
        selector_summary: str | None = None
        if self.selector_llm_client is not None and selector_pool:
            selector_decision, usage_payload = self._select_candidate_with_llm(
                snapshot=snapshot,
                game=game,
                entity_type=resolved_type,
                raw_name=cleaned_name,
                filters=normalized_filters,
                candidates=selector_pool,
            )
            if usage_payload is not None:
                selector_usage.append(usage_payload)
            selector_summary = selector_decision.reasoning_summary or None
            if (
                selector_decision.resolution_status == "selected"
                and isinstance(selector_decision.selected_slug, str)
            ):
                selected_entity = next(
                    (
                        entity
                        for entity in selector_pool
                        if entity.slug == selector_decision.selected_slug
                    ),
                    None,
                )
                if selected_entity is not None:
                    return (
                        self._resolved_slug_payload(
                            snapshot=snapshot,
                            game=game,
                            entity_type=resolved_type,
                            raw_name=cleaned_name,
                            filters=normalized_filters,
                            entity=selected_entity,
                            resolved_by="selector_model",
                            confidence="medium",
                            candidates=selector_pool,
                            selector_summary=selector_summary,
                        ),
                        selector_usage,
                    )
            status = (
                "ambiguous"
                if selector_decision.resolution_status == "ambiguous"
                else "not_found"
            )
        else:
            status = "ambiguous" if selector_pool else "not_found"

        candidate_preview = selector_pool or [
            entity for _, entity in ranked_candidates[:MAX_PROMPT_CANDIDATES]
        ]
        return (
            {
                "game": game.value,
                "entity_type": resolved_type.value,
                "raw_name": cleaned_name,
                "applied_filters": normalized_filters,
                "resolution_status": status,
                "resolved_slug": None,
                "resolved_name": None,
                "resolved_by": None,
                "confidence": "low",
                "selector_summary": selector_summary,
                "candidate_count": len(candidate_preview),
                "candidates": [
                    self._candidate_summary_view(entity=entity, snapshot=snapshot)
                    for entity in candidate_preview
                ],
            },
            selector_usage,
        )

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
        summary = self._entity_summary(entity, data_version="")
        return {
            "slug": entity.slug,
            "name": entity.english_name,
            "aliases": summary.aliases[:4],
            "adaptive_type": infobox.get("Adaptive type"),
            "class_text": infobox.get("Class(es)") or summary.class_text,
            "position_text": infobox.get("Position(s)"),
            "position_tags": summary.position_tags,
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
        summary = self._entity_summary(entity, data_version="")
        return {
            "slug": entity.slug,
            "name": entity.english_name,
            "aliases": summary.aliases[:4],
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
        summary = self._entity_summary(entity, data_version="")
        return {
            "slug": entity.slug,
            "name": entity.english_name,
            "aliases": summary.aliases[:4],
            "path": raw_payload.get("path") or attributes.get("Path"),
            "slot": raw_payload.get("slot") or attributes.get("Slot"),
            "description": raw_payload.get("description"),
        }

    def _search_match_view(
        self,
        *,
        entity: CatalogEntity,
        snapshot: CatalogSnapshot,
        matched_fields: list[str],
    ) -> dict[str, Any]:
        summary = self._entity_summary(entity, data_version=snapshot.data_version)
        if entity.entity_type == CatalogEntityType.CHAMPION.value:
            return {
                "slug": entity.slug,
                "name": entity.english_name,
                "aliases": summary.aliases[:4],
                "class_text": summary.class_text,
                "position_tags": summary.position_tags,
                "matched_fields": matched_fields,
            }
        if entity.entity_type == CatalogEntityType.ITEM.value:
            return {
                "slug": entity.slug,
                "name": entity.english_name,
                "aliases": summary.aliases[:4],
                "cost": summary.cost,
                "stats": summary.stats,
                "matched_fields": matched_fields,
            }
        raw_payload = entity.raw_payload if isinstance(entity.raw_payload, dict) else {}
        attributes = raw_payload.get("attributes") or {}
        return {
            "slug": entity.slug,
            "name": entity.english_name,
            "aliases": summary.aliases[:4],
            "path": raw_payload.get("path") or attributes.get("Path"),
            "slot": raw_payload.get("slot") or attributes.get("Slot"),
            "matched_fields": matched_fields,
        }

    def _candidate_summary_view(
        self,
        *,
        entity: CatalogEntity,
        snapshot: CatalogSnapshot,
        match_score: int | None = None,
    ) -> dict[str, Any]:
        summary = self._entity_summary(entity, data_version=snapshot.data_version)
        payload: dict[str, Any] = {
            "slug": entity.slug,
            "name": summary.name,
            "aliases": summary.aliases[:4],
        }
        if summary.class_text:
            payload["class_text"] = summary.class_text
        if summary.position_tags:
            payload["position_tags"] = summary.position_tags
        if summary.cost:
            payload["cost"] = summary.cost
        if summary.main_attributes:
            payload["main_attributes"] = summary.main_attributes[:4]
        if summary.description:
            payload["description"] = str(summary.description)[:180]
        raw_payload = entity.raw_payload if isinstance(entity.raw_payload, dict) else {}
        if entity.entity_type == CatalogEntityType.RUNE.value:
            attributes = raw_payload.get("attributes") or {}
            payload["path"] = raw_payload.get("path") or attributes.get("Path")
            payload["slot"] = raw_payload.get("slot") or attributes.get("Slot")
        if match_score is not None and match_score > 0:
            payload["match_score"] = match_score
        return payload

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

    def _filtered_entities(
        self,
        *,
        snapshot: CatalogSnapshot,
        game: Game,
        entity_type: CatalogEntityType,
        filters: dict[str, Any],
    ) -> list[CatalogEntity]:
        entities = self._all_entities(snapshot=snapshot, game=game, entity_type=entity_type)
        if not filters:
            return entities
        filtered: list[CatalogEntity] = []
        for entity in entities:
            summary = self._entity_summary(entity, data_version=snapshot.data_version)
            if self._candidate_matches_filters(entity=entity, summary=summary, filters=filters):
                filtered.append(entity)
        return filtered

    def _all_entities(
        self,
        *,
        snapshot: CatalogSnapshot,
        game: Game,
        entity_type: CatalogEntityType,
    ) -> list[CatalogEntity]:
        entities = snapshot.catalogs[game].get_entities(entity_type.value)
        return sorted(entities, key=lambda item: (item.english_name.lower(), item.slug))

    def _entity_summary(self, entity: CatalogEntity, *, data_version: str) -> CatalogEntitySummary:
        return self.catalog_service.summarize_entity(
            entity,
            data_version=data_version,
            language=Language.ZH_CN,
            terminology_style=TerminologyStyle.OFFICIAL,
        )

    def _candidate_matches_filters(
        self,
        *,
        entity: CatalogEntity,
        summary: CatalogEntitySummary,
        filters: dict[str, Any],
    ) -> bool:
        blob = self._candidate_blob(entity=entity, summary=summary)
        raw_payload = entity.raw_payload if isinstance(entity.raw_payload, dict) else {}
        attributes = raw_payload.get("attributes") or {}
        path_text = normalize_lookup_text(
            str(raw_payload.get("path") or attributes.get("Path") or "")
        )
        slot_text = normalize_lookup_text(
            str(raw_payload.get("slot") or attributes.get("Slot") or "")
        )

        if not self._matches_filter_values(
            values=filters.get("position"),
            matcher=lambda value: value in {tag.lower() for tag in summary.position_tags},
            fallback_blob=blob,
        ):
            return False
        if not self._matches_filter_values(
            values=filters.get("class_name"),
            matcher=lambda value: value in normalize_lookup_text(summary.class_text or ""),
            fallback_blob=blob,
        ):
            return False
        if not self._matches_filter_values(
            values=filters.get("path"),
            matcher=lambda value: value == path_text,
            fallback_blob=blob,
        ):
            return False
        if not self._matches_filter_values(
            values=filters.get("slot"),
            matcher=lambda value: value == slot_text,
            fallback_blob=blob,
        ):
            return False
        if not self._matches_filter_values(
            values=filters.get("category"),
            matcher=lambda value: self._text_matches_term(blob, value),
            fallback_blob=blob,
        ):
            return False
        if not self._matches_filter_values(
            values=filters.get("subtype"),
            matcher=lambda value: self._text_matches_term(blob, value),
            fallback_blob=blob,
        ):
            return False
        if not self._matches_filter_values(
            values=filters.get("keywords"),
            matcher=lambda value: self._text_matches_term(blob, value),
            fallback_blob=blob,
        ):
            return False
        return True

    def _matches_filter_values(
        self,
        *,
        values: str | list[str] | None,
        matcher: Callable[[str], bool],
        fallback_blob: str,
    ) -> bool:
        if values is None:
            return True
        normalized_values = [values] if isinstance(values, str) else list(values)
        for value in normalized_values:
            normalized_value = normalize_lookup_text(value)
            if not normalized_value:
                continue
            if matcher(normalized_value):
                continue
            if self._text_matches_term(fallback_blob, normalized_value):
                continue
            return False
        return True

    def _candidate_blob(self, *, entity: CatalogEntity, summary: CatalogEntitySummary) -> str:
        raw_payload = entity.raw_payload if isinstance(entity.raw_payload, dict) else {}
        parts: list[str] = [
            entity.slug,
            entity.source_slug,
            entity.english_name,
            summary.name,
            *summary.aliases,
            *summary.position_tags,
            summary.class_text or "",
            summary.range_type or "",
            summary.resource or "",
            summary.cost or "",
            summary.description or "",
            *summary.stats,
            *summary.main_attributes,
            *(raw_payload.get("categories") or []),
            raw_payload.get("path") or "",
            raw_payload.get("slot") or "",
        ]
        return normalize_lookup_text(" ".join(part for part in parts if part))

    def _text_matches_term(self, blob: str, term: str) -> bool:
        normalized_term = normalize_lookup_text(term)
        if not normalized_term:
            return True
        if normalized_term in blob:
            return True
        expansions = FILTER_TOKEN_EXPANSIONS.get(normalized_term, ())
        return any(normalize_lookup_text(expansion) in blob for expansion in expansions)

    def _normalize_filters(self, filters: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(filters, dict):
            return {}
        normalized: dict[str, Any] = {}
        for raw_key, raw_value in filters.items():
            canonical_key = FILTER_KEY_ALIASES.get(str(raw_key).strip().lower())
            if canonical_key is None:
                continue
            cleaned = self._clean_filter_value(raw_value)
            if cleaned in (None, [], ""):
                continue
            normalized[canonical_key] = cleaned
        return normalized

    def _clean_filter_value(self, value: Any) -> str | list[str] | None:
        if isinstance(value, str):
            cleaned = " ".join(value.split())[:60]
            return cleaned or None
        if isinstance(value, list):
            cleaned_items = [
                " ".join(str(item).split())[:60]
                for item in value[:8]
                if isinstance(item, str) and item.strip()
            ]
            return cleaned_items or None
        return None

    def _resolve_exact_match(
        self,
        *,
        snapshot: CatalogSnapshot,
        game: Game,
        entity_type: CatalogEntityType,
        raw_name: str,
        candidate_scope: list[CatalogEntity],
    ) -> CatalogEntity | None:
        if not raw_name:
            return None
        try:
            canonical_slug = canonicalize_catalog_slug(game, raw_name)
        except ValueError:
            canonical_slug = None
        if canonical_slug is not None:
            exact_entity = self._lookup_entity(
                snapshot=snapshot,
                slug=canonical_slug,
                entity_type=entity_type,
            )
            if exact_entity is not None and any(
                item.slug == exact_entity.slug for item in candidate_scope
            ):
                return exact_entity

        normalized_raw = normalize_lookup_text(raw_name)
        exact_hits = [
            entity
            for entity in candidate_scope
            if normalized_raw in self._normalized_name_terms(entity)
        ]
        if len(exact_hits) == 1:
            return exact_hits[0]
        return None

    def _normalized_name_terms(self, entity: CatalogEntity) -> set[str]:
        terms = {
            normalize_lookup_text(entity.slug),
            normalize_lookup_text(entity.source_slug),
            normalize_lookup_text(entity.english_name),
            *(normalize_lookup_text(value) for value in entity.display_names.values()),
            *(normalize_lookup_text(alias) for alias in entity.aliases),
        }
        return {term for term in terms if term}

    def _rank_entities(
        self,
        *,
        raw_name: str,
        entities: list[CatalogEntity],
    ) -> list[tuple[int, CatalogEntity]]:
        ranked = [
            (self.catalog_service.score_entity_match(query=raw_name, entity=entity), entity)
            for entity in entities
        ]
        ordered = sorted(
            ranked,
            key=lambda item: (-item[0], item[1].english_name.lower(), item[1].slug),
        )
        if normalize_lookup_text(raw_name):
            return [item for item in ordered if item[0] > 0]
        return ordered

    def _select_top_ranked_candidate(
        self,
        ranked_candidates: list[tuple[int, CatalogEntity]],
    ) -> CatalogEntity | None:
        if not ranked_candidates:
            return None
        top_score, top_entity = ranked_candidates[0]
        next_score = ranked_candidates[1][0] if len(ranked_candidates) > 1 else -1
        if top_score >= 260 and top_score > next_score:
            return top_entity
        if top_score >= 180 and top_score >= next_score + 60:
            return top_entity
        if len(ranked_candidates) == 1 and top_score >= 120:
            return top_entity
        return None

    def _selector_candidate_pool(
        self,
        *,
        filtered_entities: list[CatalogEntity],
        ranked_candidates: list[tuple[int, CatalogEntity]],
    ) -> list[CatalogEntity]:
        if filtered_entities:
            return filtered_entities[:MAX_SELECTOR_CANDIDATES]
        return [entity for _, entity in ranked_candidates[:MAX_SELECTOR_CANDIDATES]]

    def _resolved_slug_payload(
        self,
        *,
        snapshot: CatalogSnapshot,
        game: Game,
        entity_type: CatalogEntityType,
        raw_name: str,
        filters: dict[str, Any],
        entity: CatalogEntity,
        resolved_by: str,
        confidence: str,
        candidates: list[CatalogEntity],
        selector_summary: str | None,
    ) -> dict[str, Any]:
        summary = self._candidate_summary_view(entity=entity, snapshot=snapshot)
        return {
            "game": game.value,
            "entity_type": entity_type.value,
            "raw_name": raw_name,
            "applied_filters": filters,
            "resolution_status": "resolved",
            "resolved_slug": entity.slug,
            "resolved_name": summary.get("name"),
            "resolved_by": resolved_by,
            "confidence": confidence,
            "selector_summary": selector_summary,
            "candidate_count": len(candidates),
            "candidates": [
                self._candidate_summary_view(entity=item, snapshot=snapshot)
                for item in candidates[:MAX_PROMPT_CANDIDATES]
            ],
        }

    def _select_candidate_with_llm(
        self,
        *,
        snapshot: CatalogSnapshot,
        game: Game,
        entity_type: CatalogEntityType,
        raw_name: str,
        filters: dict[str, Any],
        candidates: list[CatalogEntity],
    ) -> tuple[SlugSelectorDecision, dict[str, Any] | None]:
        if self.selector_llm_client is None:
            return SlugSelectorDecision(resolution_status="not_found"), None

        candidate_views = [
            self._candidate_summary_view(entity=entity, snapshot=snapshot)
            for entity in candidates[:MAX_SELECTOR_CANDIDATES]
        ]
        filter_lines = self._format_filter_lines(filters)
        prompt_lines = [
            "## Resolver Request",
            f"- Game: {game.value}",
            f"- Entity type: {entity_type.value}",
            f"- Raw name: {raw_name or 'none'}",
            "- Filters:",
            *(filter_lines or ["  - none"]),
            "## Candidate Pool",
        ]
        for index, candidate in enumerate(candidate_views, start=1):
            parts = [
                f"{index}. {candidate.get('name', 'Unknown')} (`{candidate.get('slug', '')}`)",
            ]
            aliases = candidate.get("aliases") or []
            if aliases:
                parts.append("aliases=" + ", ".join(str(alias) for alias in aliases[:4]))
            if candidate.get("position_tags"):
                parts.append(
                    "positions=" + ", ".join(str(tag) for tag in candidate["position_tags"][:4])
                )
            if candidate.get("class_text"):
                parts.append(f"class={candidate['class_text']}")
            if candidate.get("path"):
                parts.append(f"path={candidate['path']}")
            if candidate.get("slot"):
                parts.append(f"slot={candidate['slot']}")
            if candidate.get("main_attributes"):
                parts.append(
                    "attrs=" + ", ".join(str(value) for value in candidate["main_attributes"][:3])
                )
            prompt_lines.append("- " + " | ".join(parts))
        llm_result = self.selector_llm_client.generate_text(
            prompt="\n".join(prompt_lines),
            system_prompt=SLUG_SELECTOR_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema={
                "type": "object",
                "properties": {
                    "resolution_status": {
                        "type": "string",
                        "enum": ["selected", "ambiguous", "not_found"],
                    },
                    "selected_slug": {"type": ["string", "null"]},
                    "reasoning_summary": {"type": "string"},
                },
                "required": ["resolution_status", "selected_slug", "reasoning_summary"],
                "additionalProperties": False,
            },
            temperature=0.0,
        )
        decision = self._parse_selector_decision(llm_result)
        if (
            decision.selected_slug is not None
            and decision.selected_slug not in {candidate.slug for candidate in candidates}
        ):
            decision = SlugSelectorDecision(
                resolution_status="ambiguous",
                selected_slug=None,
                reasoning_summary="Selector returned a slug outside the provided candidate pool.",
            )
        return decision, self._usage_payload(llm_result)

    def _parse_selector_decision(self, llm_result: LLMResult) -> SlugSelectorDecision:
        try:
            payload = json.loads(llm_result.text)
        except json.JSONDecodeError as exc:
            raise ApiError(
                "Model returned an invalid slug resolution decision.",
                code="provider_error",
                status_code=502,
            ) from exc
        try:
            return SlugSelectorDecision.model_validate(payload)
        except ValidationError as exc:
            raise ApiError(
                "Model returned an invalid slug resolution decision.",
                code="provider_error",
                status_code=502,
                details={"issues": exc.errors()},
            ) from exc

    def _format_filter_lines(self, filters: dict[str, Any]) -> list[str]:
        lines: list[str] = []
        for key, value in filters.items():
            if isinstance(value, list):
                lines.append(f"  - {key}: {', '.join(value)}")
            else:
                lines.append(f"  - {key}: {value}")
        return lines

    def _usage_payload(self, llm_result: LLMResult) -> dict[str, Any]:
        return {
            "provider_name": llm_result.provider_name,
            "model_name": llm_result.model_name,
            "tokens_input": llm_result.usage.input_tokens,
            "tokens_output": llm_result.usage.output_tokens,
            "latency_ms": llm_result.usage.latency_ms,
            "cost_usd": llm_result.usage.cost_usd,
        }

    def _game_from_slug(self, slug: str) -> Game:
        return Game.LOL if slug.startswith("lol-") else Game.WILD_RIFT
