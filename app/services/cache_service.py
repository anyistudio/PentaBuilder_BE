from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import CachedContextResult

CACHEABLE_RUN_TYPES = {
    "evaluate_build",
    "recommend_slot",
    "recommend_full_build",
    "explain_slot",
    "compare_builds",
    "game_status",
}


class CacheService:
    def lookup_strong_cache(
        self,
        session: Session,
        *,
        run_type: str,
        response_variant_hash: str,
    ) -> CachedContextResult | None:
        stmt = sa.select(CachedContextResult).where(
            CachedContextResult.run_type == run_type,
            CachedContextResult.response_variant_hash == response_variant_hash,
        )
        return session.scalar(stmt)

    def lookup_reference_cache(
        self,
        session: Session,
        *,
        run_type: str,
        semantic_context_hash: str,
    ) -> CachedContextResult | None:
        stmt = (
            sa.select(CachedContextResult)
            .where(
                CachedContextResult.run_type == run_type,
                CachedContextResult.semantic_context_hash == semantic_context_hash,
            )
            .order_by(
                CachedContextResult.last_hit_at.desc().nullslast(),
                CachedContextResult.created_at.desc(),
            )
            .limit(1)
        )
        return session.scalar(stmt)

    def save_cache_entry(
        self,
        session: Session,
        *,
        run_type: str,
        game: str,
        data_version: str,
        own_champion_slug: str,
        enemy_comp_key: str,
        enemy_count: int,
        normalized_environment_key: str,
        semantic_context_hash: str,
        response_variant_hash: str,
        language: str,
        terminology_style: str,
        structured_result: dict[str, Any],
        artifact_object_key: str,
        source_run_id,
    ) -> CachedContextResult:
        existing = self.lookup_strong_cache(
            session,
            run_type=run_type,
            response_variant_hash=response_variant_hash,
        )
        if existing is not None:
            existing.structured_result = structured_result
            existing.artifact_object_key = artifact_object_key
            existing.source_run_id = source_run_id
            existing.last_hit_at = datetime.now(tz=timezone.utc)
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return existing

        entry = CachedContextResult(
            run_type=run_type,
            game=game,
            data_version=data_version,
            own_champion_slug=own_champion_slug,
            enemy_comp_key=enemy_comp_key,
            enemy_count=enemy_count,
            normalized_environment_key=normalized_environment_key,
            semantic_context_hash=semantic_context_hash,
            response_variant_hash=response_variant_hash,
            language=language,
            terminology_style=terminology_style,
            structured_result=structured_result,
            artifact_object_key=artifact_object_key,
            source_run_id=source_run_id,
            last_hit_at=datetime.now(tz=timezone.utc),
        )
        session.add(entry)
        session.commit()
        session.refresh(entry)
        return entry

    def clear_cache(
        self,
        session: Session,
        *,
        data_version: str | None = None,
        game: str | None = None,
    ) -> int:
        stmt = sa.delete(CachedContextResult)
        if data_version:
            stmt = stmt.where(CachedContextResult.data_version == data_version)
        if game:
            stmt = stmt.where(CachedContextResult.game == game)
        result = session.execute(stmt)
        session.commit()
        return result.rowcount or 0
