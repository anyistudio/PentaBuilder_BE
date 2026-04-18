from collections import Counter

from app.ai.providers.factory import create_llm_client
from app.core.config import get_settings
from app.domain.enums import RunType
from app.evals.workflow_eval import (
    EvalModelRef,
    build_eval_cases,
    default_model_refs,
    run_local_workflow_eval,
)


def test_build_eval_cases_produces_five_examples_per_feature():
    cases = build_eval_cases("full-20260411")

    assert len(cases) == len(RunType) * 5

    counts = Counter(case.feature for case in cases)
    for run_type in RunType:
        assert counts[run_type] == 5

    chat_cases = [case for case in cases if case.feature == RunType.CHAT_FOLLOWUP]
    assert len(chat_cases) == 5
    assert all(case.reply_seed is not None for case in chat_cases)


def test_default_model_refs_uses_all_models_when_configured(monkeypatch):
    monkeypatch.setenv(
        "ALL_MODELS",
        (
            "google:gemini-3.1-pro-preview,"
            "google:gemini-3-flash-preview,"
            "openai:gpt-5.4,"
            "openai:gpt-5.4-mini"
        ),
    )
    settings = get_settings()

    refs = default_model_refs(settings)
    labels = [ref.label for ref in refs]

    assert labels == [
        "google/gemini-3.1-pro-preview",
        "google/gemini-3-flash-preview",
        "openai/gpt-5.4",
        "openai/gpt-5.4-mini",
    ]


def test_default_model_refs_falls_back_when_all_models_is_empty(monkeypatch):
    monkeypatch.setenv("ALL_MODELS", "")
    monkeypatch.setenv("PRIMARY_REASONING_PROVIDER", "google")
    monkeypatch.setenv("PRIMARY_REASONING_MODEL", "gemini-primary")
    monkeypatch.setenv("FAST_REASONING_PROVIDER", "google")
    monkeypatch.setenv("FAST_REASONING_MODEL", "gemini-primary")
    monkeypatch.setenv("GOOGLE_API_KEY", "google-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    settings = get_settings()

    refs = default_model_refs(settings)
    labels = [ref.label for ref in refs]

    assert labels == [
        "google/gemini-primary",
        "openai/gpt-4.1",
        "openai/gpt-4.1-mini",
    ]


def test_create_llm_client_supports_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    settings = get_settings()

    client = create_llm_client(
        settings=settings,
        provider_name="openai",
        model_name="gpt-4.1-mini",
    )

    assert client is not None
    assert client.provider_name == "openai"
    assert client.model_name == "gpt-4.1-mini"


def test_run_local_workflow_eval_writes_markdown_report(configured_app, tmp_path):
    with configured_app.state.session_factory() as session:
        active_version = configured_app.state.data_version_service.get_active_version(session)

    output_path = tmp_path / "ai-workflow-eval.md"
    report = run_local_workflow_eval(
        session_factory=configured_app.state.session_factory,
        ai_run_service=configured_app.state.ai_run_service,
        data_version=active_version.data_version,
        model_refs=[EvalModelRef(provider_name="google", model_name="gemini-test")],
        output_path=output_path,
        feature_filter={RunType.RECOMMEND_SLOT},
    )

    assert output_path.exists()
    body = output_path.read_text(encoding="utf-8")
    assert "# AI Workflow Evaluation Report" in body
    assert "## Average Latency by Feature and Model" in body
    assert "`recommend_slot`" in body
    assert len(report["results"]) == 5
    assert report["summary"]["feature_model_summaries"][0]["feature"] == "recommend_slot"
