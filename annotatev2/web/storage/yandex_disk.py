"""Yandex Disk backend (REST API: https://yandex.ru/dev/disk/api/).

Needs YANDEX_DISK_TOKEN (an OAuth token for an app with disk.write scope,
see .env.example). Fully implemented - flip REMOTE_STORAGE_BACKEND=yandex_disk
and set the token, nothing else to change.
"""

from __future__ import annotations

import logging
from pathlib import Path

import requests

from web import config

from .base import RemoteStorageBackend

logger = logging.getLogger(__name__)

API_BASE = "https://cloud-api.yandex.net/v1/disk"


class YandexDiskBackend(RemoteStorageBackend):
    name = "yandex_disk"

    def __init__(self) -> None:
        self._folder_ready = False

    def is_configured(self) -> bool:
        return bool(config.YANDEX_DISK_TOKEN)

    def _headers(self) -> dict:
        return {"Authorization": f"OAuth {config.YANDEX_DISK_TOKEN}"}

    def _ensure_folder(self) -> None:
        if self._folder_ready:
            return
        resp = requests.put(
            f"{API_BASE}/resources",
            params={"path": config.YANDEX_DISK_FOLDER},
            headers=self._headers(),
            timeout=15,
        )
        # 201 = created, 409 = already exists - both fine.
        if resp.status_code not in (201, 409):
            resp.raise_for_status()
        self._folder_ready = True

    def upload(self, local_path: Path, key: str, content_type: str) -> str:
        if not self.is_configured():
            raise RuntimeError("YANDEX_DISK_TOKEN is not set")
        self._ensure_folder()

        remote_path = f"{config.YANDEX_DISK_FOLDER.rstrip('/')}/{key}"
        resp = requests.get(
            f"{API_BASE}/resources/upload",
            params={"path": remote_path, "overwrite": "true"},
            headers=self._headers(),
            timeout=15,
        )
        resp.raise_for_status()
        upload_href = resp.json()["href"]

        with open(local_path, "rb") as f:
            put_resp = requests.put(upload_href, data=f, timeout=120)
        put_resp.raise_for_status()

        return f"yadisk://{remote_path}"
