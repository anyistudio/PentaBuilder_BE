from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.catalog.registry import GameDataRegistry
from app.db.models import ModelCalibration
from app.domain.enums import Game
from app.services.data_version_service import DataVersionService
from app.services.storage_service import StorageService


def generate_calibration_summary(
    session: Session,
    *,
    storage_service: StorageService,
    data_version_service: DataVersionService,
    registry: GameDataRegistry,
    provider_name: str,
    model_name: str,
    game: Game,
    data_version: str,
) -> dict[str, object]:
    version = data_version_service.get_version(session, data_version=data_version)
    if version is None:
        raise LookupError(f"Unknown data version {data_version!r}")

    snapshot = registry.get_or_load(
        data_version=version.data_version,
        source_root=version.source_root,
    )
    catalog = snapshot.catalogs[game]
    summary_lines = [
        f"Calibration summary for {provider_name}/{model_name}",
        f"Game: {game.value}",
        f"Data version: {version.data_version}",
        f"Champion count: {len(catalog.champions_by_slug)}",
        f"Item count: {len(catalog.items_by_slug)}",
        f"Rune count: {len(catalog.runes_by_slug)}",
        "Always use canonical slugs with the correct game prefix.",
        "Never mix LoL PC and Wild Rift entities inside the same answer.",
        "Generate the final answer directly in the user's target language.",
    ]
    summary_text = "\n".join(summary_lines)
    object_key = (
        f"calibrations/{provider_name}/{model_name}/{game.value}/{version.data_version}/summary.txt"
    )
    storage_service.write_text(object_key, summary_text)

    record = session.scalar(
        sa.select(ModelCalibration).where(
            ModelCalibration.provider_name == provider_name,
            ModelCalibration.model_name == model_name,
            ModelCalibration.game == game.value,
            ModelCalibration.data_version == version.data_version,
        )
    )
    excerpt = " ".join(summary_lines[:4])
    if record is None:
        record = ModelCalibration(
            provider_name=provider_name,
            model_name=model_name,
            game=game.value,
            data_version=version.data_version,
            status="completed",
            summary_object_key=object_key,
            summary_excerpt=excerpt,
        )
    else:
        record.status = "completed"
        record.summary_object_key = object_key
        record.summary_excerpt = excerpt
    session.add(record)
    session.commit()
    session.refresh(record)
    return {
        "id": str(record.id),
        "provider_name": provider_name,
        "model_name": model_name,
        "game": game.value,
        "data_version": version.data_version,
        "summary_object_key": object_key,
        "completed_at": datetime.now(tz=timezone.utc).isoformat(),
    }
