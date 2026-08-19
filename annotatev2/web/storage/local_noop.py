from __future__ import annotations

from pathlib import Path

from .base import RemoteStorageBackend


class NoopBackend(RemoteStorageBackend):
    """REMOTE_STORAGE_BACKEND=none (the default). Photos stay local-only -
    the sync worker never even tries, since ``is_configured`` is False."""

    name = "none"

    def is_configured(self) -> bool:
        return False

    def upload(self, local_path: Path, key: str, content_type: str) -> str:
        raise RuntimeError("NoopBackend cannot upload - remote sync is disabled")
