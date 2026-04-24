import re
from dataclasses import dataclass
from re import Pattern
from typing import Any

from app.catalog.registry import CatalogSnapshot
from app.domain.enums import Game
from app.domain.match_context import ResponsePreferences

SLUG_BOUNDARY_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_`"
)

STRUCTURED_IDENTIFIER_KEYS = {
    "id",
    "ids",
    "slug",
    "slugs",
    "target",
    "source_slug",
    "source_slugs",
    "item_slug",
    "item_slugs",
    "champion_slug",
    "champion_slugs",
    "rune_slug",
    "rune_slugs",
    "enemy_champion_slug",
    "enemy_champion_slugs",
    "current_item_slug",
    "best_item_slug",
    "recommended_item_slug",
    "recommended_build",
    "recommended_build_order",
    "build",
    "runes",
    "recommended_runes",
    "primary",
    "secondary",
}


@dataclass(frozen=True)
class CatalogSlugNameRewriter:
    slug_name_map: dict[str, str]
    backticked_pattern: Pattern[str] | None
    bare_pattern: Pattern[str] | None
    max_slug_length: int

    @classmethod
    def from_snapshot(
        cls,
        *,
        snapshot: CatalogSnapshot,
        game: Game,
        response_preferences: ResponsePreferences,
    ) -> "CatalogSlugNameRewriter":
        catalog = snapshot.catalogs[game]
        entities = [
            *catalog.champions_by_slug.values(),
            *catalog.items_by_slug.values(),
            *catalog.runes_by_slug.values(),
        ]
        slug_name_map = {
            entity.slug.lower(): entity.preferred_name(
                response_preferences.language,
                response_preferences.terminology_style,
            )
            for entity in entities
        }
        if not slug_name_map:
            return cls(
                slug_name_map={},
                backticked_pattern=None,
                bare_pattern=None,
                max_slug_length=0,
            )

        slug_alternation = "|".join(
            re.escape(slug)
            for slug in sorted(slug_name_map, key=lambda value: (-len(value), value))
        )
        return cls(
            slug_name_map=slug_name_map,
            backticked_pattern=re.compile(rf"`({slug_alternation})`", re.IGNORECASE),
            bare_pattern=re.compile(
                rf"(?<![A-Za-z0-9_-])({slug_alternation})(?![A-Za-z0-9_-])",
                re.IGNORECASE,
            ),
            max_slug_length=max(len(slug) for slug in slug_name_map),
        )

    def rewrite_text(self, text: str) -> str:
        if not text or self.backticked_pattern is None or self.bare_pattern is None:
            return text

        def replace(match: re.Match[str]) -> str:
            return self.slug_name_map.get(match.group(1).lower(), match.group(0))

        without_backticked_slugs = self.backticked_pattern.sub(replace, text)
        return self.bare_pattern.sub(replace, without_backticked_slugs)

    def rewrite_result(self, value: Any, *, parent_key: str | None = None) -> Any:
        if isinstance(value, str):
            return value if _is_structured_identifier_key(parent_key) else self.rewrite_text(value)
        if isinstance(value, list):
            if _is_structured_identifier_key(parent_key):
                return value
            return [self.rewrite_result(item, parent_key=parent_key) for item in value]
        if isinstance(value, dict):
            rewritten: dict[str, Any] = {}
            for key, item in value.items():
                key_text = str(key)
                rewritten[key] = (
                    item
                    if _is_structured_identifier_key(key_text)
                    else self.rewrite_result(item, parent_key=key_text)
                )
            return rewritten
        return value

    def create_stream_rewriter(self) -> "CatalogSlugNameStreamRewriter":
        return CatalogSlugNameStreamRewriter(self)


class CatalogSlugNameStreamRewriter:
    def __init__(self, rewriter: CatalogSlugNameRewriter) -> None:
        self.rewriter = rewriter
        self.pending = ""
        self.hold_length = max(rewriter.max_slug_length + 2, 0)

    def push(self, chunk: str) -> str:
        if not chunk:
            return ""
        if self.hold_length == 0:
            return chunk
        self.pending += chunk
        cutoff = len(self.pending) - self.hold_length
        if cutoff <= 0:
            return ""
        cutoff = _rewind_to_slug_boundary(self.pending, cutoff)
        if cutoff <= 0:
            return ""
        ready = self.pending[:cutoff]
        self.pending = self.pending[cutoff:]
        return self.rewriter.rewrite_text(ready)

    def flush(self) -> str:
        if not self.pending:
            return ""
        ready = self.pending
        self.pending = ""
        return self.rewriter.rewrite_text(ready)


def _is_structured_identifier_key(key: str | None) -> bool:
    if key is None:
        return False
    normalized = key.lower()
    return (
        normalized in STRUCTURED_IDENTIFIER_KEYS
        or normalized.endswith("_id")
        or normalized.endswith("_ids")
        or normalized.endswith("_slug")
        or normalized.endswith("_slugs")
    )


def _rewind_to_slug_boundary(text: str, cutoff: int) -> int:
    safe_cutoff = min(max(cutoff, 0), len(text))
    while safe_cutoff > 0 and text[safe_cutoff - 1] in SLUG_BOUNDARY_CHARS:
        safe_cutoff -= 1
    return safe_cutoff
