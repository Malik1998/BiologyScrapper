from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class RemoteStorageBackend(ABC):
    """One method: mirror a local file to remote storage under ``key`` and
    hand back a URL/reference for the record. Runs in a background task off
    a worker thread (see ``web.sync_worker``), so it's fine for
    implementations to do blocking I/O.
    """

    name: str = "base"

    @abstractmethod
    def upload(self, local_path: Path, key: str, content_type: str) -> str:
        """Upload ``local_path`` to ``key`` on the remote backend. Returns a
        URL or reference string to store on the photo record. Raises on
        failure (caller records the error and retries later)."""
        raise NotImplementedError

    def is_configured(self) -> bool:
        """Whether credentials/tokens are present. The sync worker checks
        this before attempting an upload so a half-configured backend fails
        fast with a clear message instead of a confusing network error."""
        return True
