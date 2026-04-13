import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.deps import get_asset_cache_service
from app.core.config import get_settings
from app.services.asset_cache_service import AssetCacheService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/assets", tags=["Assets"])


@router.get("/{data_version}/{game}/{entity_type}/{filename}")
def get_asset(
    data_version: str,
    game: str,
    entity_type: str,
    filename: str,
    asset_cache_service: Annotated[AssetCacheService, Depends(get_asset_cache_service)],
) -> Response:
    settings = get_settings()
    root = settings.game_data_s3_root if settings.game_data_source == "s3" else settings.game_data_local_root
    relative_path = f"{game}/{entity_type}/{filename}"

    try:
        image_bytes = asset_cache_service.get_image(root, relative_path)
    except Exception as e:
        logger.warning(f"Failed to load asset {relative_path}: {e}")
        raise HTTPException(status_code=404, detail="Asset not found")

    content_type = "image/png"
    if filename.lower().endswith(".jpg") or filename.lower().endswith(".jpeg"):
        content_type = "image/jpeg"
    elif filename.lower().endswith(".webp"):
        content_type = "image/webp"

    return Response(content=image_bytes, media_type=content_type)
