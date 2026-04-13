from dataclasses import dataclass, field
from typing import Any

from app.domain.enums import Game, Language, TerminologyStyle
from app.domain.match_context import (
    GAME_SOURCE_DIRECTORY,
    canonicalize_catalog_slug,
    normalize_lookup_text,
)
from app.services.storage_service import StorageService


@dataclass(frozen=True)
class CatalogEntity:
    entity_type: str
    game: Game
    slug: str
    source_slug: str
    english_name: str
    icon_url: str | None
    raw_payload: dict[str, Any]
    display_names: dict[str, str] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)

    @property
    def search_terms(self) -> tuple[str, ...]:
        values = {
            self.slug,
            self.source_slug,
            self.english_name,
            *self.display_names.values(),
            *self.aliases,
        }
        return tuple(value for value in values if value)

    def preferred_name(self, language: Language, terminology_style: TerminologyStyle) -> str:
        if language == Language.EN:
            return self.display_names.get(Language.EN.value, self.english_name)

        zh_official = self.display_names.get(Language.ZH_CN.value)
        if terminology_style == TerminologyStyle.SLANG_ZH:
            zh_aliases = [alias for alias in self.aliases if normalize_lookup_text(alias)]
            if zh_aliases:
                return zh_aliases[0]
        return zh_official or self.english_name

    def preferred_aliases(
        self, language: Language, terminology_style: TerminologyStyle
    ) -> list[str]:
        if language == Language.EN:
            return []

        aliases: list[str] = []
        zh_official = self.display_names.get(Language.ZH_CN.value)
        selected_name = self.preferred_name(language, terminology_style)
        if zh_official and zh_official != selected_name:
            aliases.append(zh_official)
        aliases.extend(
            alias for alias in self.aliases if alias != selected_name and alias not in aliases
        )
        return aliases


@dataclass
class GameCatalog:
    champions_by_slug: dict[str, CatalogEntity]
    items_by_slug: dict[str, CatalogEntity]
    runes_by_slug: dict[str, CatalogEntity]
    search_index: list[CatalogEntity]

    def get_entities(self, entity_type: str) -> list[CatalogEntity]:
        if entity_type == "champion":
            return list(self.champions_by_slug.values())
        if entity_type == "item":
            return list(self.items_by_slug.values())
        if entity_type == "rune":
            return list(self.runes_by_slug.values())
        raise KeyError(f"Unsupported entity_type {entity_type!r}")


@dataclass
class CatalogSnapshot:
    data_version: str
    source_root: str
    manifest: dict[str, Any]
    catalogs: dict[Game, GameCatalog]


class GameDataRegistry:
    def __init__(self, storage_service: StorageService, localization_root: str) -> None:
        self.storage_service = storage_service
        self.localization_root = localization_root
        self._snapshots: dict[str, CatalogSnapshot] = {}

    def get_or_load(self, *, data_version: str, source_root: str) -> CatalogSnapshot:
        snapshot = self._snapshots.get(data_version)
        if snapshot is not None:
            return snapshot

        manifest = self.storage_service.read_json_from_root(source_root, "manifest.json")
        catalogs: dict[Game, GameCatalog] = {}
        for game in Game:
            catalogs[game] = self._load_game_catalog(game=game, source_root=source_root)

        snapshot = CatalogSnapshot(
            data_version=data_version,
            source_root=source_root,
            manifest=manifest,
            catalogs=catalogs,
        )
        self._snapshots[data_version] = snapshot
        return snapshot

    def _load_game_catalog(self, *, game: Game, source_root: str) -> GameCatalog:
        game_dir = GAME_SOURCE_DIRECTORY[game]
        champion_localization = self._load_localization_map(game_dir, "champions")
        item_localization = self._load_localization_map(game_dir, "items")
        rune_localization = self._load_localization_map(game_dir, "runes")

        champions = self._load_entities(
            game=game,
            entity_type="champion",
            source_root=source_root,
            relative_path=f"{game_dir}/champions.json",
            localization_map=champion_localization,
        )
        items = self._load_entities(
            game=game,
            entity_type="item",
            source_root=source_root,
            relative_path=f"{game_dir}/items.json",
            localization_map=item_localization,
        )
        runes = self._load_entities(
            game=game,
            entity_type="rune",
            source_root=source_root,
            relative_path=f"{game_dir}/runes.json",
            localization_map=rune_localization,
        )
        search_index = [*champions.values(), *items.values(), *runes.values()]
        return GameCatalog(
            champions_by_slug=champions,
            items_by_slug=items,
            runes_by_slug=runes,
            search_index=search_index,
        )

    def _load_entities(
        self,
        *,
        game: Game,
        entity_type: str,
        source_root: str,
        relative_path: str,
        localization_map: dict[str, dict[str, Any]],
    ) -> dict[str, CatalogEntity]:
        payload = self.storage_service.read_json_from_root(source_root, relative_path)
        entities: dict[str, CatalogEntity] = {}

        for item in payload:
            source_slug = item["slug"]
            canonical_slug = canonicalize_catalog_slug(game, source_slug)
            localization = localization_map.get(canonical_slug) or localization_map.get(
                source_slug, {}
            )
            display_names = {
                Language.EN.value: localization.get("localized_display_names", {}).get(
                    "en", item["name"]
                ),
            }
            zh_official_name = localization.get("zh_official_name") or localization.get(
                "localized_display_names",
                {},
            ).get("zh-CN")
            if zh_official_name:
                display_names[Language.ZH_CN.value] = zh_official_name

            aliases: list[str] = []
            for alias_key in ("aliases", "zh_aliases"):
                aliases.extend(localization.get(alias_key, []))
            aliases = list(dict.fromkeys(alias for alias in aliases if alias))

            entities[canonical_slug] = CatalogEntity(
                entity_type=entity_type,
                game=game,
                slug=canonical_slug,
                source_slug=source_slug,
                english_name=item["name"],
                icon_url=item.get("icon_url"),
                raw_payload=item,
                display_names=display_names,
                aliases=aliases,
            )

        return entities

    def _load_localization_map(
        self, game_dir: str, entity_plural: str
    ) -> dict[str, dict[str, Any]]:
        relative_path = f"{game_dir}/{entity_plural}.zh-CN.json"
        payload = self.storage_service.read_optional_json_from_root(
            self.localization_root, relative_path
        )
        if payload is None:
            return {}
        if isinstance(payload, dict):
            return {key: value if isinstance(value, dict) else {} for key, value in payload.items()}
        if isinstance(payload, list):
            records: dict[str, dict[str, Any]] = {}
            for item in payload:
                if isinstance(item, dict) and item.get("slug"):
                    records[item["slug"]] = item
            return records
        return {}
