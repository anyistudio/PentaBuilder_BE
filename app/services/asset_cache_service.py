import logging
from functools import lru_cache

from app.core.config import Settings
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)


class AssetCacheService:
    def __init__(self, settings: Settings, storage_service: StorageService) -> None:
        self.settings = settings
        self.storage_service = storage_service

    @lru_cache(maxsize=2048)
    def _get_image_cached(self, root: str, relative_path: str) -> bytes:
        logger.info("AssetCache miss: fetching %s from %s", relative_path, root)
        return self.storage_service.read_bytes_from_root(root, relative_path)

    def get_image(self, root: str, relative_path: str) -> bytes:
        return self._get_image_cached(root, relative_path)
