from app.main import app
from sqlalchemy.orm import Session
from app.services.catalog_service import CatalogService
from app.domain.enums import Game, Language, TerminologyStyle

from app.api.schemas.catalog import CatalogEntityType
settings = app.state.settings
catalog_service = app.state.catalog_service
session_factory = app.state.session_factory

with session_factory() as session:
    try:
        catalog_service.list_entities(
            session,
            game=Game.WILD_RIFT,
            entity_type=CatalogEntityType.CHAMPION,
            data_version=None,
            language=Language.ZH_CN,
            terminology_style=TerminologyStyle.OFFICIAL
        )
        print("Success!")
    except Exception as e:
        import traceback
        traceback.print_exc()

