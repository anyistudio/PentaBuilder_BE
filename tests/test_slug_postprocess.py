from app.ai.orchestration.slug_postprocess import CatalogSlugNameRewriter
from app.catalog.registry import CatalogEntity, CatalogSnapshot, GameCatalog
from app.domain.enums import Game, Language, TerminologyStyle
from app.domain.match_context import ResponsePreferences


def _snapshot() -> CatalogSnapshot:
    trinity_force = CatalogEntity(
        entity_type="item",
        game=Game.WILD_RIFT,
        slug="wr-trinity-force",
        source_slug="trinity-force",
        english_name="Trinity Force",
        icon_url=None,
        raw_payload={},
        display_names={
            Language.EN.value: "Trinity Force",
            Language.ZH_CN.value: "三相之力",
        },
        aliases=["三相"],
    )
    volibear = CatalogEntity(
        entity_type="champion",
        game=Game.WILD_RIFT,
        slug="wr-volibear",
        source_slug="volibear",
        english_name="Volibear",
        icon_url=None,
        raw_payload={},
        display_names={
            Language.EN.value: "Volibear",
            Language.ZH_CN.value: "不灭狂雷",
        },
        aliases=[],
    )
    catalog = GameCatalog(
        champions_by_slug={volibear.slug: volibear},
        items_by_slug={trinity_force.slug: trinity_force},
        runes_by_slug={},
        search_index=[volibear, trinity_force],
    )
    return CatalogSnapshot(
        data_version="test-version",
        source_root="test-root",
        manifest={},
        catalogs={Game.WILD_RIFT: catalog},
    )


def test_rewrite_result_replaces_slugs_in_user_visible_text() -> None:
    rewriter = CatalogSlugNameRewriter.from_snapshot(
        snapshot=_snapshot(),
        game=Game.WILD_RIFT,
        response_preferences=ResponsePreferences(
            language=Language.ZH_CN,
            terminology_style=TerminologyStyle.OFFICIAL,
        ),
    )

    result = rewriter.rewrite_result(
        {
            "recommended_build_order": ["wr-trinity-force", None],
            "recommended_item_slug": "wr-trinity-force",
            "summary": (
                "先做`wr-trinity-force`，最契合wr-volibear当前单人对局的前中期强势点。"
            ),
            "slot_notes": [
                {
                    "slot_index": 0,
                    "text": "wr-trinity-force 能补足移速和持续输出。",
                }
            ],
        }
    )

    assert result["recommended_build_order"] == ["wr-trinity-force", None]
    assert result["recommended_item_slug"] == "wr-trinity-force"
    assert result["summary"] == "先做三相之力，最契合不灭狂雷当前单人对局的前中期强势点。"
    assert result["slot_notes"][0]["text"] == "三相之力 能补足移速和持续输出。"


def test_rewrite_result_uses_requested_language_and_terminology_style() -> None:
    snapshot = _snapshot()

    english_rewriter = CatalogSlugNameRewriter.from_snapshot(
        snapshot=snapshot,
        game=Game.WILD_RIFT,
        response_preferences=ResponsePreferences(
            language=Language.EN,
            terminology_style=TerminologyStyle.OFFICIAL,
        ),
    )
    slang_rewriter = CatalogSlugNameRewriter.from_snapshot(
        snapshot=snapshot,
        game=Game.WILD_RIFT,
        response_preferences=ResponsePreferences(
            language=Language.ZH_CN,
            terminology_style=TerminologyStyle.SLANG_ZH,
        ),
    )

    assert english_rewriter.rewrite_text("Buy wr-trinity-force first.") == (
        "Buy Trinity Force first."
    )
    assert slang_rewriter.rewrite_text("先做wr-trinity-force。") == "先做三相。"


def test_stream_rewriter_handles_slug_split_across_chunks() -> None:
    rewriter = CatalogSlugNameRewriter.from_snapshot(
        snapshot=_snapshot(),
        game=Game.WILD_RIFT,
        response_preferences=ResponsePreferences(
            language=Language.ZH_CN,
            terminology_style=TerminologyStyle.OFFICIAL,
        ),
    )
    stream = rewriter.create_stream_rewriter()

    chunks = [
        stream.push("先做`wr-tr"),
        stream.push("inity-force`，再围绕wr-vol"),
        stream.push("ibear的追击能力继续补装。"),
        stream.flush(),
    ]

    assert "".join(chunks) == "先做三相之力，再围绕不灭狂雷的追击能力继续补装。"
