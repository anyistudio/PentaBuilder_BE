from app.ai.orchestration.prompt_builder import build_prompt_package
from app.ai.orchestration.result_contracts import get_result_response_schema
from app.ai.orchestration.tool_plans import get_tool_plan_response_schema
from app.domain.enums import RunType
from app.domain.match_context import MatchContext, ResponsePreferences


def _load_snapshot(configured_app):
    session = configured_app.state.session_factory()
    version = configured_app.state.data_version_service.get_active_version(session)
    snapshot = configured_app.state.game_data_registry.get_or_load(
        data_version=version.data_version,
        source_root=version.source_root,
    )
    session.close()
    return snapshot


def test_game_status_generation_prompt_skips_tool_rules_and_uses_compact_appendix(
    configured_app,
) -> None:
    snapshot = _load_snapshot(configured_app)
    context = MatchContext(
        game="wild_rift",
        data_version=snapshot.data_version,
        own_champion_slug="wr-lucian",
        enemy_team=[
            {
                "champion_slug": "wr-jhin",
                "build": ["wr-essence-reaver", None, None, None, None, None, None],
                "runes": {"primary": ["wr-conqueror"], "secondary": []},
            }
        ],
        own_build=["wr-dead-man-s-plate", None, None, None, None, None, None],
        own_runes={"primary": ["wr-conqueror"], "secondary": []},
        environment={"tags": ["aram"], "free_text": ""},
    )

    prompt = build_prompt_package(
        run_type=RunType.GAME_STATUS,
        context=context,
        response_preferences=ResponsePreferences(language="zh-CN", terminology_style="official"),
        operation_context={},
        baseline=None,
        reference_summary=None,
        calibration_summary=None,
        session_memory_summary=None,
        reply_to_run_summary=None,
        snapshot=snapshot,
    )

    assert "Tool rules:" not in prompt.system_prompt
    assert "Tool planning rules:" not in prompt.system_prompt
    assert "Ability hooks:" not in prompt.user_prompt
    assert "display_names" not in prompt.user_prompt
    assert "english_name" not in prompt.user_prompt
    assert '"aliases"' not in prompt.user_prompt
    assert "similar_items" not in prompt.user_prompt
    assert "## Detailed Parameter Appendix" in prompt.user_prompt


def test_recommend_full_build_prompt_keeps_wild_rift_contract_in_task_context_once(
    configured_app,
) -> None:
    snapshot = _load_snapshot(configured_app)
    context = MatchContext(
        game="wild_rift",
        data_version=snapshot.data_version,
        own_champion_slug="wr-jhin",
        enemy_team=[
            {
                "champion_slug": "wr-lucian",
                "build": [None, None, None, None, None, None, None],
                "runes": {"primary": [], "secondary": []},
            }
        ],
        own_build=["wr-essence-reaver", None, None, None, None, None, None],
        own_runes={"primary": [], "secondary": []},
        environment={"tags": ["aram"], "free_text": ""},
    )

    prompt = build_prompt_package(
        run_type=RunType.RECOMMEND_FULL_BUILD,
        context=context,
        response_preferences=ResponsePreferences(language="zh-CN", terminology_style="official"),
        operation_context={},
        baseline=None,
        reference_summary=None,
        calibration_summary=None,
        session_memory_summary=None,
        reply_to_run_summary=None,
        snapshot=snapshot,
        output_mode="tool_plan",
    )

    assert prompt.system_prompt.count("Return exactly 7 steps.") == 0
    assert prompt.user_prompt.count("Build order contract: return exactly 7 steps.") == 1
    assert prompt.user_prompt.count("The boots step must appear before the enchant step.") == 1
    assert "Keep `recommended_runes` empty for now" in prompt.system_prompt
    assert "`list_item_ids`" in prompt.user_prompt


def test_prioritized_workflow_schemas_are_compact(configured_app) -> None:
    snapshot = _load_snapshot(configured_app)
    context = MatchContext(
        game="wild_rift",
        data_version=snapshot.data_version,
        own_champion_slug="wr-lucian",
        enemy_team=[],
        own_build=[None, None, None, None, None, None, None],
        own_runes={"primary": [], "secondary": []},
        environment={"tags": [], "free_text": ""},
    )

    recommend_schema = get_result_response_schema(
        run_type=RunType.RECOMMEND_FULL_BUILD,
        context=context,
    )
    game_status_schema = get_result_response_schema(
        run_type=RunType.GAME_STATUS,
        context=context,
    )
    tool_plan_schema = get_tool_plan_response_schema()

    assert (
        recommend_schema["properties"]["recommended_build_order"]["description"]
        == (
            "Ordered purchase path using canonical item slugs. "
            "Follow the current game's step count and boots/enchant contract "
            "from the prompt."
        )
    )
    assert (
        recommend_schema["properties"]["recommended_runes"]["description"]
        == (
            "Temporary placeholder. Leave both arrays empty for this workflow: "
            "`primary=[]`, `secondary=[]`."
        )
    )
    assert "recommended_runes" in recommend_schema["required"]
    assert (
        game_status_schema["properties"]["assumed_match_duration_minutes"]["description"]
        == "15 for ARAM, otherwise 30."
    )
    assert (
        tool_plan_schema["properties"]["reasoning_summary"]["description"]
        == "Short user-visible note about the missing facts and next action."
    )
