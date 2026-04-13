from app.core.config import Settings
from app.services.storage_service import StorageService


def test_storage_service_local_object_round_trip(tmp_path) -> None:
    settings = Settings(
        game_data_source="local",
        s3_bucket="test-bucket",
    )
    storage_service = StorageService(settings)
    object_key = "sessions/demo/transcript.json"
    payload = {"hello": "world"}

    storage_service.write_json(object_key, payload)
    assert storage_service.read_json_object(object_key) == payload

    storage_service.delete_object(object_key)
    assert not (storage_service.local_artifact_root / object_key).exists()
