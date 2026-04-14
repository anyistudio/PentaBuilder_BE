import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ai.providers.base import LLMResult, LLMStreamEvent, LLMUsage
from app.core.config import get_settings
from app.db.base import Base
from app.main import create_app

LOL_BUILD_TEMPLATE = [
    "lol-luden-s-companion",
    "lol-zhonya-s-hourglass",
    "lol-shadowflame",
    "lol-rabadon-s-deathcap",
    "lol-void-staff",
    "lol-banshee-s-veil",
]
LOL_RUNES_TEMPLATE = {
    "primary": [
        "lol-electrocute",
        "lol-sudden-impact",
        "lol-eyeball-collection",
        "lol-ultimate-hunter",
    ],
    "secondary": ["lol-manaflow-band", "lol-transcendence"],
}
WR_BUILD_TEMPLATE = [
    "wr-luden-s-echo",
    "wr-ionian-boots-of-lucidity",
    "wr-infinity-orb",
    "wr-stormsurge",
    "wr-rabadon-s-deathcap",
    "wr-void-staff",
]
WR_RUNES_TEMPLATE = {
    "primary": ["wr-electrocute", "wr-brutal", "wr-bone-plating", "wr-sweet-tooth"],
    "secondary": [],
}


class TestLLMClient:
    provider_name = "google"
    model_name = "gemini-test"

    def generate_text(
        self,
        *,
        prompt: str,
        system_prompt: str | None = None,
        response_mime_type: str | None = None,
        response_schema: dict | None = None,
        temperature: float | None = None,
    ) -> LLMResult:
        combined_prompt = "\n".join(part for part in [system_prompt or "", prompt] if part)
        del response_schema, temperature
        run_type = _extract_run_type(prompt)
        if response_mime_type == "application/json" and "Tool planning mode:" in combined_prompt:
            payload = _build_tool_plan(prompt=prompt, run_type=run_type)
            text = json.dumps(payload, ensure_ascii=False)
        elif response_mime_type == "application/json":
            payload = _build_structured_payload(prompt=prompt, run_type=run_type)
            text = json.dumps(payload, ensure_ascii=False)
        elif "Catalog batch:" in prompt:
            text = "- No obviously outdated entries detected in this batch."
        else:
            text = _build_preview_text(prompt=prompt, run_type=run_type)
        return LLMResult(
            text=text,
            usage=LLMUsage(input_tokens=10, output_tokens=12, latency_ms=5, cost_usd=0.001),
            provider_name=self.provider_name,
            model_name=self.model_name,
        )

    def stream_text(
        self,
        *,
        prompt: str,
        system_prompt: str | None = None,
        response_mime_type: str | None = None,
        response_schema: dict | None = None,
        temperature: float | None = None,
    ):
        del system_prompt, response_mime_type, response_schema, temperature
        text = _build_preview_text(prompt=prompt, run_type=_extract_run_type(prompt))
        for index in range(0, len(text), 8):
            yield LLMStreamEvent(event_type="text_delta", delta=text[index : index + 8])
        yield LLMStreamEvent(
            event_type="completed",
            usage=LLMUsage(input_tokens=8, output_tokens=10, latency_ms=4, cost_usd=0.0005),
            provider_name=self.provider_name,
            model_name=self.model_name,
        )


def _extract_run_type(prompt: str) -> str:
    match = re.search(r"- Run type: ([a-z_]+)", prompt)
    return match.group(1) if match else "recommend_full_build"


def _extract_game(prompt: str) -> str:
    match = re.search(r"- Game: (LoL PC|Wild Rift)", prompt)
    return "wild_rift" if match and match.group(1) == "Wild Rift" else "lol"


def _extract_target_slot(prompt: str) -> int:
    match = re.search(r"- Target slot index: (\d+)", prompt)
    return int(match.group(1)) if match else 0


def _extract_current_build(prompt: str) -> list[str | None]:
    build: list[str | None] = [None] * 6
    for slot, value in re.findall(r"- Slot (\d+): .*?`((?:lol|wr)-[^`]+)`", prompt):
        build[int(slot) - 1] = value
    return build


def _build_template(game: str) -> tuple[list[str], dict[str, list[str]]]:
    if game == "wild_rift":
        return WR_BUILD_TEMPLATE, WR_RUNES_TEMPLATE
    return LOL_BUILD_TEMPLATE, LOL_RUNES_TEMPLATE


def _fill_build(current_build: list[str | None], template: list[str]) -> list[str]:
    return [slot or template[index] for index, slot in enumerate(current_build)]


def _build_preview_text(*, prompt: str, run_type: str) -> str:
    game = _extract_game(prompt)
    build_template, _ = _build_template(game)
    slot_index = _extract_target_slot(prompt)
    current_build = _extract_current_build(prompt)
    if run_type == "explain_slot":
        current_item = current_build[slot_index]
        best_item = build_template[slot_index]
        if current_item == best_item:
            return "当前这个位置已经合理，先保证整体节奏继续往后做。"
        return "这个位置更推荐补防守与节奏兼顾的装备，能更稳地接中期团战。"
    if run_type == "chat_followup":
        return "这局优先级更高的是把当前核心节奏做出来，然后再根据对面威胁补针对装。"
    return "这件装备更符合当前对局。"


def _build_structured_payload(*, prompt: str, run_type: str) -> dict:
    game = _extract_game(prompt)
    build_template, runes_template = _build_template(game)
    current_build = _extract_current_build(prompt)
    filled_build = _fill_build(current_build, build_template)
    slot_index = _extract_target_slot(prompt)

    if run_type == "evaluate_build":
        return {
            "score": 84,
            "summary": "当前出装方向基本正确，但第二件之后需要补更多容错。",
            "strengths": ["前两件节奏顺", "爆发路径明确"],
            "weaknesses": ["中期自保略少", "面对刺客时风险偏高"],
            "recommended_build": filled_build,
            "recommended_runes": runes_template,
        }
    if run_type == "recommend_slot":
        return {
            "slot_index": slot_index,
            "recommended_item_slug": build_template[slot_index],
            "summary": "这个槽位先补更稳的关键装最合适。",
            "reasoning": ["对面爆发压力高", "当前 build 需要更平衡的中期战斗力"],
            "alternatives": [
                {
                    "item_slug": build_template[min(slot_index + 1, 5)],
                    "reason": "如果你想更偏伤害，也可以往后顺延一件输出装。",
                }
            ],
        }
    if run_type == "recommend_full_build":
        return {
            "recommended_build_order": filled_build,
            "recommended_runes": runes_template,
            "summary": "这套 build 兼顾了当前对局的爆发、成型节奏和容错。",
            "slot_notes": [
                {"slot_index": 0, "text": "第一件先做核心起手装。"},
                {"slot_index": 1, "text": "第二件优先补更稳的中期关键装。"},
            ],
        }
    if run_type == "explain_slot":
        current_item = current_build[slot_index]
        best_item = build_template[slot_index]
        return {
            "slot_index": slot_index,
            "current_item_slug": current_item,
            "is_current_choice_good": current_item == best_item,
            "best_item_slug": best_item,
            "summary": "当前这个位置需要更稳的选择来保证中期团战。",
            "why_current_choice": "现在的选择不是完全不能出，但对当前压力点的覆盖不够好。",
            "why_best_choice": "这个替代项更适合当前对局节奏，也更能补足生存和关键回合价值。",
            "linked_adjustments": [
                {"target": f"slot:{min(slot_index + 1, 5)}", "text": "后续槽位可以再补纯输出。"}
            ],
        }
    if run_type == "compare_builds":
        return {
            "winner": "build_a",
            "score_delta": 8,
            "summary": "A 在当前高压对局里更稳。",
            "key_differences": [
                {"target": "slot:1", "reason": "A 的第二件更早补到了关键容错。"}
            ],
            "when_build_b_is_better": ["如果对面爆发没那么高，B 的纯输出路线会更赚。"],
        }
    return {
        "summary": "当前更重要的是把核心节奏做顺。",
        "answer": "当前更重要的是把核心节奏做顺，再根据对面威胁补针对装。",
        "followup_suggestions": ["如果对面双 AP 呢？", "那第三件应该怎么补？"],
    }


def _build_tool_plan(*, prompt: str, run_type: str) -> dict:
    if "## Tool Facts" in prompt:
        return {"tool_calls": [], "done": True}
    if run_type == "explain_slot":
        return {
            "tool_calls": [
                {
                    "tool_name": "search_catalog",
                    "arguments": {
                        "entity_type": "item",
                        "query": "defensive mage item against burst",
                        "limit": 4,
                    },
                }
            ],
            "done": False,
        }
    if run_type == "chat_followup":
        return {
            "tool_calls": [
                {
                    "tool_name": "search_catalog",
                    "arguments": {
                        "entity_type": "item",
                        "query": "burst defense mage item",
                        "limit": 3,
                    },
                }
            ],
            "done": False,
        }
    return {"tool_calls": [], "done": True}


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def build_configured_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    database_path = tmp_path / "app.db"
    localization_root = tmp_path / "game_localization"
    (localization_root / "lol").mkdir(parents=True)
    (localization_root / "wild_rift").mkdir(parents=True)
    (localization_root / "lol" / "champions.zh-CN.json").write_text(
        """
        [
          {"slug": "lol-ahri", "zh_official_name": "阿狸", "zh_aliases": ["狐狸"]},
          {"slug": "lol-zed", "zh_official_name": "劫", "zh_aliases": []}
        ]
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("GAME_DATA_SOURCE", "local")
    monkeypatch.setenv(
        "GAME_DATA_LOCAL_ROOT",
        "/Users/jialinliu/Dev/PentaBuilder/PentaBuilder_BE/game_data",
    )
    monkeypatch.setenv("GAME_LOCALIZATION_ROOT", str(localization_root))
    monkeypatch.setenv(
        "BENCHMARK_LOCAL_ROOT",
        "/Users/jialinliu/Dev/PentaBuilder/PentaBuilder_BE/benchmark_datasets",
    )
    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    monkeypatch.setenv("JWT_SIGNING_KEY", "test-signing-key-with-32-plus-bytes")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setattr(
        "app.services.ai_run_service.create_llm_client",
        lambda **kwargs: TestLLMClient(),
    )
    monkeypatch.setattr(
        "app.jobs.calibrations.create_llm_client",
        lambda **kwargs: TestLLMClient(),
    )
    get_settings.cache_clear()

    app = create_app()
    engine = app.state.session_factory.kw["bind"]
    Base.metadata.create_all(bind=engine)
    return app


@pytest.fixture
def configured_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    return build_configured_app(monkeypatch, tmp_path)


@pytest.fixture
def configured_client(configured_app) -> Iterator[TestClient]:
    with TestClient(configured_app) as test_client:
        yield test_client
