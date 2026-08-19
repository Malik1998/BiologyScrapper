"""All environment-driven settings, read once at import time. See
.env.example for what each of these does."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PHOTOS_DIR = DATA_DIR / "photos"
PHOTO_FILES_DIR = PHOTOS_DIR / "files"
SUBMISSIONS_DIR = DATA_DIR / "submissions"
PHOTO_TYPES_PATH = BASE_DIR / "config" / "photo_types.json"

# At least one of these must be uploaded - the other is fine to skip
# (e.g. only one parent available/willing). Both self_* types stay required.
OPTIONAL_GROUP = ("mother_50_60", "father_50_60")

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8001"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

ADMIN_USER = os.environ.get("ADMIN_USER", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

ENABLE_FACE_CHECK = os.environ.get("ENABLE_FACE_CHECK", "false").strip().lower() in (
    "1", "true", "yes", "on",
)

REMOTE_STORAGE_BACKEND = os.environ.get("REMOTE_STORAGE_BACKEND", "none").strip().lower()

YANDEX_DISK_TOKEN = os.environ.get("YANDEX_DISK_TOKEN", "")
YANDEX_DISK_FOLDER = os.environ.get("YANDEX_DISK_FOLDER", "/annotatev2-photos")

S3_BUCKET = os.environ.get("S3_BUCKET", "")
S3_ACCESS_KEY_ID = os.environ.get("S3_ACCESS_KEY_ID", "")
S3_SECRET_ACCESS_KEY = os.environ.get("S3_SECRET_ACCESS_KEY", "")
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL", "") or None
S3_REGION = os.environ.get("S3_REGION", "auto")

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB - generous for a single high-res phone photo
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
