"""Background remote-storage mirroring. The local write in
data_access.save_photo already happened and already succeeded by the time
anything here runs - this only ever *adds* a copy elsewhere, so a slow or
down remote backend never blocks an uploader or risks the original photo.

Two entry points:
- ``sync_one`` is scheduled as a FastAPI BackgroundTask right after each
  upload, for low-latency mirroring in the common case.
- ``sweep_loop`` runs for the lifetime of the process and periodically
  retries anything still ``pending``/``failed`` (e.g. the backend was down,
  or the process restarted mid-upload) - a safety net so a transient remote
  failure can't silently leave a photo unmirrored forever.
"""

from __future__ import annotations

import asyncio
import logging

from web import config, data_access
from web.storage import get_backend

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = 60
MAX_ATTEMPTS_LOGGED = 5


def _do_upload(photo: data_access.Photo) -> None:
    backend = get_backend()
    if not backend.is_configured():
        data_access.update_photo_sync_status(
            photo.id, status="failed", error=f"{backend.name} backend not configured"
        )
        return

    local_path = data_access.photo_file_path(photo.id)
    key = f"{photo.family_slug}/{photo.photo_type}_{photo.id}.jpg"
    try:
        remote_url = backend.upload(local_path, key, "image/jpeg")
    except Exception as e:  # noqa: BLE001 - any backend failure just means "retry later"
        logger.warning("remote sync failed for photo %s: %s", photo.id, e)
        data_access.update_photo_sync_status(photo.id, status="failed", error=str(e))
        return

    data_access.update_photo_sync_status(
        photo.id, status="synced", remote_backend=backend.name, remote_url=remote_url, error=None,
    )


async def sync_one(photo_id: str) -> None:
    if config.REMOTE_STORAGE_BACKEND == "none":
        return
    photo = data_access.get_photo(photo_id)
    if photo is None:
        return
    await asyncio.to_thread(_do_upload, photo)


async def sweep_loop() -> None:
    if config.REMOTE_STORAGE_BACKEND == "none":
        logger.info("remote sync disabled (REMOTE_STORAGE_BACKEND=none) - sweep loop not starting")
        return
    logger.info("remote sync sweep loop starting (backend=%s, every %ss)",
                config.REMOTE_STORAGE_BACKEND, SWEEP_INTERVAL_SECONDS)
    while True:
        try:
            pending = [p for p in data_access.list_photos() if p.sync_status in ("pending", "failed")]
            for photo in pending:
                await asyncio.to_thread(_do_upload, photo)
        except Exception:
            logger.exception("sync sweep iteration failed")
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
