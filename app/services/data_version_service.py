from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import DataVersion
from app.repositories.core import DataVersionsRepository
from app.services.storage_service import StorageService


class DataVersionService:
    def __init__(self, settings: Settings, storage_service: StorageService) -> None:
        self.settings = settings
        self.storage_service = storage_service

    def get_active_version(self, session: Session) -> DataVersion:
        repository = DataVersionsRepository(session)
        active_version = repository.get_active()
        if active_version is not None:
            return active_version
        return self._bootstrap_current_version(repository)

    def list_versions(self, session: Session, *, active_only: bool = False) -> list[DataVersion]:
        repository = DataVersionsRepository(session)
        versions = repository.list(active_only=active_only)
        if versions:
            return versions
        return [self._bootstrap_current_version(repository)]

    def get_version(self, session: Session, *, data_version: str) -> DataVersion | None:
        repository = DataVersionsRepository(session)
        existing = repository.get_by_data_version(data_version)
        if existing is not None:
            return existing

        active_version = self.get_active_version(session)
        if active_version.data_version == data_version:
            return active_version
        return None

    def _bootstrap_current_version(self, repository: DataVersionsRepository) -> DataVersion:
        source_root = self._resolve_source_root()
        manifest_object_key = self._build_manifest_object_key(source_root)
        manifest = self.storage_service.read_json_from_root(source_root, "manifest.json")

        return repository.create(
            data_version=manifest.get("snapshot_id", "unknown"),
            manifest_object_key=manifest_object_key,
            source_root=source_root,
            lol_patch_version=self._extract_patch_version(manifest, "lol"),
            wild_rift_patch_version=self._extract_patch_version(manifest, "wild_rift"),
            is_active=True,
            activated_at=datetime.now(tz=timezone.utc),
        )

    def _resolve_source_root(self) -> str:
        if self.settings.game_data_source == "s3":
            return self.settings.game_data_s3_root
        return self.settings.game_data_local_root

    def _build_manifest_object_key(self, source_root: str) -> str:
        return f"{source_root.rstrip('/')}/manifest.json"

    def _extract_patch_version(self, manifest: dict[str, Any], game_key: str) -> str | None:
        patches = manifest.get("patch_versions")
        if isinstance(patches, dict):
            value = patches.get(game_key)
            if isinstance(value, str):
                return value
        return None
