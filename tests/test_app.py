from fastapi.testclient import TestClient

from app.core import llm_debug
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
