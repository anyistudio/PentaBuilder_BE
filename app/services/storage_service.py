import json
from pathlib import Path
from typing import Any

import boto3
from botocore.client import BaseClient

from app.core.config import BASE_DIR, Settings


class StorageService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._s3_client: BaseClient | None = None

    def read_json_from_root(self, root: str, relative_path: str) -> Any:
        return json.loads(self.read_text_from_root(root, relative_path))

    def read_optional_json_from_root(self, root: str, relative_path: str) -> Any | None:
        try:
            return self.read_json_from_root(root, relative_path)
        except Exception as e:
            if getattr(e, "response", {}).get("Error", {}).get("Code") == "NoSuchKey" or e.__class__.__name__ == "NoSuchKey" or isinstance(e, FileNotFoundError):
                return None
            raise

    def read_text_from_root(self, root: str, relative_path: str) -> str:
        if self._should_use_s3(root):
            return self._read_text_from_s3(root, relative_path)
        return self._read_text_from_local(root, relative_path)

    def read_bytes_from_root(self, root: str, relative_path: str) -> bytes:
        if self._should_use_s3(root):
            return self._read_bytes_from_s3(root, relative_path)
        return self._read_bytes_from_local(root, relative_path)

    def write_json(self, object_key: str, payload: Any) -> str:
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        self.write_text(object_key, serialized)
        return object_key

    def read_json_object(self, object_key: str) -> Any:
        return json.loads(self.read_text_object(object_key))

    def write_text(self, object_key: str, content: str) -> str:
        if self.settings.game_data_source == "s3":
            self._write_text_to_s3(object_key, content)
        else:
            self._write_text_to_local_artifact_root(object_key, content)
        return object_key

    def read_text_object(self, object_key: str) -> str:
        if self.settings.game_data_source == "s3":
            return self._read_text_from_s3("", object_key)
        return self._read_text_from_local_artifact_root(object_key)

    def read_bytes_object(self, object_key: str) -> bytes:
        if self.settings.game_data_source == "s3":
            return self._read_bytes_from_s3("", object_key)
        return self._read_bytes_from_local_artifact_root(object_key)

    def delete_object(self, object_key: str) -> None:
        if self.settings.game_data_source == "s3":
            self.s3_client.delete_object(Bucket=self.settings.s3_bucket, Key=object_key)
            return

        file_path = self.local_artifact_root / object_key
        if file_path.exists():
            file_path.unlink()

    def _should_use_s3(self, root: str) -> bool:
        return root.startswith("s3://") or self.settings.game_data_source == "s3"

    def _read_text_from_local(self, root: str, relative_path: str) -> str:
        base_path = Path(root)
        if not base_path.is_absolute():
            base_path = BASE_DIR / base_path
        file_path = base_path / relative_path
        return file_path.read_text(encoding="utf-8")

    def _read_bytes_from_local(self, root: str, relative_path: str) -> bytes:
        base_path = Path(root)
        if not base_path.is_absolute():
            base_path = BASE_DIR / base_path
        file_path = base_path / relative_path
        return file_path.read_bytes()

    def _read_text_from_s3(self, root: str, relative_path: str) -> str:
        prefix = root.removeprefix("s3://")
        key = "/".join(part for part in (prefix.rstrip("/"), relative_path.lstrip("/")) if part)
        response = self.s3_client.get_object(Bucket=self.settings.s3_bucket, Key=key)
        return response["Body"].read().decode("utf-8")

    def _read_bytes_from_s3(self, root: str, relative_path: str) -> bytes:
        prefix = root.removeprefix("s3://")
        key = "/".join(part for part in (prefix.rstrip("/"), relative_path.lstrip("/")) if part)
        response = self.s3_client.get_object(Bucket=self.settings.s3_bucket, Key=key)
        return response["Body"].read()

    def _write_text_to_s3(self, object_key: str, content: str) -> None:
        self.s3_client.put_object(
            Bucket=self.settings.s3_bucket,
            Key=object_key,
            Body=content.encode("utf-8"),
            ContentType="application/json",
        )

    def _write_text_to_local_artifact_root(self, object_key: str, content: str) -> None:
        file_path = self.local_artifact_root / object_key
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

    def _read_text_from_local_artifact_root(self, object_key: str) -> str:
        file_path = self.local_artifact_root / object_key
        return file_path.read_text(encoding="utf-8")

    def _read_bytes_from_local_artifact_root(self, object_key: str) -> bytes:
        file_path = self.local_artifact_root / object_key
        return file_path.read_bytes()

    @property
    def s3_client(self) -> BaseClient:
        if self._s3_client is None:
            self._s3_client = boto3.client(
                "s3",
                endpoint_url=self.settings.s3_endpoint,
                aws_access_key_id=self.settings.s3_access_key.get_secret_value(),
                aws_secret_access_key=self.settings.s3_secret_key.get_secret_value(),
                region_name=self.settings.s3_region,
            )
        return self._s3_client

    @property
    def local_artifact_root(self) -> Path:
        return BASE_DIR / ".local_object_storage" / self.settings.s3_bucket
