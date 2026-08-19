"""S3-compatible backend - works unmodified for real AWS S3 or Cloudflare R2
(R2 speaks the S3 API; only the endpoint/region differ, see .env.example).

Fully implemented - flip REMOTE_STORAGE_BACKEND=s3 and fill in the
S3_*/credentials, nothing else to change.
"""

from __future__ import annotations

from pathlib import Path

from web import config

from .base import RemoteStorageBackend


class S3Backend(RemoteStorageBackend):
    name = "s3"

    def __init__(self) -> None:
        self._client = None

    def is_configured(self) -> bool:
        return bool(config.S3_BUCKET and config.S3_ACCESS_KEY_ID and config.S3_SECRET_ACCESS_KEY)

    def _get_client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client(
                "s3",
                endpoint_url=config.S3_ENDPOINT_URL,
                aws_access_key_id=config.S3_ACCESS_KEY_ID,
                aws_secret_access_key=config.S3_SECRET_ACCESS_KEY,
                region_name=config.S3_REGION,
            )
        return self._client

    def upload(self, local_path: Path, key: str, content_type: str) -> str:
        if not self.is_configured():
            raise RuntimeError("S3_BUCKET/S3_ACCESS_KEY_ID/S3_SECRET_ACCESS_KEY are not fully set")
        client = self._get_client()
        client.upload_file(
            str(local_path),
            config.S3_BUCKET,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        if config.S3_ENDPOINT_URL:
            return f"{config.S3_ENDPOINT_URL.rstrip('/')}/{config.S3_BUCKET}/{key}"
        return f"s3://{config.S3_BUCKET}/{key}"
