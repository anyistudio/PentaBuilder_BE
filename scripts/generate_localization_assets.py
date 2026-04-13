import json
from pathlib import Path
from typing import Any

from app.core.config import BASE_DIR
from app.domain.enums import Game
from app.domain.match_context import GAME_SOURCE_DIRECTORY, canonicalize_catalog_slug

ENTITY_FILES = {
    "champions": "champions.json",
    "items": "items.json",
    "runes": "runes.json",
}


def generate_assets(
    *,
    game_data_root: Path,
    output_root: Path,
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    for game in Game:
        game_dir = GAME_SOURCE_DIRECTORY[game]
        source_dir = game_data_root / game_dir
        target_dir = output_root / game_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        for entity_name, filename in ENTITY_FILES.items():
            source_path = source_dir / filename
            if not source_path.exists():
                continue
            payload = json.loads(source_path.read_text(encoding="utf-8"))
            generated = [_build_record(game, entity) for entity in payload]
            output_path = target_dir / f"{entity_name}.zh-CN.json"
            output_path.write_text(
                json.dumps(generated, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )


def _build_record(game: Game, entity: dict[str, Any]) -> dict[str, Any]:
    canonical_slug = canonicalize_catalog_slug(game, entity["slug"])
    english_name = entity.get("name") or canonical_slug
    return {
        "slug": canonical_slug,
        "source_slug": entity["slug"],
        "zh_official_name": "",
        "zh_aliases": [],
        "localized_display_names": {
            "en": english_name,
            "zh-CN": "",
        },
    }


def main() -> None:
    generate_assets(
        game_data_root=BASE_DIR / "game_data",
        output_root=BASE_DIR / "game_localization",
    )


if __name__ == "__main__":
    main()
