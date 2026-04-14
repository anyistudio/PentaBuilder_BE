from datetime import datetime, timezone
from itertools import islice

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.ai.providers.factory import create_llm_client
from app.catalog.registry import CatalogEntity, GameDataRegistry
from app.core.config import get_settings
from app.core.errors import ApiError
from app.db.models import ModelCalibration
from app.domain.enums import Game
from app.services.data_version_service import DataVersionService
from app.services.storage_service import StorageService

CALIBRATION_BATCH_SIZE = 40
CALIBRATION_SYSTEM_PROMPT = (
    "You are checking whether the provided game data likely differs from your built-in game "
    "knowledge. Focus on entries that look newly introduced, renamed, reworked, or otherwise "
    "likely to differ from older internal knowledge. Keep the output concise and structured."
)


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

    settings = get_settings()
    llm_client = create_llm_client(
        settings=settings,
        provider_name=provider_name,
        model_name=model_name,
    )
    if llm_client is None:
        raise ApiError(
            "No LLM client is configured for the requested provider/model.",
            code="provider_not_configured",
            status_code=503,
        )

    snapshot = registry.get_or_load(
        data_version=version.data_version,
        source_root=version.source_root,
    )
    catalog = snapshot.catalogs[game]
    entries = [
        *catalog.champions_by_slug.values(),
        *catalog.items_by_slug.values(),
        *catalog.runes_by_slug.values(),
    ]
    batch_notes: list[str] = []
    for batch_index, batch in enumerate(_batched(entries, CALIBRATION_BATCH_SIZE), start=1):
        prompt = "\n".join(
            [
                f"Game: {game.value}",
                f"Data version: {version.data_version}",
                f"Batch: {batch_index}",
                "",
                "For this batch:",
                (
                    "1. List entries that likely changed or look unfamiliar "
                    "relative to your prior knowledge."
                ),
                "2. For each entry, briefly state the suspected difference.",
                "3. Keep the output concise and structured.",
                "",
                "Catalog batch:",
                *(_format_entity_for_calibration(entity) for entity in batch),
            ]
        )
        result = llm_client.generate_text(
            prompt=prompt,
            system_prompt=CALIBRATION_SYSTEM_PROMPT,
            temperature=0.1,
        )
        if result.text.strip():
            batch_notes.append(f"## Batch {batch_index}\n{result.text.strip()}")

    summary_text = "\n\n".join(batch_notes) if batch_notes else "No calibration notes generated."
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
    excerpt = summary_text[:400]
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


def _batched(items: list[CatalogEntity], size: int):
    iterator = iter(items)
    while batch := list(islice(iterator, size)):
        yield batch


def _format_entity_for_calibration(entity: CatalogEntity) -> str:
    payload = entity.raw_payload if isinstance(entity.raw_payload, dict) else {}
    if entity.entity_type == "champion":
        infobox = payload.get("infobox", {})
        class_text = infobox.get("Class(es)") or "unknown"
        positions = infobox.get("Position(s)") or "unknown"
        return (
            f"- champion | {entity.slug} | {entity.english_name} | "
            f"class={class_text} | positions={positions}"
        )
    if entity.entity_type == "item":
        stats = (
            ", ".join(str(stat) for stat in (payload.get("stats") or [])[:3])
            or "no short stats"
        )
        return f"- item | {entity.slug} | {entity.english_name} | stats={stats}"
    path = payload.get("path") or payload.get("attributes", {}).get("Path") or "unknown"
    description = " ".join(str(payload.get("description") or "").split())[:140]
    return (
        f"- rune | {entity.slug} | {entity.english_name} | path={path} | "
        f"description={description}"
    )
