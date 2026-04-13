from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import Game, Language, TerminologyStyle


class CatalogEntityType(str, Enum):
    CHAMPION = "champion"
    ITEM = "item"
    RUNE = "rune"


class CatalogEntitySummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slug: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    icon_url: str | None = None


class CatalogLookupResult(CatalogEntitySummary):
    entity_type: CatalogEntityType
    game: Game


class CatalogVersionPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data_version: str
    lol_patch_version: str | None = None
    wild_rift_patch_version: str | None = None
    activated_at: str | None = None


class CatalogVersionListPayload(BaseModel):
    versions: list[CatalogVersionPayload]


class CatalogCollectionPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    game: Game
    data_version: str
    champions: list[CatalogEntitySummary] | None = None
    items: list[CatalogEntitySummary] | None = None
    runes: list[CatalogEntitySummary] | None = None


class CatalogLookupPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    game: Game
    data_version: str
    query: str
    results: list[CatalogLookupResult]


class CatalogQueryOptions(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data_version: str | None = None
    language: Language = Language.ZH_CN
    terminology_style: TerminologyStyle = TerminologyStyle.OFFICIAL
