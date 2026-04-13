from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_catalog_service, get_db_session
from app.api.schemas.catalog import (
    CatalogCollectionPayload,
    CatalogEntityType,
    CatalogLookupPayload,
    CatalogVersionListPayload,
    CatalogVersionPayload,
)
from app.api.schemas.common import ApiResponse
from app.domain.enums import Game, Language, TerminologyStyle
from app.services.catalog_service import CatalogService

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])


@router.get("/versions/current")
def get_current_catalog_version(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> ApiResponse[CatalogVersionPayload]:
    version = catalog_service.get_current_version(session)
    return ApiResponse[CatalogVersionPayload](
        request_id=request.state.request_id,
        data=CatalogVersionPayload(
            data_version=version.data_version,
            lol_patch_version=version.lol_patch_version,
            wild_rift_patch_version=version.wild_rift_patch_version,
            activated_at=version.activated_at.isoformat() if version.activated_at else None,
        ),
    )


@router.get("/versions")
def list_catalog_versions(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
    active_only: bool = False,
) -> ApiResponse[CatalogVersionListPayload]:
    versions = catalog_service.list_versions(session, active_only=active_only)
    payload = CatalogVersionListPayload(
        versions=[
            CatalogVersionPayload(
                data_version=version.data_version,
                lol_patch_version=version.lol_patch_version,
                wild_rift_patch_version=version.wild_rift_patch_version,
                activated_at=version.activated_at.isoformat() if version.activated_at else None,
            )
            for version in versions
        ]
    )
    return ApiResponse[CatalogVersionListPayload](request_id=request.state.request_id, data=payload)


@router.get("/{game}/champions")
def list_champions(
    request: Request,
    game: Game,
    session: Annotated[Session, Depends(get_db_session)],
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
    data_version: str | None = None,
    language: Language = Language.ZH_CN,
    terminology_style: TerminologyStyle = TerminologyStyle.OFFICIAL,
) -> ApiResponse[CatalogCollectionPayload]:
    resolved_version, champions = catalog_service.list_entities(
        session,
        game=game,
        entity_type=CatalogEntityType.CHAMPION,
        data_version=data_version,
        language=language,
        terminology_style=terminology_style,
    )
    payload = CatalogCollectionPayload(
        game=game,
        data_version=resolved_version,
        champions=champions,
    )
    return ApiResponse[CatalogCollectionPayload](request_id=request.state.request_id, data=payload)


@router.get("/{game}/items")
def list_items(
    request: Request,
    game: Game,
    session: Annotated[Session, Depends(get_db_session)],
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
    data_version: str | None = None,
    language: Language = Language.ZH_CN,
    terminology_style: TerminologyStyle = TerminologyStyle.OFFICIAL,
) -> ApiResponse[CatalogCollectionPayload]:
    resolved_version, items = catalog_service.list_entities(
        session,
        game=game,
        entity_type=CatalogEntityType.ITEM,
        data_version=data_version,
        language=language,
        terminology_style=terminology_style,
    )
    payload = CatalogCollectionPayload(
        game=game,
        data_version=resolved_version,
        items=items,
    )
    return ApiResponse[CatalogCollectionPayload](request_id=request.state.request_id, data=payload)


@router.get("/{game}/runes")
def list_runes(
    request: Request,
    game: Game,
    session: Annotated[Session, Depends(get_db_session)],
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
    data_version: str | None = None,
    language: Language = Language.ZH_CN,
    terminology_style: TerminologyStyle = TerminologyStyle.OFFICIAL,
) -> ApiResponse[CatalogCollectionPayload]:
    resolved_version, runes = catalog_service.list_entities(
        session,
        game=game,
        entity_type=CatalogEntityType.RUNE,
        data_version=data_version,
        language=language,
        terminology_style=terminology_style,
    )
    payload = CatalogCollectionPayload(
        game=game,
        data_version=resolved_version,
        runes=runes,
    )
    return ApiResponse[CatalogCollectionPayload](request_id=request.state.request_id, data=payload)


@router.get("/{game}/lookup")
def lookup_catalog(
    request: Request,
    game: Game,
    q: Annotated[str, Query(min_length=1)],
    session: Annotated[Session, Depends(get_db_session)],
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
    entity_type: CatalogEntityType | None = None,
    data_version: str | None = None,
    language: Language = Language.ZH_CN,
    terminology_style: TerminologyStyle = TerminologyStyle.OFFICIAL,
    limit: int = Query(default=20, ge=1, le=50),
) -> ApiResponse[CatalogLookupPayload]:
    resolved_version, results = catalog_service.lookup(
        session,
        game=game,
        query=q,
        entity_type=entity_type,
        data_version=data_version,
        language=language,
        terminology_style=terminology_style,
        limit=limit,
    )
    payload = CatalogLookupPayload(
        game=game,
        data_version=resolved_version,
        query=q,
        results=results,
    )
    return ApiResponse[CatalogLookupPayload](request_id=request.state.request_id, data=payload)
