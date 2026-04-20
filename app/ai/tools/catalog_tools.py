import json
from dataclasses import dataclass
from typing import Any, Callable, Literal

from fuzzywuzzy import fuzz
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.ai.providers.base import BaseLLMClient, LLMResult
from app.api.schemas.catalog import CatalogEntitySummary, CatalogEntityType
from app.catalog.registry import CatalogEntity, CatalogSnapshot
from app.core.errors import ApiError
from app.core.llm_debug import llm_debug_scope
from app.domain.enums import Game, Language, TerminologyStyle
from app.domain.match_context import canonicalize_catalog_slug, normalize_lookup_text
from app.services.catalog_service import CatalogService

MAX_BATCH_SLUGS = 12
MAX_SEARCH_LIMIT = 8
MAX_SELECTOR_CANDIDATES = 20
MAX_PROMPT_CANDIDATES = 20
MAX_FUZZY_CANDIDATE_PREVIEW = 12

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
    "magic": ("magic", "ability power", "ap", "法术", "法强", "魔法"),
    "ad": ("attack damage", "physical"),
    "physical": ("physical", "attack damage", "ad", "物理"),
    "ah": ("ability haste",),
    "mr": ("magic resistance",),
    "armor": ("armor",),
    "boots": ("boots", "shoes", "shoe", "靴", "鞋", "鞋子"),
    "shoe": ("boots", "shoes", "shoe", "靴", "鞋", "鞋子"),
    "shoes": ("boots", "shoes", "shoe", "靴", "鞋", "鞋子"),
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


@dataclass(frozen=True)
class RankedCatalogEntity:
    entity: CatalogEntity
    score: int
    lexical_score: int
    fuzzy_score: int
    fuzzy_breakdown: dict[str, int]
    matched_term: str


def best_catalog_entity_fuzzy_match(
    *,
    raw_name: str,
    entities: list[CatalogEntity],
) -> RankedCatalogEntity | None:
    ranked = rank_catalog_entities(
        raw_name=raw_name,
        entities=entities,
        lexical_scorer=None,
    )
    return ranked[0] if ranked else None


def rank_catalog_entities(
    *,
    raw_name: str,
    entities: list[CatalogEntity],
    lexical_scorer: Callable[[CatalogEntity], int] | None,
) -> list[RankedCatalogEntity]:
    ranked: list[RankedCatalogEntity] = []
    for entity in entities:
        lexical_score = lexical_scorer(entity) if lexical_scorer is not None else 0
        fuzzy_score, fuzzy_breakdown, matched_term = _best_fuzzy_match(
            raw_name=raw_name,
            entity=entity,
        )
        combined_score = max(lexical_score, 0) + fuzzy_score
        ranked.append(
            RankedCatalogEntity(
                entity=entity,
                score=combined_score,
                lexical_score=lexical_score,
                fuzzy_score=fuzzy_score,
                fuzzy_breakdown=fuzzy_breakdown,
                matched_term=matched_term,
            )
        )
    ordered = sorted(
        ranked,
        key=lambda item: (
            -item.score,
            -item.lexical_score,
            -item.fuzzy_score,
            item.entity.english_name.lower(),
            item.entity.slug,
        ),
    )
    if normalize_lookup_text(raw_name):
        return [
            item
            for item in ordered
            if item.lexical_score > 0 or item.fuzzy_score >= 55
        ]
    return ordered


def _best_fuzzy_match(
    *,
    raw_name: str,
    entity: CatalogEntity,
) -> tuple[int, dict[str, int], str]:
    query_variants = {
        _collapsed_lookup_text(raw_name),
        normalize_lookup_text(raw_name),
    }
    query_variants = {variant for variant in query_variants if variant}
    best_score = 0
    best_breakdown = {
        "ratio": 0,
        "partial_ratio": 0,
        "token_sort_ratio": 0,
        "token_set_ratio": 0,
        "wratio": 0,
    }
    best_term = ""
    for term in entity.search_terms:
        candidate_variants = {
            _collapsed_lookup_text(term),
            normalize_lookup_text(term),
        }
        candidate_variants = {variant for variant in candidate_variants if variant}
        term_best_breakdown = {
            "ratio": 0,
            "partial_ratio": 0,
            "token_sort_ratio": 0,
            "token_set_ratio": 0,
            "wratio": 0,
        }
        for query_variant in query_variants:
            for candidate_variant in candidate_variants:
                term_best_breakdown["ratio"] = max(
                    term_best_breakdown["ratio"],
                    fuzz.ratio(query_variant, candidate_variant),
                )
                term_best_breakdown["partial_ratio"] = max(
                    term_best_breakdown["partial_ratio"],
                    fuzz.partial_ratio(query_variant, candidate_variant),
                )
                term_best_breakdown["token_sort_ratio"] = max(
                    term_best_breakdown["token_sort_ratio"],
                    fuzz.token_sort_ratio(query_variant, candidate_variant),
                )
                term_best_breakdown["token_set_ratio"] = max(
                    term_best_breakdown["token_set_ratio"],
                    fuzz.token_set_ratio(query_variant, candidate_variant),
                )
                term_best_breakdown["wratio"] = max(
                    term_best_breakdown["wratio"],
                    fuzz.WRatio(query_variant, candidate_variant),
                )
        composite_score = round(
            term_best_breakdown["wratio"] * 0.30
            + term_best_breakdown["token_set_ratio"] * 0.25
            + term_best_breakdown["token_sort_ratio"] * 0.20
            + term_best_breakdown["partial_ratio"] * 0.15
            + term_best_breakdown["ratio"] * 0.10
        )
        if composite_score > best_score:
            best_score = composite_score
            best_breakdown = term_best_breakdown
            best_term = term
    return best_score, best_breakdown, best_term


def _collapsed_lookup_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


@dataclass
class CatalogToolset:
    catalog_service: CatalogService
    selector_llm_client: BaseLLMClient | None = None

    def resolve_catalog_slug_with_selector(
        self,
        snapshot: CatalogSnapshot,
        *,
        game: Game,
        entity_type: str,
        raw_name: str,
        filters: dict[str, Any] | None,
    ) -> tuple[str | None, list[dict[str, Any]]]:
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
            return exact_match.slug, []

        ranked_candidates = self._rank_entities(raw_name=cleaned_name, entities=candidate_scope)
        selector_pool = self._selector_candidate_pool(
            raw_name=cleaned_name,
            filtered_entities=filtered_entities,
            ranked_candidates=ranked_candidates,
        )
        if self.selector_llm_client is not None and selector_pool:
            selector_decision, usage_payload = self._select_candidate_with_llm(
                snapshot=snapshot,
                game=game,
                entity_type=resolved_type,
                raw_name=cleaned_name,
                filters=normalized_filters,
                candidates=selector_pool,
            )
            if (
                selector_decision.resolution_status == "selected"
                and isinstance(selector_decision.selected_slug, str)
            ):
                return selector_decision.selected_slug, (
                    [usage_payload] if usage_payload is not None else []
                )
            return None, ([usage_payload] if usage_payload is not None else [])

        fallback = self._select_top_ranked_candidate(ranked_candidates)
        if fallback is not None:
            return fallback.entity.slug, []
        if ranked_candidates:
            return ranked_candidates[0].entity.slug, []
        return None, []

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
        del session
        resolved_type = CatalogEntityType(entity_type)
        bounded_limit = max(1, min(limit, MAX_SEARCH_LIMIT))
        ranked_matches = self._rank_entities(
            raw_name=query,
            entities=self._all_entities(
                snapshot=snapshot,
                game=game,
                entity_type=resolved_type,
            ),
        )
        matches = [
            self._search_match_view(
                entity=ranking.entity,
                snapshot=snapshot,
                matched_fields=self._matched_fields(entity=ranking.entity, query=query),
                ranking=ranking,
            )
            for ranking in ranked_matches[:bounded_limit]
        ]
        top_match = (
            self._detailed_ranked_entity_view(ranking=ranked_matches[0])
            if ranked_matches
            else None
        )
        return {
            "game": game.value,
            "entity_type": resolved_type.value,
            "query": query,
            "ranking_method": "fuzzywuzzy_blend",
            "match_count": len(ranked_matches),
            "top_match": top_match,
            "matches": matches,
        }

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

    def list_item_ids(
        self,
        snapshot: CatalogSnapshot,
        *,
        game: Game,
        category: str | list[str] | None,
    ) -> dict[str, Any]:
        normalized_categories = self._normalize_item_categories(category)
        if not normalized_categories:
            items = self._filtered_entities(
                snapshot=snapshot,
                game=game,
                entity_type=CatalogEntityType.ITEM,
                filters={},
            )
        elif len(normalized_categories) == 1:
            items = self._filtered_entities(
                snapshot=snapshot,
                game=game,
                entity_type=CatalogEntityType.ITEM,
                filters={"category": normalized_categories[0]},
            )
        else:
            deduped_items: dict[str, CatalogEntity] = {}
            for normalized_category in normalized_categories:
                category_items = self._filtered_entities(
                    snapshot=snapshot,
                    game=game,
                    entity_type=CatalogEntityType.ITEM,
                    filters={"category": normalized_category},
                )
                for entity in category_items:
                    deduped_items.setdefault(entity.slug, entity)
            items = sorted(
                deduped_items.values(),
                key=lambda entity: (entity.english_name.lower(), entity.slug),
            )
        return {
            "game": game.value,
            "entity_type": CatalogEntityType.ITEM.value,
            "requested_categories": normalized_categories or ["all"],
            "item_count": len(items),
            "items": [
                self._candidate_summary_view(entity=entity, snapshot=snapshot)
                for entity in items
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
                    selected_ranking=None,
                    selector_summary=None,
                ),
                [],
            )

        ranked_candidates = self._rank_entities(raw_name=cleaned_name, entities=candidate_scope)
        auto_selected = self._select_top_ranked_candidate(ranked_candidates)
        if auto_selected is not None:
            candidate_preview: list[RankedCatalogEntity | CatalogEntity] = [
                auto_selected,
                *ranked_candidates[1:4],
            ]
            return (
                self._resolved_slug_payload(
                    snapshot=snapshot,
                    game=game,
                    entity_type=resolved_type,
                    raw_name=cleaned_name,
                    filters=normalized_filters,
                    entity=auto_selected.entity,
                    resolved_by="deterministic_rank",
                    confidence="medium",
                    candidates=candidate_preview,
                    selected_ranking=auto_selected,
                    selector_summary=None,
                ),
                [],
            )

        selector_pool = self._selector_candidate_pool(
            raw_name=cleaned_name,
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
                            selected_ranking=next(
                                (
                                    ranking
                                    for ranking in ranked_candidates
                                    if ranking.entity.slug == selected_entity.slug
                                ),
                                None,
                            ),
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
            ranking for ranking in ranked_candidates[:MAX_PROMPT_CANDIDATES]
        ]
        return (
            {
                "game": game.value,
                "entity_type": resolved_type.value,
                "raw_name": cleaned_name,
                "applied_filters": normalized_filters,
                "resolution_status": status,
                "resolved_slug": None,
                "resolved_id": None,
                "resolved_name": None,
                "resolved_entity": None,
                "resolved_by": None,
                "confidence": "low",
                "selector_summary": selector_summary,
                "candidate_count": len(candidate_preview),
                "candidates": self._candidate_payloads(
                    snapshot=snapshot,
                    candidates=candidate_preview,
                ),
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
            "id": entity.slug,
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
            "id": entity.slug,
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
            "id": entity.slug,
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
        ranking: RankedCatalogEntity | None = None,
    ) -> dict[str, Any]:
        summary = self._entity_summary(entity, data_version=snapshot.data_version)
        if entity.entity_type == CatalogEntityType.CHAMPION.value:
            payload = {
                "id": entity.slug,
                "slug": entity.slug,
                "name": entity.english_name,
                "aliases": summary.aliases[:4],
                "class_text": summary.class_text,
                "position_tags": summary.position_tags,
                "matched_fields": matched_fields,
            }
            return self._attach_ranking(payload=payload, ranking=ranking)
        if entity.entity_type == CatalogEntityType.ITEM.value:
            payload = {
                "id": entity.slug,
                "slug": entity.slug,
                "name": entity.english_name,
                "aliases": summary.aliases[:4],
                "cost": summary.cost,
                "stats": summary.stats,
                "matched_fields": matched_fields,
            }
            return self._attach_ranking(payload=payload, ranking=ranking)
        raw_payload = entity.raw_payload if isinstance(entity.raw_payload, dict) else {}
        attributes = raw_payload.get("attributes") or {}
        payload = {
            "id": entity.slug,
            "slug": entity.slug,
            "name": entity.english_name,
            "aliases": summary.aliases[:4],
            "path": raw_payload.get("path") or attributes.get("Path"),
            "slot": raw_payload.get("slot") or attributes.get("Slot"),
            "matched_fields": matched_fields,
        }
        return self._attach_ranking(payload=payload, ranking=ranking)

    def _candidate_summary_view(
        self,
        *,
        entity: CatalogEntity,
        snapshot: CatalogSnapshot,
        ranking: RankedCatalogEntity | None = None,
    ) -> dict[str, Any]:
        summary = self._entity_summary(entity, data_version=snapshot.data_version)
        payload: dict[str, Any] = {
            "id": entity.slug,
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
        return self._attach_ranking(payload=payload, ranking=ranking)

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
    ) -> list[RankedCatalogEntity]:
        return rank_catalog_entities(
            raw_name=raw_name,
            entities=entities,
            lexical_scorer=lambda entity: self.catalog_service.score_entity_match(
                query=raw_name,
                entity=entity,
            ),
        )

    def _select_top_ranked_candidate(
        self,
        ranked_candidates: list[RankedCatalogEntity],
    ) -> RankedCatalogEntity | None:
        if not ranked_candidates:
            return None
        top_candidate = ranked_candidates[0]
        next_candidate = ranked_candidates[1] if len(ranked_candidates) > 1 else None
        next_score = next_candidate.score if next_candidate is not None else -1
        next_fuzzy_score = next_candidate.fuzzy_score if next_candidate is not None else -1
        if top_candidate.lexical_score >= 260 and top_candidate.score > next_score:
            return top_candidate
        if top_candidate.fuzzy_score >= 95 and top_candidate.fuzzy_score >= next_fuzzy_score + 10:
            return top_candidate
        if top_candidate.score >= 220 and top_candidate.score >= next_score + 40:
            return top_candidate
        if len(ranked_candidates) == 1 and top_candidate.fuzzy_score >= 90:
            return top_candidate
        return None

    def _selector_candidate_pool(
        self,
        *,
        raw_name: str,
        filtered_entities: list[CatalogEntity],
        ranked_candidates: list[RankedCatalogEntity],
    ) -> list[CatalogEntity]:
        seen: set[str] = set()
        candidates: list[CatalogEntity] = []
        candidate_scope = filtered_entities or [ranking.entity for ranking in ranked_candidates]
        normalized_raw = normalize_lookup_text(raw_name)

        def add(entity: CatalogEntity) -> None:
            if entity.slug in seen or len(candidates) >= MAX_SELECTOR_CANDIDATES:
                return
            seen.add(entity.slug)
            candidates.append(entity)

        if normalized_raw:
            for entity in candidate_scope:
                normalized_terms = self._normalized_name_terms(entity)
                if normalized_raw in normalized_terms:
                    add(entity)
            for entity in candidate_scope:
                if any(self._terms_overlap(normalized_raw, term) for term in entity.search_terms):
                    add(entity)
        for ranking in ranked_candidates[:MAX_SELECTOR_CANDIDATES]:
            add(ranking.entity)
        for entity in candidate_scope[:MAX_SELECTOR_CANDIDATES]:
            add(entity)
        return candidates

    def _terms_overlap(self, raw_name: str, term: str) -> bool:
        normalized_term = normalize_lookup_text(term)
        if not raw_name or not normalized_term:
            return False
        if raw_name in normalized_term or normalized_term in raw_name:
            return True
        raw_tokens = set(raw_name.split())
        term_tokens = set(normalized_term.split())
        return bool(raw_tokens and term_tokens and raw_tokens.intersection(term_tokens))

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
        candidates: list[RankedCatalogEntity | CatalogEntity],
        selected_ranking: RankedCatalogEntity | None,
        selector_summary: str | None,
    ) -> dict[str, Any]:
        summary = self._candidate_summary_view(
            entity=entity,
            snapshot=snapshot,
            ranking=selected_ranking,
        )
        return {
            "game": game.value,
            "entity_type": entity_type.value,
            "raw_name": raw_name,
            "applied_filters": filters,
            "resolution_status": "resolved",
            "resolved_slug": entity.slug,
            "resolved_id": entity.slug,
            "resolved_name": summary.get("name"),
            "resolved_entity": self._detailed_ranked_entity_view(
                ranking=selected_ranking,
                entity=entity,
            ),
            "resolved_by": resolved_by,
            "confidence": confidence,
            "selector_summary": selector_summary,
            "candidate_count": len(candidates),
            "candidates": self._candidate_payloads(
                snapshot=snapshot,
                candidates=candidates[:MAX_PROMPT_CANDIDATES],
            ),
        }

    def _attach_ranking(
        self,
        *,
        payload: dict[str, Any],
        ranking: RankedCatalogEntity | None,
    ) -> dict[str, Any]:
        if ranking is None:
            return payload
        payload["match_score"] = ranking.score
        payload["lexical_score"] = ranking.lexical_score
        payload["fuzzy_score"] = ranking.fuzzy_score
        payload["matched_term"] = ranking.matched_term
        payload["fuzzy_breakdown"] = dict(ranking.fuzzy_breakdown)
        return payload

    def _candidate_payloads(
        self,
        *,
        snapshot: CatalogSnapshot,
        candidates: list[RankedCatalogEntity | CatalogEntity],
    ) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for candidate in candidates:
            if isinstance(candidate, RankedCatalogEntity):
                payloads.append(
                    self._candidate_summary_view(
                        entity=candidate.entity,
                        snapshot=snapshot,
                        ranking=candidate,
                    )
                )
                continue
            payloads.append(self._candidate_summary_view(entity=candidate, snapshot=snapshot))
        return payloads

    def _detailed_ranked_entity_view(
        self,
        *,
        ranking: RankedCatalogEntity | None,
        entity: CatalogEntity | None = None,
    ) -> dict[str, Any] | None:
        ranked_entity = ranking.entity if ranking is not None else entity
        if ranked_entity is None:
            return None
        payload = self._entity_tool_view(ranked_entity)
        if payload is None:
            return None
        return self._attach_ranking(payload=payload, ranking=ranking)

    def _normalize_item_categories(self, category: str | list[str] | None) -> list[str]:
        if category is None:
            return []
        raw_values = [category] if isinstance(category, str) else list(category)
        normalized_categories: list[str] = []
        alias_map = {
            "magic": "magic",
            "ap": "magic",
            "法术": "magic",
            "法强": "magic",
            "魔法": "magic",
            "physical": "physical",
            "ad": "physical",
            "物理": "physical",
            "boots": "boots",
            "boot": "boots",
            "shoe": "boots",
            "shoes": "boots",
            "鞋": "boots",
            "鞋子": "boots",
            "enchant": "enchant",
            "附魔": "enchant",
            "tank": "tank",
            "mage": "mage",
            "support": "support_item",
        }
        for raw_value in raw_values[:8]:
            if not isinstance(raw_value, str):
                continue
            cleaned = normalize_lookup_text(raw_value)
            if not cleaned:
                continue
            normalized_value = alias_map.get(cleaned, cleaned)
            if normalized_value not in normalized_categories:
                normalized_categories.append(normalized_value)
        return normalized_categories

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
        with llm_debug_scope(
            graph_node="tool_execute",
            tool_name="resolve_catalog_slug",
            tool_stage="selector_llm",
        ):
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
