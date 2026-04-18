import json

from fastapi.testclient import TestClient

from app.ai.providers.base import LLMResult, LLMStreamEvent, LLMUsage
from app.services.ai_run_service import _SectionedStreamParser


class FakeLLMClient:
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
        if response_mime_type == "application/json" and "Tool planning mode:" in combined_prompt:
            text = json.dumps(
                {
                    "tool_calls": [
                        {
                            "tool_name": "search_catalog",
                            "arguments": {
                                "entity_type": "item",
                                "query": "defensive mage item against burst",
                                "limit": 4,
                            },
                        }
                    ]
                    if "## Tool Facts" not in prompt
                    else [],
                    "done": "## Tool Facts" in prompt,
                },
                ensure_ascii=False,
            )
        elif response_mime_type == "application/json":
            text = (
                '{"slot_index":1,"current_item_slug":null,"is_current_choice_good":false,'
                '"best_item_slug":"lol-zhonya-s-hourglass","summary":"这件装备能更稳地顶住爆发，然后把中期团战接起来。",'
                '"why_current_choice":"当前这个位置还没有成型。","why_best_choice":"中娅能直接补上当前最缺的容错。",'
                '"linked_adjustments":[]}'
            )
        else:
            text = "这件装备能更稳地顶住爆发，然后把中期团战接起来。"
        del prompt
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
        del response_mime_type, response_schema, temperature
        text = "这件装备能更稳地顶住爆发，然后把中期团战接起来。"
        if system_prompt and "Streaming + structured mode:" in system_prompt:
            text = (
                "<display>这件装备能更稳地顶住爆发，然后把中期团战接起来。</display>"
                "<json>"
                '{"slot_index":1,"current_item_slug":null,"is_current_choice_good":false,'
                '"best_item_slug":"lol-zhonya-s-hourglass","summary":"这件装备能更稳地顶住爆发，然后把中期团战接起来。",'
                '"why_current_choice":"当前这个位置还没有成型。","why_best_choice":"中娅能直接补上当前最缺的容错。",'
                '"linked_adjustments":[]}'
                "</json>"
            )
        del prompt
        for index in range(0, len(text), 8):
            yield LLMStreamEvent(event_type="text_delta", delta=text[index : index + 8])
        yield LLMStreamEvent(
            event_type="completed",
            usage=LLMUsage(input_tokens=8, output_tokens=10, latency_ms=4, cost_usd=0.0005),
            provider_name=self.provider_name,
            model_name=self.model_name,
        )


def _exchange_access_token(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/exchange",
        json={
            "provider": "clerk",
            "provider_token": "dev-clerk:user_2:test2@example.com:BenchFox",
        },
    )
    assert response.status_code == 200
    return response.json()["data"]["access_token"]


def test_streaming_explain_slot_uses_sse(configured_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.ai_run_service.create_llm_client",
        lambda **kwargs: FakeLLMClient(),
    )
    access_token = _exchange_access_token(configured_client)
    headers = {"Authorization": f"Bearer {access_token}"}
    data_version = configured_client.get("/api/v1/catalog/versions/current").json()["data"][
        "data_version"
    ]
    context = {
        "game": "lol",
        "data_version": data_version,
        "own_champion_slug": "lol-ahri",
        "enemy_team": [
            {
                "champion_slug": "lol-zed",
                "build": [None, None, None, None, None, None],
                "runes": {"primary": [], "secondary": []},
            }
        ],
        "own_build": ["lol-luden-s-companion", None, None, None, None, None],
        "own_runes": {"primary": [], "secondary": []},
        "environment": {"tags": ["assassin-heavy", "ranked"], "free_text": ""},
    }

    response = configured_client.post(
        "/api/v1/ai/runs",
        headers=headers,
        json={
            "run_type": "explain_slot",
            "context": context,
            "response_preferences": {"language": "zh-CN", "terminology_style": "official"},
            "stream": True,
            "payload": {"slot_index": 1},
        },
    )
    assert response.status_code == 202
    stream_url = response.json()["data"]["stream_url"]

    with configured_client.stream("GET", stream_url, headers=headers) as stream_response:
        body = "".join(
            chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
            for chunk in stream_response.iter_text()
        )

    assert "event: run_started" in body
    assert "event: tool_event" in body
    assert "event: message_delta" in body
    assert "event: run_completed" in body
    assert '"status":"fallback"' not in body
    assert "gemini-test" not in body


def test_sectioned_stream_parser_extracts_display_and_json() -> None:
    parser = _SectionedStreamParser()
    deltas = [
        "<displ",
        "ay>用户可见内容</display><js",
        'on>{"summary":"用户可见内容"}</json>',
    ]
    emitted = "".join(parser.push(delta) for delta in deltas)
    parser.finish()

    assert emitted == "用户可见内容"
    assert parser.display_text == "用户可见内容"
    assert json.loads(parser.json_text) == {"summary": "用户可见内容"}


def test_admin_jobs_cover_baselines_calibrations_benchmarks_and_cache(
    configured_app,
    configured_client: TestClient,
) -> None:
    access_token = _exchange_access_token(configured_client)
    headers = {"Authorization": f"Bearer {access_token}"}
    admin_auth = ("admin", "secret")
    data_version = configured_client.get("/api/v1/catalog/versions/current").json()["data"][
        "data_version"
    ]

    context = {
        "game": "lol",
        "data_version": data_version,
        "own_champion_slug": "lol-ahri",
        "enemy_team": [],
        "own_build": [None, None, None, None, None, None],
        "own_runes": {"primary": [], "secondary": []},
        "environment": {"tags": ["ranked"], "free_text": ""},
    }
    configured_client.post(
        "/api/v1/ai/runs",
        headers=headers,
        json={
            "run_type": "recommend_full_build",
            "context": context,
            "response_preferences": {"language": "zh-CN", "terminology_style": "official"},
            "payload": {},
        },
    )

    cache_job_response = configured_client.post(
        "/api/v1/admin/cache/clear",
        auth=admin_auth,
        json={"data_version": data_version, "game": "lol"},
    )
    assert cache_job_response.status_code == 202
    cache_job_id = cache_job_response.json()["data"]["job_id"]
    cache_job_detail = configured_client.get(f"/api/v1/admin/jobs/{cache_job_id}", auth=admin_auth)
    assert cache_job_detail.status_code == 200
    assert cache_job_detail.json()["data"]["job"]["status"] == "completed"

    baseline_job_response = configured_client.post(
        "/api/v1/admin/jobs/precompute-baselines",
        auth=admin_auth,
        json={
            "data_version": data_version,
            "game": "lol",
            "provider_name": "google",
            "model_name": "gemini-3-flash-preview",
        },
    )
    assert baseline_job_response.status_code == 202
    baseline_job_id = baseline_job_response.json()["data"]["job_id"]
    baseline_job_detail = configured_client.get(
        f"/api/v1/admin/jobs/{baseline_job_id}", auth=admin_auth
    )
    assert baseline_job_detail.status_code == 200
    assert baseline_job_detail.json()["data"]["job"]["status"] == "completed"

    calibration_job_response = configured_client.post(
        "/api/v1/admin/jobs/generate-calibrations",
        auth=admin_auth,
        json={
            "data_version": data_version,
            "games": ["lol"],
            "models": [{"provider_name": "google", "model_name": "gemini-3-flash-preview"}],
        },
    )
    assert calibration_job_response.status_code == 202
    calibration_job_id = calibration_job_response.json()["data"]["job_id"]
    calibration_job_detail = configured_client.get(
        f"/api/v1/admin/jobs/{calibration_job_id}",
        auth=admin_auth,
    )
    assert calibration_job_detail.status_code == 200
    assert calibration_job_detail.json()["data"]["job"]["status"] == "completed"

    session = configured_app.state.session_factory()
    try:
        datasets = configured_app.state.benchmark_service.sync_local_datasets(session)
        assert datasets
        dataset_id = str(datasets[0].id)
    finally:
        session.close()

    benchmark_job_response = configured_client.post(
        "/api/v1/admin/jobs/run-benchmarks",
        auth=admin_auth,
        json={
            "dataset_id": dataset_id,
            "models": [{"provider_name": "google", "model_name": "gemini-3-flash-preview"}],
        },
    )
    assert benchmark_job_response.status_code == 202
    benchmark_job_id = benchmark_job_response.json()["data"]["job_id"]
    benchmark_job_detail = configured_client.get(
        f"/api/v1/admin/jobs/{benchmark_job_id}",
        auth=admin_auth,
    )
    assert benchmark_job_detail.status_code == 200
    assert benchmark_job_detail.json()["data"]["job"]["status"] == "completed"

    metrics_response = configured_client.get("/api/v1/admin/metrics", auth=admin_auth)
    assert metrics_response.status_code == 200
    assert "requests_total" in metrics_response.json()["data"]["counters"]
