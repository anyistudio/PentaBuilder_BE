from dataclasses import dataclass
from typing import Any

from app.api.schemas.catalog import CatalogEntityType
from app.catalog.registry import CatalogSnapshot
from app.domain.enums import Game, Language, TerminologyStyle
from app.services.catalog_service import CatalogService


@dataclass
class CatalogToolset:
    catalog_service: CatalogService

    def get_champion(self, snapshot: CatalogSnapshot, slug: str) -> dict[str, Any] | None:
        entity = snapshot.catalogs[self._game_from_slug(slug)].champions_by_slug.get(slug)
        return entity.raw_payload if entity else None

    def get_item(self, snapshot: CatalogSnapshot, slug: str) -> dict[str, Any] | None:
        entity = snapshot.catalogs[self._game_from_slug(slug)].items_by_slug.get(slug)
        return entity.raw_payload if entity else None

    def get_rune(self, snapshot: CatalogSnapshot, slug: str) -> dict[str, Any] | None:
        entity = snapshot.catalogs[self._game_from_slug(slug)].runes_by_slug.get(slug)
        return entity.raw_payload if entity else None

    def batch_get_entities(
        self, snapshot: CatalogSnapshot, slugs: list[str]
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for slug in slugs:
            entity = None
            game_catalog = snapshot.catalogs[self._game_from_slug(slug)]
            entity = (
                game_catalog.champions_by_slug.get(slug)
                or game_catalog.items_by_slug.get(slug)
                or game_catalog.runes_by_slug.get(slug)
            )
            if entity:
                results.append(entity.raw_payload)
        return results

    def search_catalog(
        self,
        session,
        *,
        game: Game,
        snapshot: CatalogSnapshot,
        query: str,
        entity_type: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        _, results = self.catalog_service.lookup(
            session,
            game=game,
            query=query,
            entity_type=CatalogEntityType(entity_type) if entity_type else None,
            data_version=snapshot.data_version,
            language=Language.ZH_CN,
            terminology_style=TerminologyStyle.OFFICIAL,
            limit=limit,
        )
        return [result.model_dump(mode="json") for result in results]

    def _game_from_slug(self, slug: str) -> Game:
        return Game.LOL if slug.startswith("lol-") else Game.WILD_RIFT
