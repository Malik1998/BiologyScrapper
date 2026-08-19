"""File-based storage for submissions and photos - one JSON record per
entity, same "no database, atomic-write JSON files under data/" approach
already used by ../Scrapping/web/annotate_data.py. At this scale (a
handful of families, 4 photos each) this is simpler to operate than
standing up a DB, and every write touches its own file so concurrent
uploads never contend with each other.

One submission = one family sitting down once and uploading up to 4
photos (config/photo_types.json): themselves now, themselves older,
mother, father - see README for why it's shaped this way.

Layout (all under data/, gitignored):
    data/submissions/<submission_id>.json   - family_label, created_at
    data/photos/<photo_id>.json              - one record per uploaded photo
    data/photos/files/<photo_id>.jpg         - the full, uncropped image
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps

from web import config

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)  # atomic on POSIX - readers never see a half-written file


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "family"


# ── Photo types ──────────────────────────────────────────────────────────

def load_photo_types() -> list[dict]:
    return json.loads(config.PHOTO_TYPES_PATH.read_text())


# ── Submissions ──────────────────────────────────────────────────────────

@dataclass
class Submission:
    id: str
    family_label: str
    family_slug: str
    created_at: str = field(default_factory=_now)


def create_submission(family_label: str) -> Submission:
    family_label = family_label.strip()
    if not family_label:
        raise ValueError("family_label is required")

    submission = Submission(
        id=_new_id(),
        family_label=family_label,
        family_slug=slugify(family_label),
    )
    _atomic_write_json(_submission_path(submission.id), asdict(submission))
    return submission


def _submission_path(submission_id: str) -> Path:
    return config.SUBMISSIONS_DIR / f"{submission_id}.json"


def get_submission(submission_id: str) -> Optional[Submission]:
    path = _submission_path(submission_id)
    if not path.exists():
        return None
    return Submission(**json.loads(path.read_text()))


def list_submissions() -> list[Submission]:
    if not config.SUBMISSIONS_DIR.exists():
        return []
    out = []
    for f in sorted(config.SUBMISSIONS_DIR.glob("*.json")):
        try:
            out.append(Submission(**json.loads(f.read_text())))
        except Exception:
            logger.exception("failed to load submission record %s", f)
    return out


# ── Photos ───────────────────────────────────────────────────────────────

@dataclass
class Photo:
    id: str
    submission_id: str
    family_label: str
    family_slug: str
    photo_type: str
    uploaded_at: str
    width: int
    height: int
    crop: Optional[dict]           # {x, y, width, height} in this photo's pixel coords, or None
    face_check: dict               # {"enabled": bool, "passed": bool, "detail": str}
    sync_status: str               # local_only | pending | synced | failed
    remote_backend: Optional[str] = None
    remote_url: Optional[str] = None
    sync_error: Optional[str] = None


def _photo_json_path(photo_id: str) -> Path:
    return config.PHOTOS_DIR / f"{photo_id}.json"


def _photo_file_path(photo_id: str) -> Path:
    return config.PHOTO_FILES_DIR / f"{photo_id}.jpg"


def save_photo(
    *,
    submission: Submission,
    photo_type: str,
    image_bytes: bytes,
    crop: Optional[dict],
    face_check_result,
) -> Photo:
    """Normalize orientation, write the full photo to local disk, and record
    metadata. Runs synchronously in the request (local disk write is fast);
    any remote mirroring happens afterwards in the background - see
    web.sync_worker. Uploading the same photo_type again for a submission
    just adds another record - see data_access.replace behavior notes in
    web/app.py (old one is deleted so a slot never shows two photos)."""
    from io import BytesIO

    with Image.open(BytesIO(image_bytes)) as im:
        im = ImageOps.exif_transpose(im)  # bake in phone EXIF rotation so
        # stored pixels match what the crop coordinates were computed against
        im = im.convert("RGB")
        width, height = im.size

        photo_id = _new_id()
        file_path = _photo_file_path(photo_id)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        im.save(file_path, "JPEG", quality=95)

    remote_configured = config.REMOTE_STORAGE_BACKEND != "none"
    photo = Photo(
        id=photo_id,
        submission_id=submission.id,
        family_label=submission.family_label,
        family_slug=submission.family_slug,
        photo_type=photo_type,
        uploaded_at=_now(),
        width=width,
        height=height,
        crop=crop,
        face_check={
            "enabled": face_check_result.enabled,
            "passed": face_check_result.passed,
            "detail": face_check_result.detail,
        },
        sync_status="pending" if remote_configured else "local_only",
    )
    _atomic_write_json(_photo_json_path(photo_id), asdict(photo))
    return photo


def get_photo(photo_id: str) -> Optional[Photo]:
    path = _photo_json_path(photo_id)
    if not path.exists():
        return None
    return Photo(**json.loads(path.read_text()))


def delete_photo(photo_id: str) -> None:
    _photo_json_path(photo_id).unlink(missing_ok=True)
    _photo_file_path(photo_id).unlink(missing_ok=True)


def update_photo_sync_status(
    photo_id: str, *, status: str, remote_backend: str | None = None,
    remote_url: str | None = None, error: str | None = None,
) -> None:
    photo = get_photo(photo_id)
    if photo is None:
        return
    photo.sync_status = status
    photo.remote_backend = remote_backend or photo.remote_backend
    photo.remote_url = remote_url or photo.remote_url
    photo.sync_error = error
    _atomic_write_json(_photo_json_path(photo_id), asdict(photo))


def list_photos(*, submission_id: Optional[str] = None) -> list[Photo]:
    if not config.PHOTOS_DIR.exists():
        return []
    out = []
    for f in sorted(config.PHOTOS_DIR.glob("*.json")):
        try:
            photo = Photo(**json.loads(f.read_text()))
        except Exception:
            logger.exception("failed to load photo record %s", f)
            continue
        if submission_id is not None and photo.submission_id != submission_id:
            continue
        out.append(photo)
    return out


def photo_file_path(photo_id: str) -> Path:
    return _photo_file_path(photo_id)


def render_cropped(photo_id: str) -> bytes:
    """Reconstruct the crop on demand from the stored full image + crop
    JSON, proving the round trip works without ever duplicating storage."""
    from io import BytesIO

    photo = get_photo(photo_id)
    if photo is None:
        raise FileNotFoundError(photo_id)
    file_path = _photo_file_path(photo_id)
    with Image.open(file_path) as im:
        if photo.crop:
            x, y, w, h = (
                photo.crop["x"], photo.crop["y"], photo.crop["width"], photo.crop["height"],
            )
            left = max(0, min(round(x), im.width - 1))
            top = max(0, min(round(y), im.height - 1))
            right = max(left + 1, min(round(x + w), im.width))
            bottom = max(top + 1, min(round(y + h), im.height))
            im = im.crop((left, top, right, bottom))
        buf = BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=95)
        return buf.getvalue()
