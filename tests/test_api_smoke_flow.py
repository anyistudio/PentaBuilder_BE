from fastapi.testclient import TestClient


def _exchange_access_token(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/exchange",
        json={
            "provider": "clerk",
            "provider_token": "dev-clerk:user_1:test@example.com:BlueFox",
        },
    )
    assert response.status_code == 200
    return response.json()["data"]["access_token"]


def test_end_to_end_smoke_flow(configured_client: TestClient) -> None:
    access_token = _exchange_access_token(configured_client)
    headers = {"Authorization": f"Bearer {access_token}"}

    current_version_response = configured_client.get("/api/v1/catalog/versions/current")
    assert current_version_response.status_code == 200
    data_version = current_version_response.json()["data"]["data_version"]

    lookup_response = configured_client.get(
        "/api/v1/catalog/lol/lookup",
        params={"q": "狐狸", "entity_type": "champion", "language": "zh-CN"},
    )
    assert lookup_response.status_code == 200
    assert lookup_response.json()["data"]["results"][0]["slug"] == "lol-ahri"

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
    create_session_response = configured_client.post(
        "/api/v1/sessions",
        headers=headers,
        json={
            "client_session_id": "client-local-1",
            "game": "lol",
            "data_version": data_version,
            "initial_context": context,
        },
    )
    assert create_session_response.status_code == 201
    session_id = create_session_response.json()["data"]["session"]["id"]

    recommend_response = configured_client.post(
        "/api/v1/ai/runs",
        headers=headers,
        json={
            "run_type": "recommend_slot",
            "context": context,
            "response_preferences": {
                "language": "zh-CN",
                "terminology_style": "official",
            },
            "session_id": session_id,
            "payload": {"slot_index": 1},
        },
    )
    assert recommend_response.status_code == 200
    recommend_data = recommend_response.json()["data"]
    assert recommend_data["run"]["cache_resolution"] == "miss"
    assert recommend_data["result"]["build"][1] is not None

    recommend_cached_response = configured_client.post(
        "/api/v1/ai/runs",
        headers=headers,
        json={
            "run_type": "recommend_slot",
            "context": context,
            "response_preferences": {
                "language": "zh-CN",
                "terminology_style": "official",
            },
            "session_id": session_id,
            "payload": {"slot_index": 1},
        },
    )
    assert recommend_cached_response.status_code == 200
    assert recommend_cached_response.json()["data"]["run"]["cache_resolution"] == "strong_hit"

    evaluate_response = configured_client.post(
        "/api/v1/ai/runs",
        headers=headers,
        json={
            "run_type": "evaluate_build",
            "context": context,
            "response_preferences": {
                "language": "zh-CN",
                "terminology_style": "official",
            },
            "session_id": session_id,
            "payload": {},
        },
    )
    assert evaluate_response.status_code == 200
    evaluate_data = evaluate_response.json()["data"]
    assert evaluate_data["result"]["score"] >= 60

    session_list_response = configured_client.get("/api/v1/sessions", headers=headers)
    assert session_list_response.status_code == 200
    assert len(session_list_response.json()["data"]["items"]) == 1

    session_detail_response = configured_client.get(
        f"/api/v1/sessions/{session_id}", headers=headers
    )
    assert session_detail_response.status_code == 200
    assert session_detail_response.json()["data"]["transcript"]["events"]

    leaderboard_response = configured_client.get(
        "/api/v1/leaderboard",
        headers=headers,
        params={"game": "lol", "own_champion_slug": "lol-ahri"},
    )
    assert leaderboard_response.status_code == 200
    leaderboard_items = leaderboard_response.json()["data"]["items"]
    assert leaderboard_items
    assert leaderboard_items[0]["top_score"] >= 60
