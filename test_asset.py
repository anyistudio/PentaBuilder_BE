import asyncio
from app.core.config import get_settings
from app.services.storage_service import StorageService
from app.services.asset_cache_service import AssetCacheService

settings = get_settings()
storage_service = StorageService(settings)
cache = AssetCacheService(settings, storage_service)

root = settings.game_data_s3_root if settings.game_data_source == "s3" else settings.game_data_local_root
print("root:", root)
try:
    data = cache.get_image(root, "full-20260411/wild_rift/champion_icons/aatrox.png")
    print("success, length:", len(data))
except Exception as e:
    import traceback
    traceback.print_exc()
