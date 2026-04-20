import json

from app.ai.graphs.nodes import (
    _call_tool_plan_model,
    _sanitize_tool_call,
)
from app.ai.orchestration.tool_plans import validate_tool_plan
from app.ai.providers.base import LLMResult, LLMUsage
from app.domain.match_context import MatchContext


def _load_snapshot(configured_app):
    session = configured_app.state.session_factory()
    version = configured_app.state.data_version_service.get_active_version(session)
    snapshot = configured_app.state.game_data_registry.get_or_load(
        data_version=version.data_version,
        source_root=version.source_root,
    )
    session.close()
    return snapshot


def test_list_catalog_candidates_sanitizer_fills_game_and_maps_tags_to_keywords(
    configured_app,
) -> None:
    snapshot = _load_snapshot(configured_app)
    context = MatchContext(
        game="wild_rift",
        data_version=snapshot.data_version,
        own_champion_slug="wr-heimerdinger",
        enemy_team=[],
        own_build=[None, None, None, None, None, None, None],
        own_runes={"primary": [], "secondary": []},
        environment={"tags": ["aram"], "free_text": ""},
    )

    sanitized = _sanitize_tool_call(
        tool_call={
            "tool_name": "list_catalog_candidates",
            "arguments": {
                "entity_type": "item",
                "tags": ["magic"],
            },
        },
        context=context,
        snapshot=snapshot,
    )

    assert sanitized == {
        "tool_name": "list_catalog_candidates",
        "arguments": {
            "game": "wild_rift",
            "entity_type": "item",
            "filters": {
                "keywords": ["magic"],
            },
        },
    }


def test_resolve_catalog_slug_sanitizer_accepts_nested_tags_without_explicit_game(
    configured_app,
) -> None:
    snapshot = _load_snapshot(configured_app)
    context = MatchContext(
        game="wild_rift",
        data_version=snapshot.data_version,
        own_champion_slug="wr-heimerdinger",
        enemy_team=[],
        own_build=[None, None, None, None, None, None, None],
        own_runes={"primary": [], "secondary": []},
        environment={"tags": ["aram"], "free_text": ""},
    )

    sanitized = _sanitize_tool_call(
        tool_call={
            "tool_name": "resolve_catalog_slug",
            "arguments": {
                "entity_type": "rune",
                "raw_name": "法力流系带",
                "filters": {
                    "tags": ["mana"],
                },
            },
        },
        context=context,
        snapshot=snapshot,
    )

    assert sanitized == {
        "tool_name": "resolve_catalog_slug",
        "arguments": {
            "game": "wild_rift",
            "entity_type": "rune",
            "raw_name": "法力流系带",
            "filters": {
                "keywords": ["mana"],
            },
        },
    }


def test_list_item_ids_sanitizer_accepts_kind_alias_without_explicit_game(
    configured_app,
) -> None:
    snapshot = _load_snapshot(configured_app)
    context = MatchContext(
        game="wild_rift",
        data_version=snapshot.data_version,
        own_champion_slug="wr-heimerdinger",
        enemy_team=[],
        own_build=[None, None, None, None, None, None, None],
        own_runes={"primary": [], "secondary": []},
        environment={"tags": ["aram"], "free_text": ""},
    )

    sanitized = _sanitize_tool_call(
        tool_call={
            "tool_name": "list_item_ids",
            "arguments": {
                "kind": "magic",
            },
        },
        context=context,
        snapshot=snapshot,
    )

    assert sanitized == {
        "tool_name": "list_item_ids",
        "arguments": {
            "game": "wild_rift",
            "category": "magic",
        },
    }


def test_validate_tool_plan_accepts_tool_and_args_aliases() -> None:
    plan = validate_tool_plan(
        {
            "reasoning_summary": "先查真实条目。",
            "done": False,
            "tool_calls": [
                {
                    "tool": "search_catalog",
                    "args": {
                        "entity_type": "item",
                        "query": "破败王者之刃 电刀",
                    },
                }
            ],
        }
    )

    assert plan.done is False
    assert plan.tool_calls[0].tool_name == "search_catalog"
    assert plan.tool_calls[0].arguments == {
        "entity_type": "item",
        "query": "破败王者之刃 电刀",
    }


class _ConcatenatedToolPlanLLMClient:
    provider_name = "openai"
    model_name = "gpt-5.4"

    def generate_text(
        self,
        *,
        prompt: str,
        system_prompt: str | None = None,
        response_mime_type: str | None = None,
        response_schema: dict | None = None,
        temperature: float | None = None,
    ) -> LLMResult:
        del prompt, system_prompt, response_mime_type, response_schema, temperature
        first_object = {
            "done": False,
            "reasoning_summary": "先确认真实条目。",
            "tool_calls": [
                {
                    "tool": "search_catalog",
                    "args": {
                        "entity_type": "item",
                        "query": "破败王者之刃 电刀 水银之靴",
                    },
                }
            ],
        }
        second_object = {
            "done": True,
            "reasoning_summary": "已经直接得出最终答案。",
            "recommended_build_order": ["wr-blade-of-the-ruined-king"],
        }
        text = json.dumps(first_object, ensure_ascii=False) + json.dumps(
            second_object, ensure_ascii=False
        )
        return LLMResult(
            text=text,
            usage=LLMUsage(input_tokens=10, output_tokens=20, latency_ms=5, cost_usd=0.001),
            provider_name=self.provider_name,
            model_name=self.model_name,
        )


def test_call_tool_plan_model_uses_first_valid_candidate_from_concatenated_json() -> None:
    tool_plan, usage_payload = _call_tool_plan_model(
        llm_client=_ConcatenatedToolPlanLLMClient(),
        prompt="test prompt",
        system_prompt="test system prompt",
        response_schema={},
        temperature=0.05,
        error_message="Model returned an invalid tool plan.",
        graph_node="tool_select",
    )

    assert tool_plan.done is False
    assert tool_plan.reasoning_summary == "先确认真实条目。"
    assert len(tool_plan.tool_calls) == 1
    assert tool_plan.tool_calls[0].tool_name == "search_catalog"
    assert usage_payload["provider_name"] == "openai"
