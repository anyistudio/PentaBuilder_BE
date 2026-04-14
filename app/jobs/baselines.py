from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.catalog.registry import GameDataRegistry
from app.db.models import BaselineBuild
from app.domain.enums import Game, RunType
from app.domain.match_context import MatchContext, ResponsePreferences
from app.services.ai_run_service import AIRunService
from app.services.data_version_service import DataVersionService


def precompute_baselines(
    session: Session,
    *,
    data_version_service: DataVersionService,
    registry: GameDataRegistry,
    ai_run_service: AIRunService,
    game: Game,
    data_version: str,
    provider_name: str,
    model_name: str,
) -> dict[str, object]:
    version = data_version_service.get_version(session, data_version=data_version)
    if version is None:
        raise LookupError(f"Unknown data version {data_version!r}")

    snapshot = registry.get_or_load(
        data_version=version.data_version,
        source_root=version.source_root,
    )
    champion_slugs = sorted(snapshot.catalogs[game].champions_by_slug)
    created_count = 0
    updated_count = 0

    for champion_slug in champion_slugs:
        context = MatchContext(
            game=game,
            data_version=version.data_version,
            own_champion_slug=champion_slug,
            environment={"tags": [], "free_text": ""},
        )
        run, _ = ai_run_service.create_run(
            session,
            user=None,
            session_id=None,
            run_type=RunType.RECOMMEND_FULL_BUILD,
            context=context,
            response_preferences=ResponsePreferences(),
            operation_context={},
            stream=False,
            use_cache=False,
        )
        result = ai_run_service.execute_run(
            session,
            run=run,
            context=context,
            response_preferences=ResponsePreferences(),
            operation_context={},
            provider_name_override=provider_name,
            model_name_override=model_name,
        )
        existing = session.scalar(
            sa.select(BaselineBuild).where(
                BaselineBuild.game == game.value,
                BaselineBuild.data_version == version.data_version,
                BaselineBuild.own_champion_slug == champion_slug,
            )
        )
        if existing is None:
            existing = BaselineBuild(
                game=game.value,
                data_version=version.data_version,
                own_champion_slug=champion_slug,
                recommended_build=(
                    result.get("recommended_build_order")
                    or result.get("recommended_build")
                    or result.get("build")
                    or []
                ),
                recommended_runes=result.get("recommended_runes") or result.get("runes") or {},
                provider_name=provider_name,
                model_name=model_name,
                source_run_id=run.id,
            )
            created_count += 1
        else:
            existing.recommended_build = (
                result.get("recommended_build_order")
                or result.get("recommended_build")
                or result.get("build")
                or []
            )
            existing.recommended_runes = (
                result.get("recommended_runes") or result.get("runes") or {}
            )
            existing.provider_name = provider_name
            existing.model_name = model_name
            existing.source_run_id = run.id
            updated_count += 1
        session.add(existing)

    session.commit()
    return {
        "game": game.value,
        "data_version": version.data_version,
        "champion_count": len(champion_slugs),
        "created_count": created_count,
        "updated_count": updated_count,
        "completed_at": datetime.now(tz=timezone.utc).isoformat(),
    }
