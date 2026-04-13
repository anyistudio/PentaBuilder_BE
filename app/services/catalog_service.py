from sqlalchemy.orm import Session

from app.api.schemas.catalog import CatalogEntitySummary, CatalogEntityType, CatalogLookupResult
from app.catalog.registry import CatalogEntity, GameDataRegistry
from app.domain.enums import Game, Language, TerminologyStyle
from app.domain.match_context import normalize_lookup_text
from app.services.data_version_service import DataVersionService


class CatalogService:
    def __init__(
        self,
        *,
        data_version_service: DataVersionService,
        registry: GameDataRegistry,
    ) -> None:
        self.data_version_service = data_version_service
        self.registry = registry

    def get_current_version(self, session: Session):
        return self.data_version_service.get_active_version(session)

    def list_versions(self, session: Session, *, active_only: bool = False):
        return self.data_version_service.list_versions(session, active_only=active_only)

    def list_entities(
        self,
        session: Session,
        *,
        game: Game,
        entity_type: CatalogEntityType,
        data_version: str | None,
        language: Language,
        terminology_style: TerminologyStyle,
    ) -> tuple[str, list[CatalogEntitySummary]]:
        version = self._resolve_version(session, data_version=data_version)
        snapshot = self.registry.get_or_load(
            data_version=version.data_version,
            source_root=version.source_root,
        )
        entities = snapshot.catalogs[game].get_entities(entity_type.value)
        summaries = [
            self._format_entity(entity, language=language, terminology_style=terminology_style)
            for entity in entities
        ]
        return version.data_version, sorted(summaries, key=lambda item: item.name.lower())

    def lookup(
        self,
        session: Session,
        *,
        game: Game,
        query: str,
        entity_type: CatalogEntityType | None,
        data_version: str | None,
        language: Language,
        terminology_style: TerminologyStyle,
        limit: int,
    ) -> tuple[str, list[CatalogLookupResult]]:
        version = self._resolve_version(session, data_version=data_version)
        snapshot = self.registry.get_or_load(
            data_version=version.data_version,
            source_root=version.source_root,
        )
        q_normalized = query.strip()
        results: list[tuple[int, CatalogEntity]] = []

        for entity in snapshot.catalogs[game].search_index:
            if entity_type is not None and entity.entity_type != entity_type.value:
                continue
            score = self._score_entity(query=q_normalized, entity=entity)
            if score > 0:
                results.append((score, entity))

        ordered = sorted(
            results,
            key=lambda item: (
                -item[0],
                item[1].english_name.lower(),
                item[1].slug,
            ),
        )
        payload = [
            CatalogLookupResult(
                entity_type=CatalogEntityType(entity.entity_type),
                game=entity.game,
                slug=entity.slug,
                name=entity.preferred_name(language, terminology_style),
                aliases=entity.preferred_aliases(language, terminology_style),
                icon_url=entity.icon_url,
            )
            for _, entity in ordered[:limit]
        ]
        return version.data_version, payload

    def _resolve_version(self, session: Session, *, data_version: str | None):
        if data_version is None:
            return self.data_version_service.get_active_version(session)
        version = self.data_version_service.get_version(session, data_version=data_version)
        if version is None:
            raise LookupError(f"Unknown data_version {data_version!r}")
        return version

    def _format_entity(
        self,
        entity: CatalogEntity,
        *,
        language: Language,
        terminology_style: TerminologyStyle,
    ) -> CatalogEntitySummary:
        return CatalogEntitySummary(
            slug=entity.slug,
            name=entity.preferred_name(language, terminology_style),
            aliases=entity.preferred_aliases(language, terminology_style),
            icon_url=entity.icon_url,
        )

    def _score_entity(self, *, query: str, entity: CatalogEntity) -> int:
        query_normalized = normalize_lookup_text(query)
        best_score = 0
        for candidate in entity.search_terms:
            candidate_normalized = normalize_lookup_text(candidate)
            if not candidate_normalized:
                continue
            if candidate_normalized == query_normalized:
                best_score = max(best_score, 300)
            elif candidate_normalized.startswith(query_normalized):
                best_score = max(best_score, 200 - len(candidate_normalized))
            elif query_normalized in candidate_normalized:
                best_score = max(best_score, 100 - len(candidate_normalized))
        return best_score
