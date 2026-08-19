"""Pluggable remote-storage mirror. The full photo always lands on local
disk synchronously (see ``data_access.save_photo_file``) - everything in
this package only concerns *also* copying that same file to a remote
backend in the background, so a slow/unreachable remote never blocks or
risks an upload.

Selected via ``REMOTE_STORAGE_BACKEND`` (see .env.example): ``none`` (the
default), ``yandex_disk`` or ``s3`` (also covers Cloudflare R2, which is
S3-compatible). Swapping backends later is just setting env vars - no code
changes.
"""

from __future__ import annotations

from web import config

from .base import RemoteStorageBackend
from .local_noop import NoopBackend
from .s3 import S3Backend
from .yandex_disk import YandexDiskBackend

_backend: RemoteStorageBackend | None = None


def get_backend() -> RemoteStorageBackend:
    global _backend
    if _backend is not None:
        return _backend

    kind = config.REMOTE_STORAGE_BACKEND
    if kind == "yandex_disk":
        _backend = YandexDiskBackend()
    elif kind == "s3":
        _backend = S3Backend()
    elif kind == "none":
        _backend = NoopBackend()
    else:
        raise ValueError(
            f"Unknown REMOTE_STORAGE_BACKEND={kind!r} - expected none, yandex_disk or s3"
        )
    return _backend
