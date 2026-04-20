from fastapi.testclient import TestClient

from app.core import llm_debug
from app.core.config import Settings
from app.domain.enums import RunType
from app.domain.match_context import MatchContext, ResponsePreferences
from app.main import create_app


def test_healthz_returns_ok(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["X-Request-ID"]


def test_unhandled_exceptions_are_wrapped_as_json() -> None:
    app = create_app()

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("boom")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_server_error"
    assert response.json()["request_id"]


def test_clear_debug_llm_log_endpoint(monkeypatch, tmp_path) -> None:
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    (log_dir / "run-a.log").write_text("run a", encoding="utf-8")
    (log_dir / "run-b.log").write_text("run b", encoding="utf-8")
    legacy_log_path = tmp_path / "debug_llm.log"
    legacy_log_path.write_text("legacy log", encoding="utf-8")
    monkeypatch.setattr(llm_debug, "LLM_DEBUG_LOG_DIR", log_dir)
    monkeypatch.setattr(llm_debug, "LEGACY_LLM_DEBUG_LOG_PATH", legacy_log_path)

    app = create_app()
    with TestClient(app) as client:
        response = client.post("/api/v1/ai/debug/llm-log/clear")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["cleared"] is True
    assert payload["existed"] is True
    assert payload["bytes_removed"] > 0
    assert payload["files_removed"] == 3
    assert payload["log_path"] == str(log_dir)
    assert log_dir.exists()
    assert not list(log_dir.glob("*.log"))
    assert not legacy_log_path.exists()


def test_append_llm_debug_log_uses_run_id_file(monkeypatch, tmp_path) -> None:
    log_dir = tmp_path / "log"
    monkeypatch.setattr(llm_debug, "LLM_DEBUG_LOG_DIR", log_dir)
    monkeypatch.setattr(llm_debug, "LEGACY_LLM_DEBUG_LOG_PATH", tmp_path / "debug_llm.log")
    log_file_name = "20260418-103045-123456-4000.log"

    with llm_debug.llm_debug_scope(
        workflow_name="online_run",
        log_file_name=log_file_name,
        run_type="recommend_full_build",
        run_id="123e4567-e89b-12d3-a456-426614174000",
    ):
        llm_debug.append_llm_debug_log("provider_request", prompt="hello world")

    log_path = log_dir / log_file_name
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "LLM Debug Event: provider_request" in content
    assert "Run ID: 123e4567-e89b-12d3-a456-426614174000" in content


def test_build_run_log_file_name_uses_start_timestamp_and_run_suffix() -> None:
    log_file_name = llm_debug.build_run_log_file_name(
        run_id="123e4567-e89b-12d3-a456-426614174000",
        started_at="2026-04-18T15:30:45.123456+00:00",
    )

    assert log_file_name == "20260418-103045-123456-4000.log"


def test_slug_selector_model_accepts_provider_prefixed_model_ref(monkeypatch) -> None:
    monkeypatch.setenv("FAST_REASONING_MODEL", "google:gemini-3-flash-preview")
    monkeypatch.setenv("SLUG_SELECTOR_MODEL", "openai:gpt-5.4-mini")

    settings = Settings(_env_file=None)

    assert settings.resolved_slug_selector_provider == "openai"
    assert settings.resolved_slug_selector_model == "gpt-5.4-mini"


def test_primary_and_fast_reasoning_model_refs_split_provider_and_model(monkeypatch) -> None:
    monkeypatch.setenv("PRIMARY_REASONING_MODEL", "openai:gpt-5.4")
    monkeypatch.setenv("FAST_REASONING_MODEL", "google:gemini-3-flash-preview")

    settings = Settings(_env_file=None)

    assert settings.resolved_primary_reasoning_provider == "openai"
    assert settings.resolved_primary_reasoning_model == "gpt-5.4"
    assert settings.resolved_fast_reasoning_provider == "google"
    assert settings.resolved_fast_reasoning_model == "gemini-3-flash-preview"


def test_prepare_run_keeps_selector_model_on_env_config(
    configured_app,
    monkeypatch,
) -> None:
    captured_calls: list[tuple[str, str]] = []

    class DummyClient:
        def __init__(self, provider_name: str, model_name: str) -> None:
            self.provider_name = provider_name
            self.model_name = model_name

    def record_create_llm_client(*, settings, provider_name: str, model_name: str):
        del settings
        captured_calls.append((provider_name, model_name))
        return DummyClient(provider_name, model_name)

    monkeypatch.setattr(
        "app.services.ai_run_service.create_llm_client",
        record_create_llm_client,
    )
    configured_app.state.ai_run_service.settings.fast_reasoning_model = (
        "google:gemini-3-flash-preview"
    )
    configured_app.state.ai_run_service.settings.slug_selector_model = "openai:gpt-5.4-mini"

    session = configured_app.state.session_factory()
    try:
        version = configured_app.state.data_version_service.get_active_version(session)
        context = MatchContext(
            game="wild_rift",
            data_version=version.data_version,
            own_champion_slug="wr-ahri",
            enemy_team=[],
            own_build=[None, None, None, None, None, None, None],
            own_runes={"primary": [], "secondary": []},
            environment={"tags": [], "free_text": ""},
        )
        run, _ = configured_app.state.ai_run_service.create_run(
            session,
            user=None,
            session_id=None,
            run_type=RunType.RECOMMEND_FULL_BUILD,
            context=context,
            response_preferences=ResponsePreferences(),
            operation_context={},
            stream=False,
            use_cache=False,
        )

        configured_app.state.ai_run_service._prepare_run(
            session,
            run=run,
            context=context,
            response_preferences=ResponsePreferences(),
            operation_context={},
            provider_name_override="google",
            model_name_override="gemini-3.1-pro-preview",
        )
    finally:
        session.close()

    assert captured_calls[0] == ("google", "gemini-3.1-pro-preview")
    assert captured_calls[1] == ("openai", "gpt-5.4-mini")
