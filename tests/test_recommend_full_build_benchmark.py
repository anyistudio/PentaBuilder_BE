import json

from app.core.errors import ApiError
from app.domain.enums import RunType
from app.evals.models import EvalModelRef
from app.evals.recommend_full_build_benchmark import (
    _build_failure_error_payload,
    build_recommend_full_build_benchmark_cases,
    build_selected_model_price_table,
    filter_model_refs,
    load_model_refs_from_env_file,
    render_recommend_full_build_benchmark_markdown,
    run_recommend_full_build_benchmark,
    sync_model_price_table,
)


def test_build_recommend_full_build_benchmark_cases_has_five_distinct_item_counts() -> None:
    cases = build_recommend_full_build_benchmark_cases("full-20260411")

    assert len(cases) == 5
    assert all(case.feature == RunType.RECOMMEND_FULL_BUILD for case in cases)
    assert len({case.context.own_champion_slug for case in cases}) == 5
    assert [sum(1 for slot in case.context.own_build if slot) for case in cases] == [0, 1, 2, 3, 4]


def test_load_model_refs_from_env_file_supports_all_model_key(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        'ALL_MODEL="google:gemini-3-flash-preview,openai:gpt-5.4-mini"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("ALL_MODELS", "")

    refs = load_model_refs_from_env_file(env_path=env_path)

    assert [ref.label for ref in refs] == [
        "google/gemini-3-flash-preview",
        "openai/gpt-5.4-mini",
    ]


def test_sync_model_price_table_creates_blank_entries(tmp_path) -> None:
    price_file_path = tmp_path / "prices.json"

    payload = sync_model_price_table(
        model_refs=[
            EvalModelRef(provider_name="google", model_name="gemini-3-flash-preview"),
            EvalModelRef(provider_name="openai", model_name="gpt-5.4-mini"),
        ],
        price_file_path=price_file_path,
    )

    assert price_file_path.exists()
    assert (
        payload["models"]["google/gemini-3-flash-preview"]["input_price_per_1m_tokens_usd"]
        is None
    )
    assert payload["models"]["openai/gpt-5.4-mini"]["output_price_per_1m_tokens_usd"] is None


def test_sync_model_price_table_preserves_existing_models_when_running_subset(tmp_path) -> None:
    price_file_path = tmp_path / "prices.json"
    price_file_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-04-19T00:00:00+00:00",
                "currency": "USD",
                "price_unit": "per_1m_tokens",
                "models": {
                    "google/gemini-3-flash-preview": {
                        "provider_name": "google",
                        "model_name": "gemini-3-flash-preview",
                        "input_price_per_1m_tokens_usd": 0.3,
                        "output_price_per_1m_tokens_usd": 2.5,
                        "notes": "saved",
                    },
                    "openai/gpt-5.4": {
                        "provider_name": "openai",
                        "model_name": "gpt-5.4",
                        "input_price_per_1m_tokens_usd": 2.5,
                        "output_price_per_1m_tokens_usd": 15.0,
                        "notes": "saved",
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = sync_model_price_table(
        model_refs=[EvalModelRef(provider_name="google", model_name="gemini-3-flash-preview")],
        price_file_path=price_file_path,
    )

    assert set(payload["models"]) == {
        "google/gemini-3-flash-preview",
        "openai/gpt-5.4",
    }
    assert payload["models"]["openai/gpt-5.4"]["input_price_per_1m_tokens_usd"] == 2.5
    assert payload["models"]["openai/gpt-5.4"]["output_price_per_1m_tokens_usd"] == 15.0


def test_build_selected_model_price_table_returns_only_requested_models() -> None:
    payload = build_selected_model_price_table(
        model_refs=[EvalModelRef(provider_name="openai", model_name="gpt-5.4")],
        price_table={
            "generated_at": "2026-04-19T00:00:00+00:00",
            "currency": "USD",
            "price_unit": "per_1m_tokens",
            "models": {
                "google/gemini-3-flash-preview": {
                    "provider_name": "google",
                    "model_name": "gemini-3-flash-preview",
                    "input_price_per_1m_tokens_usd": 0.3,
                    "output_price_per_1m_tokens_usd": 2.5,
                    "notes": "",
                },
                "openai/gpt-5.4": {
                    "provider_name": "openai",
                    "model_name": "gpt-5.4",
                    "input_price_per_1m_tokens_usd": 2.5,
                    "output_price_per_1m_tokens_usd": 15.0,
                    "notes": "current",
                },
            },
        },
    )

    assert list(payload["models"]) == ["openai/gpt-5.4"]
    assert payload["models"]["openai/gpt-5.4"]["input_price_per_1m_tokens_usd"] == 2.5
    assert payload["models"]["openai/gpt-5.4"]["notes"] == "current"


def test_filter_model_refs_by_provider_supports_case_and_csv() -> None:
    refs = filter_model_refs(
        model_refs=[
            EvalModelRef(provider_name="google", model_name="gemini-3-flash-preview"),
            EvalModelRef(provider_name="openai", model_name="gpt-5.4-mini"),
            EvalModelRef(provider_name="anthropic", model_name="claude-sonnet"),
        ],
        providers=["Google, openai"],
    )

    assert [ref.label for ref in refs] == [
        "google/gemini-3-flash-preview",
        "openai/gpt-5.4-mini",
    ]


def test_filter_model_refs_by_model_supports_name_label_and_env_style() -> None:
    refs = filter_model_refs(
        model_refs=[
            EvalModelRef(provider_name="google", model_name="gemini-3-flash-preview"),
            EvalModelRef(provider_name="google", model_name="gemini-2.5-flash"),
            EvalModelRef(provider_name="openai", model_name="gpt-5.4-mini"),
        ],
        models=["Gemini-2.5-Flash, openai/gpt-5.4-mini, google:gemini-3-flash-preview"],
    )

    assert [ref.label for ref in refs] == [
        "google/gemini-3-flash-preview",
        "google/gemini-2.5-flash",
        "openai/gpt-5.4-mini",
    ]


def test_build_failure_error_payload_includes_detailed_issues() -> None:
    exc = ApiError(
        "Invalid AI result.",
        code="provider_error",
        status_code=502,
        details={
            "issues": [
                {
                    "loc": ["recommended_runes", "primary"],
                    "msg": "List should have at least 4 items",
                },
                {"loc": ["summary"], "msg": "Field required"},
            ]
        },
    )

    payload = _build_failure_error_payload(exc=exc, run=None)

    assert payload["error"] == "Invalid AI result."
    assert (
        payload["error_summary"]
        == "recommended_runes.primary: List should have at least 4 items"
    )
    assert payload["error_code"] == "provider_error"
    assert payload["error_status_code"] == 502
    assert payload["error_issues"] == [
        "recommended_runes.primary: List should have at least 4 items",
        "summary: Field required",
    ]


def test_render_markdown_includes_detailed_failure_reason() -> None:
    markdown = render_recommend_full_build_benchmark_markdown(
        {
            "generated_at": "2026-04-19T05:13:31.145932+00:00",
            "data_version": "full-20260411",
            "models": [{"label": "google/test-model"}],
            "case_count": 1,
            "price_file_path": "/tmp/prices.json",
            "summary": {
                "model_summaries": [
                    {
                        "model_label": "google/test-model",
                        "completed_count": 0,
                        "total_count": 1,
                        "avg_total_elapsed_ms": None,
                        "avg_run_latency_ms": None,
                        "avg_tokens_input": None,
                        "avg_tokens_output": None,
                        "provider_cost_total_usd": None,
                        "estimated_cost_total_usd": None,
                    }
                ]
            },
            "results": [
                {
                    "case_key": "case-1",
                    "model_label": "google/test-model",
                    "description": "failed case",
                    "owned_item_count": 2,
                    "status": "failed",
                    "total_elapsed_ms": 1234,
                    "run_latency_ms": None,
                    "tokens_input": None,
                    "tokens_output": None,
                    "provider_cost_usd": None,
                    "estimated_cost_from_price_table_usd": None,
                    "generated_content": None,
                    "explanation": "",
                    "error": "Invalid AI result.",
                    "error_summary": "recommended_runes.primary: List should have at least 4 items",
                    "error_code": "provider_error",
                    "error_status_code": 502,
                    "error_issues": [
                        "recommended_runes.primary: List should have at least 4 items",
                    ],
                    "error_details": {
                        "issues": [
                            {
                                "loc": ["recommended_runes", "primary"],
                                "msg": "List should have at least 4 items",
                            }
                        ]
                    },
                    "run_error_code": "provider_error",
                    "run_error_message": "Invalid AI result.",
                }
            ],
        }
    )

    assert "**Failure Details**" in markdown
    assert (
        "Failure summary: `recommended_runes.primary: List should have at least 4 items`"
        in markdown
    )
    assert "Error code: `provider_error`" in markdown
    assert "Status code: `502`" in markdown
    assert "recommended_runes.primary: List should have at least 4 items" in markdown
    assert "**Raw Error Details**" in markdown


def test_run_recommend_full_build_benchmark_writes_artifacts(configured_app, tmp_path) -> None:
    with configured_app.state.session_factory() as session:
        active_version = configured_app.state.data_version_service.get_active_version(session)

    bundle = run_recommend_full_build_benchmark(
        session_factory=configured_app.state.session_factory,
        ai_run_service=configured_app.state.ai_run_service,
        data_version=active_version.data_version,
        model_refs=[EvalModelRef(provider_name="google", model_name="gemini-test")],
        output_dir=tmp_path / "benchmark-output",
        price_file_path=tmp_path / "prices.json",
        show_progress=False,
        show_failure_logs=False,
    )

    assert len(bundle["report"]["results"]) == 5
    assert bundle["report"]["summary"]["model_summaries"][0]["model_label"] == "google/gemini-test"
    assert (tmp_path / "benchmark-output" / "report.json").exists()
    assert (tmp_path / "benchmark-output" / "report.md").exists()
    assert (tmp_path / "benchmark-output" / "cases.json").exists()
