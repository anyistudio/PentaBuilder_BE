import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import Game, Language, RunType, TerminologyStyle

BUILD_SLOT_COUNT = 6
MAX_FREE_TEXT_LENGTH = 500
ENVIRONMENT_TAG_WHITELIST = (
    "aram",
    "ranked",
    "normal",
    "tank-heavy",
    "assassin-heavy",
    "healing-heavy",
    "ap-heavy",
    "ad-heavy",
    "cc-heavy",
    "poke-heavy",
    "early-game",
    "late-game",
)
GAME_SLUG_PREFIX = {
    Game.LOL: "lol-",
    Game.WILD_RIFT: "wr-",
}
GAME_SOURCE_DIRECTORY = {
    Game.LOL: "lol",
    Game.WILD_RIFT: "wild_rift",
}
LOOKUP_NORMALIZE_PATTERN = re.compile(r"[^0-9a-z\u4e00-\u9fff]+", re.IGNORECASE)
CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]+")
PROMPT_INJECTION_PATTERN = re.compile(
    "|".join(
        [
            r"ignore\s+(all|any|the)\s+(previous|above)\s+instructions",
            r"system\s+prompt",
            r"developer\s+message",
            r"tool\s+call",
            r"</?(system|developer|assistant|tool)>",
        ]
    ),
    re.IGNORECASE,
)


def normalize_lookup_text(value: str) -> str:
    lowered = value.strip().lower()
    cleaned = LOOKUP_NORMALIZE_PATTERN.sub(" ", lowered)
    return " ".join(cleaned.split())


def sanitize_free_text(value: str) -> str:
    cleaned = CONTROL_CHAR_PATTERN.sub(" ", value)
    cleaned = cleaned.replace("```", " ")
    cleaned = " ".join(cleaned.split())
    return cleaned[:MAX_FREE_TEXT_LENGTH]

def slugify_name(name: str) -> str:
    collapsed = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return collapsed or "unknown"


def has_prompt_injection_markers(value: str) -> bool:
    return bool(PROMPT_INJECTION_PATTERN.search(value))


def canonicalize_catalog_slug(game: Game, slug: str) -> str:
    normalized = slug.strip().lower()
    if game == Game.LOL:
        if normalized.startswith("lol-"):
            return normalized
        if normalized.startswith("wr-") or normalized.startswith("wild-rift-"):
            raise ValueError(f"Slug {slug!r} does not belong to game {game.value}.")
        return (
            normalized
            if normalized.startswith("lol-")
            else f"lol-{normalized.removeprefix('lol-')}"
        )

    if normalized.startswith("wr-"):
        return normalized
    if normalized.startswith("wild-rift-"):
        return "wr-" + normalized.removeprefix("wild-rift-")
    if normalized.startswith("wild_rift-"):
        return "wr-" + normalized.removeprefix("wild_rift-")
    if normalized.startswith("lol-"):
        raise ValueError(f"Slug {slug!r} does not belong to game {game.value}.")
    return f"wr-{normalized}"


def validate_slug_for_game(game: Game, slug: str) -> str:
    canonical_slug = slug.strip().lower()
    if not canonical_slug.startswith(GAME_SLUG_PREFIX[game]):
        raise ValueError(f"Slug {slug!r} does not belong to game {game.value}.")
    return canonical_slug


def _default_build_slots() -> list[str | None]:
    return [None] * BUILD_SLOT_COUNT


class RuneSelection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    primary: list[str] = Field(default_factory=list)
    secondary: list[str] = Field(default_factory=list)


class EnemyChampionContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    champion_slug: str
    build: list[str | None] = Field(default_factory=_default_build_slots)
    runes: RuneSelection = Field(default_factory=RuneSelection)

    @field_validator("build")
    @classmethod
    def validate_build_slots(cls, value: list[str | None]) -> list[str | None]:
        if len(value) != BUILD_SLOT_COUNT:
            raise ValueError(f"Build must contain exactly {BUILD_SLOT_COUNT} slots.")
        return value


class EnvironmentContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tags: list[str] = Field(default_factory=list)
    free_text: str = ""

    @field_validator("free_text")
    @classmethod
    def validate_free_text(cls, value: str) -> str:
        sanitized = sanitize_free_text(value)
        if has_prompt_injection_markers(sanitized):
            raise ValueError("free_text contains unsupported meta-instructions.")
        return sanitized


class ResponsePreferences(BaseModel):
    model_config = ConfigDict(extra="ignore")

    language: Language = Language.ZH_CN
    terminology_style: TerminologyStyle = TerminologyStyle.OFFICIAL


class SessionEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    action: str | None = None
    timestamp: str
    payload: dict[str, Any] = Field(default_factory=dict)


class MatchContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    game: Game
    data_version: str
    own_champion_slug: str
    enemy_team: list[EnemyChampionContext] = Field(default_factory=list)
    own_build: list[str | None] = Field(default_factory=_default_build_slots)
    own_runes: RuneSelection = Field(default_factory=RuneSelection)
    environment: EnvironmentContext = Field(default_factory=EnvironmentContext)

    @field_validator("own_build")
    @classmethod
    def validate_own_build_slots(cls, value: list[str | None]) -> list[str | None]:
        if len(value) != BUILD_SLOT_COUNT:
            raise ValueError(f"Build must contain exactly {BUILD_SLOT_COUNT} slots.")
        return value

    @model_validator(mode="after")
    def validate_context(self) -> "MatchContext":
        self.own_champion_slug = validate_slug_for_game(self.game, self.own_champion_slug)

        if len(self.enemy_team) > 5:
            raise ValueError("enemy_team must contain between 0 and 5 champions.")

        self.own_build = [
            validate_slug_for_game(self.game, slot) if slot else None for slot in self.own_build
        ]
        self.own_runes = self._validate_runes(self.own_runes)
        self.environment.tags = list(canonicalize_environment_tags(self.environment.tags))

        for enemy in self.enemy_team:
            enemy.champion_slug = validate_slug_for_game(self.game, enemy.champion_slug)
            enemy.build = [
                validate_slug_for_game(self.game, slot) if slot else None for slot in enemy.build
            ]
            enemy.runes = self._validate_runes(enemy.runes)

        return self

    def _validate_runes(self, rune_selection: RuneSelection) -> RuneSelection:
        rune_selection.primary = [
            validate_slug_for_game(self.game, rune_slug) for rune_slug in rune_selection.primary
        ]
        rune_selection.secondary = [
            validate_slug_for_game(self.game, rune_slug) for rune_slug in rune_selection.secondary
        ]
        return rune_selection

    @property
    def enemy_champion_slugs_sorted(self) -> tuple[str, ...]:
        return canonicalize_enemy_comp(self.enemy_team)

    @property
    def enemy_comp_key(self) -> str:
        return build_enemy_comp_key(self.enemy_team)

    @property
    def normalized_environment_key(self) -> str:
        return build_normalized_environment_key(self.environment.tags)


def canonicalize_enemy_comp(enemy_team: Sequence[EnemyChampionContext]) -> tuple[str, ...]:
    return tuple(sorted(enemy.champion_slug for enemy in enemy_team))


def build_enemy_comp_key(enemy_team: Sequence[EnemyChampionContext]) -> str:
    normalized = canonicalize_enemy_comp(enemy_team)
    return "|".join(normalized) if normalized else "_none"


def canonicalize_environment_tags(tags: Sequence[str]) -> tuple[str, ...]:
    normalized_tags: set[str] = set()
    for tag in tags:
        normalized = tag.strip().lower()
        if normalized not in ENVIRONMENT_TAG_WHITELIST:
            raise ValueError(f"Unsupported environment tag: {tag!r}")
        normalized_tags.add(normalized)
    return tuple(sorted(normalized_tags))


def build_normalized_environment_key(tags: Sequence[str]) -> str:
    normalized = canonicalize_environment_tags(tags)
    return "|".join(normalized) if normalized else "_none"


def build_semantic_context_hash(
    match_context: MatchContext,
    *,
    operation_context: Mapping[str, Any] | None = None,
) -> str:
    canonical_payload = {
        "game": match_context.game.value,
        "data_version": match_context.data_version,
        "own_champion_slug": match_context.own_champion_slug,
        "enemy_team": [
            {
                "champion_slug": enemy.champion_slug,
                "build": enemy.build,
                "runes": enemy.runes.model_dump(),
            }
            for enemy in sorted(match_context.enemy_team, key=lambda entry: entry.champion_slug)
        ],
        "own_build": match_context.own_build,
        "own_runes": match_context.own_runes.model_dump(),
        "environment_tags": list(canonicalize_environment_tags(match_context.environment.tags)),
        "operation_context": _normalize_operation_context(operation_context or {}),
    }
    return hashlib.sha256(_stable_json_dumps(canonical_payload).encode("utf-8")).hexdigest()


def build_response_variant_hash(
    match_context: MatchContext,
    *,
    run_type: RunType,
    response_preferences: ResponsePreferences,
    operation_context: Mapping[str, Any] | None = None,
) -> str:
    semantic_payload = {
        "semantic_context_hash": build_semantic_context_hash(
            match_context,
            operation_context=operation_context,
        ),
        "run_type": run_type.value,
        "language": response_preferences.language.value,
        "terminology_style": response_preferences.terminology_style.value,
    }
    return hashlib.sha256(_stable_json_dumps(semantic_payload).encode("utf-8")).hexdigest()


def _normalize_operation_context(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _normalize_operation_context(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_normalize_operation_context(item) for item in value]
    return value


def _stable_json_dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
