import re
from typing import Any

from sqlalchemy.orm import Session

from app.api.schemas.catalog import (
    CatalogAbilitySummary,
    CatalogEntitySummary,
    CatalogEntityType,
    CatalogLookupResult,
)
from app.catalog.registry import CatalogEntity, GameDataRegistry
from app.domain.enums import Game, Language, TerminologyStyle
from app.domain.match_context import normalize_lookup_text
from app.services.data_version_service import DataVersionService

POSITION_ORDER = ("top", "jungle", "mid", "adc", "support")

POSITION_LABELS = {
    "top": {Language.ZH_CN: "上路", Language.EN: "Top"},
    "jungle": {Language.ZH_CN: "打野", Language.EN: "Jungle"},
    "mid": {Language.ZH_CN: "中路", Language.EN: "Mid"},
    "adc": {Language.ZH_CN: "射手", Language.EN: "ADC"},
    "support": {Language.ZH_CN: "辅助", Language.EN: "Support"},
}

TRAIT_HINTS = (
    ("dash champion", {Language.ZH_CN: "位移", Language.EN: "Mobility"}),
    ("blink champion", {Language.ZH_CN: "突进", Language.EN: "Blink"}),
    ("stun champion", {Language.ZH_CN: "眩晕", Language.EN: "Stun"}),
    ("root champion", {Language.ZH_CN: "禁锢", Language.EN: "Root"}),
    ("knockup champion", {Language.ZH_CN: "击飞", Language.EN: "Knock Up"}),
    ("knockback champion", {Language.ZH_CN: "击退", Language.EN: "Knockback"}),
    ("charm champion", {Language.ZH_CN: "魅惑", Language.EN: "Charm"}),
    ("shield champion", {Language.ZH_CN: "护盾", Language.EN: "Shield"}),
    ("healer champion", {Language.ZH_CN: "治疗", Language.EN: "Healing"}),
    ("self heal champion", {Language.ZH_CN: "自疗", Language.EN: "Self-Heal"}),
    ("stealth champion", {Language.ZH_CN: "隐身", Language.EN: "Stealth"}),
    ("execution champion", {Language.ZH_CN: "斩杀", Language.EN: "Execute"}),
    ("global champion", {Language.ZH_CN: "全图", Language.EN: "Global"}),
)

ITEM_ATTRIBUTE_LABELS = {
    "Cost": {Language.ZH_CN: "总价", Language.EN: "Cost"},
    "Sell": {Language.ZH_CN: "售价", Language.EN: "Sell"},
    "Cooldown": {Language.ZH_CN: "冷却", Language.EN: "Cooldown"},
    "Range": {Language.ZH_CN: "范围", Language.EN: "Range"},
    "Path": {Language.ZH_CN: "路径", Language.EN: "Path"},
    "Slot": {Language.ZH_CN: "槽位", Language.EN: "Slot"},
}


class CatalogService:
    def __init__(
        self,
        *,
        data_version_service: DataVersionService,
        registry: GameDataRegistry,
    ) -> None:
        self.data_version_service = data_version_service
        self.registry = registry

    def get_current_version(self, session: Session):
        return self.data_version_service.get_active_version(session)

    def list_versions(self, session: Session, *, active_only: bool = False):
        return self.data_version_service.list_versions(session, active_only=active_only)

    def list_entities(
        self,
        session: Session,
        *,
        game: Game,
        entity_type: CatalogEntityType,
        data_version: str | None,
        language: Language,
        terminology_style: TerminologyStyle,
    ) -> tuple[str, list[CatalogEntitySummary]]:
        version = self._resolve_version(session, data_version=data_version)
        snapshot = self.registry.get_or_load(
            data_version=version.data_version,
            source_root=version.source_root,
        )
        entities = snapshot.catalogs[game].get_entities(entity_type.value)
        summaries = [
            self._format_entity(entity, language=language, terminology_style=terminology_style)
            for entity in entities
        ]
        return version.data_version, sorted(summaries, key=lambda item: item.name.lower())

    def lookup(
        self,
        session: Session,
        *,
        game: Game,
        query: str,
        entity_type: CatalogEntityType | None,
        data_version: str | None,
        language: Language,
        terminology_style: TerminologyStyle,
        limit: int,
    ) -> tuple[str, list[CatalogLookupResult]]:
        version = self._resolve_version(session, data_version=data_version)
        snapshot = self.registry.get_or_load(
            data_version=version.data_version,
            source_root=version.source_root,
        )
        q_normalized = query.strip()
        results: list[tuple[int, CatalogEntity]] = []

        for entity in snapshot.catalogs[game].search_index:
            if entity_type is not None and entity.entity_type != entity_type.value:
                continue
            score = self._score_entity(query=q_normalized, entity=entity)
            if score > 0:
                results.append((score, entity))

        ordered = sorted(
            results,
            key=lambda item: (
                -item[0],
                item[1].english_name.lower(),
                item[1].slug,
            ),
        )
        payload = [
            CatalogLookupResult(
                **self._format_entity(
                    entity,
                    language=language,
                    terminology_style=terminology_style,
                ).model_dump(),
                entity_type=CatalogEntityType(entity.entity_type),
                game=entity.game,
            )
            for _, entity in ordered[:limit]
        ]
        return version.data_version, payload

    def _resolve_version(self, session: Session, *, data_version: str | None):
        if data_version is None:
            return self.data_version_service.get_active_version(session)
        version = self.data_version_service.get_version(session, data_version=data_version)
        if version is None:
            raise LookupError(f"Unknown data_version {data_version!r}")
        return version

    def _format_entity(
        self,
        entity: CatalogEntity,
        *,
        language: Language,
        terminology_style: TerminologyStyle,
    ) -> CatalogEntitySummary:
        raw_payload = entity.raw_payload if isinstance(entity.raw_payload, dict) else {}
        base_payload: dict[str, Any] = {
            "slug": entity.slug,
            "name": entity.preferred_name(language, terminology_style),
            "aliases": entity.preferred_aliases(language, terminology_style),
            "icon_url": entity.icon_url,
        }

        if entity.entity_type == CatalogEntityType.CHAMPION.value:
            class_text = self._infer_class_text(raw_payload)
            position_tags = self._extract_position_tags(entity.game, raw_payload)
            range_type = self._infer_range_type(raw_payload)
            resource = self._infer_resource(raw_payload)
            abilities = self._build_ability_summaries(raw_payload)
            return CatalogEntitySummary(
                **base_payload,
                summary=self._build_champion_summary(
                    raw_payload=raw_payload,
                    language=language,
                    position_tags=position_tags,
                    class_text=class_text,
                    range_type=range_type,
                    resource=resource,
                ),
                class_text=class_text,
                position_tags=position_tags,
                range_type=range_type,
                resource=resource,
                abilities=abilities,
            )

        if entity.entity_type == CatalogEntityType.ITEM.value:
            attributes = self._dict_from_unknown(raw_payload.get("attributes"))
            stats = self._list_of_strings(raw_payload.get("stats"))
            return CatalogEntitySummary(
                **base_payload,
                cost=self._text_or_none(attributes.get("Cost")),
                description=self._text_or_none(raw_payload.get("description")),
                stats=stats,
                main_attributes=self._build_item_main_attributes(
                    attributes=attributes,
                    stats=stats,
                    language=language,
                ),
            )

        return CatalogEntitySummary(
            **base_payload,
        )

    def _score_entity(self, *, query: str, entity: CatalogEntity) -> int:
        query_normalized = normalize_lookup_text(query)
        best_score = 0
        for candidate in entity.search_terms:
            candidate_normalized = normalize_lookup_text(candidate)
            if not candidate_normalized:
                continue
            if candidate_normalized == query_normalized:
                best_score = max(best_score, 300)
            elif candidate_normalized.startswith(query_normalized):
                best_score = max(best_score, 200 - len(candidate_normalized))
            elif query_normalized in candidate_normalized:
                best_score = max(best_score, 100 - len(candidate_normalized))
        return best_score

    def _extract_position_tags(self, game: Game, raw_payload: dict[str, Any]) -> list[str]:
        infobox = self._dict_from_unknown(raw_payload.get("infobox"))
        explicit_positions = self._text_or_none(infobox.get("Position(s)"), lowercase=True) or ""
        class_text = (self._infer_class_text(raw_payload) or "").lower()
        category_text = " ".join(self._list_of_strings(raw_payload.get("categories"))).lower()
        range_type = self._infer_range_type(raw_payload)
        resource = (self._infer_resource(raw_payload) or "").lower()
        magic_hits, physical_hits = self._damage_profile(raw_payload)
        attack_range = self._parse_first_number(infobox.get("Attack range"))

        tags: list[str] = []

        if "baron lane" in explicit_positions or "top" in explicit_positions:
            tags.append("top")
        if "jungle" in explicit_positions:
            tags.append("jungle")
        if re.search(r"\bmid\b", explicit_positions):
            tags.append("mid")
        if "dragon lane" in explicit_positions:
            tags.append("support" if "support" in explicit_positions else "adc")
        if "support" in explicit_positions:
            tags.append("support")
        if "bottom champion" in category_text or "marksman champion" in category_text:
            tags.append("adc")
        if "support champion" in category_text or any(
            token in class_text for token in ("support", "enchanter", "catcher", "warden")
        ):
            tags.append("support")

        if not tags:
            if "support champion" in category_text or "healer champion" in category_text:
                tags.append("support")
            if range_type == "Ranged" and physical_hits > magic_hits and "support" not in tags:
                tags.append("adc")
            if range_type == "Ranged" and magic_hits >= physical_hits:
                tags.append("mid")
            if "assassin" in class_text or "stealth champion" in category_text or "energy" in resource:
                tags.append("jungle")
            if attack_range < 300 or any(
                token in class_text
                for token in ("fighter", "juggernaut", "diver", "skirmisher", "tank", "vanguard")
            ):
                tags.append("top")

        if not tags:
            if game == Game.WILD_RIFT:
                tags.append("mid" if range_type == "Ranged" else "top")
            else:
                tags.append("top" if range_type == "Melee" else "mid")

        seen: set[str] = set()
        return [tag for tag in POSITION_ORDER if tag in tags and not (tag in seen or seen.add(tag))]

    def _infer_class_text(self, raw_payload: dict[str, Any]) -> str | None:
        infobox = self._dict_from_unknown(raw_payload.get("infobox"))
        explicit = self._text_or_none(infobox.get("Class(es)"))
        if explicit:
            return explicit

        category_text = " ".join(self._list_of_strings(raw_payload.get("categories"))).lower()
        attack_range = self._parse_first_number(infobox.get("Attack range"))
        hp = self._parse_first_number(infobox.get("HP"))
        ar = self._parse_first_number(infobox.get("AR"))
        mr = self._parse_first_number(infobox.get("MR"))
        magic_hits, physical_hits = self._damage_profile(raw_payload)

        if "support champion" in category_text or "healer champion" in category_text:
            return "Support"
        if attack_range < 300 and hp >= 600 and (ar + mr) >= 60:
            return "Tank"
        if attack_range >= 475 and physical_hits > magic_hits:
            return "Marksman"
        if magic_hits > physical_hits:
            return "Mage"
        if "stealth champion" in category_text:
            return "Assassin"
        if attack_range < 300:
            return "Fighter"
        return None

    def _infer_range_type(self, raw_payload: dict[str, Any]) -> str | None:
        infobox = self._dict_from_unknown(raw_payload.get("infobox"))
        explicit = self._text_or_none(infobox.get("Range type"))
        if explicit:
            lowered = explicit.lower()
            if "ranged" in lowered:
                return "Ranged"
            if "melee" in lowered:
                return "Melee"
            return explicit

        attack_range = self._parse_first_number(infobox.get("Attack range"))
        if attack_range <= 0:
            return None
        return "Ranged" if attack_range >= 300 else "Melee"

    def _infer_resource(self, raw_payload: dict[str, Any]) -> str | None:
        infobox = self._dict_from_unknown(raw_payload.get("infobox"))
        explicit = self._text_or_none(infobox.get("Resource"))
        if explicit:
            return explicit
        category_text = " ".join(self._list_of_strings(raw_payload.get("categories"))).lower()
        if "manaless champion" in category_text:
            return "Manaless"
        if "energy champion" in category_text:
            return "Energy"
        return None

    def _build_ability_summaries(self, raw_payload: dict[str, Any]) -> list[CatalogAbilitySummary]:
        abilities = [
            ability
            for ability in self._list_of_dicts(raw_payload.get("abilities"))
            if self._text_or_none(ability.get("name"))
        ]
        ordered = sorted(abilities, key=lambda ability: self._ability_sort_key(ability.get("skill")))
        return [
            CatalogAbilitySummary(
                skill=self._normalize_skill(ability.get("skill")),
                name=self._text_or_none(ability.get("name")) or "Unknown Ability",
                blurb=self._text_or_none(ability.get("blurb")) or self._text_or_none(ability.get("description")),
                damage_type=self._text_or_none(ability.get("damage_type")),
            )
            for ability in ordered[:5]
        ]

    def _build_champion_summary(
        self,
        *,
        raw_payload: dict[str, Any],
        language: Language,
        position_tags: list[str],
        class_text: str | None,
        range_type: str | None,
        resource: str | None,
    ) -> str | None:
        parts: list[str] = []
        if position_tags:
            separator = " / " if language == Language.ZH_CN else ", "
            position_text = separator.join(
                POSITION_LABELS[tag][language] for tag in position_tags if tag in POSITION_LABELS
            )
            parts.append(
                f"常见位置：{position_text}"
                if language == Language.ZH_CN
                else f"Common roles: {position_text}"
            )
        if class_text:
            parts.append(f"定位：{class_text}" if language == Language.ZH_CN else f"Class: {class_text}")
        if range_type:
            display_range = (
                "远程"
                if range_type == "Ranged" and language == Language.ZH_CN
                else "近战"
                if range_type == "Melee" and language == Language.ZH_CN
                else range_type
            )
            parts.append(
                f"攻击方式：{display_range}"
                if language == Language.ZH_CN
                else f"Range type: {display_range}"
            )
        if resource:
            parts.append(f"资源：{resource}" if language == Language.ZH_CN else f"Resource: {resource}")

        traits = self._extract_trait_hints(raw_payload, language=language)
        if traits:
            trait_text = "、".join(traits) if language == Language.ZH_CN else ", ".join(traits)
            parts.append(f"特性：{trait_text}" if language == Language.ZH_CN else f"Traits: {trait_text}")

        return " · ".join(parts[:5]) if parts else None

    def _extract_trait_hints(self, raw_payload: dict[str, Any], *, language: Language) -> list[str]:
        category_text = " ".join(self._list_of_strings(raw_payload.get("categories"))).lower()
        traits: list[str] = []
        for needle, labels in TRAIT_HINTS:
            if needle in category_text and labels[language] not in traits:
                traits.append(labels[language])
            if len(traits) == 3:
                break
        return traits

    def _build_item_main_attributes(
        self,
        *,
        attributes: dict[str, Any],
        stats: list[str],
        language: Language,
    ) -> list[str]:
        entries: list[str] = []

        for key in ("Cost", "Sell"):
            value = self._text_or_none(attributes.get(key))
            if value:
                entries.append(f"{ITEM_ATTRIBUTE_LABELS[key][language]} {value}")

        entries.extend(stats[:3])

        if not stats:
            for key in ("Cooldown", "Range", "Path", "Slot"):
                value = self._text_or_none(attributes.get(key))
                if value:
                    entries.append(f"{ITEM_ATTRIBUTE_LABELS[key][language]}: {value}")

        deduped: list[str] = []
        for entry in entries:
            if entry and entry not in deduped:
                deduped.append(entry)
        return deduped[:4]

    def _damage_profile(self, raw_payload: dict[str, Any]) -> tuple[int, int]:
        magic_hits = 0
        physical_hits = 0
        for ability in self._list_of_dicts(raw_payload.get("abilities")):
            damage_type = self._text_or_none(ability.get("damage_type"), lowercase=True) or ""
            if damage_type.startswith("magic"):
                magic_hits += 1
            if damage_type.startswith("physical"):
                physical_hits += 1
        return magic_hits, physical_hits

    def _ability_sort_key(self, skill: Any) -> tuple[int, str]:
        normalized = self._normalize_skill(skill) or ""
        order = {"P": 0, "Q": 1, "1": 1, "W": 2, "2": 2, "E": 3, "3": 3, "R": 4, "4": 4}
        return order.get(normalized, 9), normalized

    def _normalize_skill(self, skill: Any) -> str | None:
        text = self._text_or_none(skill, uppercase=True)
        if text == "I":
            return "P"
        return text

    def _parse_first_number(self, value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if not isinstance(value, str):
            return 0.0
        match = re.search(r"\d+(?:\.\d+)?", value.replace(",", ""))
        return float(match.group(0)) if match else 0.0

    def _text_or_none(
        self,
        value: Any,
        *,
        lowercase: bool = False,
        uppercase: bool = False,
    ) -> str | None:
        if not isinstance(value, str):
            return None
        text = value.strip()
        if not text:
            return None
        if lowercase:
            return text.lower()
        if uppercase:
            return text.upper()
        return text

    def _list_of_strings(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]

    def _list_of_dicts(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def _dict_from_unknown(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}
