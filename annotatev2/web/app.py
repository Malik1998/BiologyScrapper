"""Photo-collection app for the parent-child aging study (Step 1 of Medha's
2026-08-14 email): one family sits down once and uploads 4 photos -
themselves now, themselves older, mother, father (config/photo_types.json;
one parent is optional, see web/config.OPTIONAL_GROUP).

Run with:
    .venv/bin/uvicorn web.app:app --host 0.0.0.0 --port 8001
then send participants the link to http://<host>:8001/
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader
from starlette.requests import Request

from web import config, data_access, face_check, sync_worker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.SUBMISSIONS_DIR.mkdir(parents=True, exist_ok=True)
    config.PHOTO_FILES_DIR.mkdir(parents=True, exist_ok=True)
    task = asyncio.create_task(sync_worker.sweep_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="annotatev2 - photo collection", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

templates = Jinja2Templates(env=Environment(
    loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
))


# ── Admin auth ───────────────────────────────────────────────────────────
# The photos are real participants' faces, so /admin/... is HTTP Basic-gated
# and simply 404s (not 401 - don't advertise it exists) until both
# ADMIN_USER and ADMIN_PASSWORD are set in .env.

_security = HTTPBasic(auto_error=False)


def require_admin(credentials: HTTPBasicCredentials | None = Depends(_security)) -> None:
    """Gate on ADMIN_USER/ADMIN_PASSWORD (.env) - but if neither is set,
    /admin is wide open with no login (a deliberate "backdoor" for local
    testing before real participant data exists). Set both before pointing
    this at anything real - see README "Admin dashboard"."""
    if not (config.ADMIN_USER and config.ADMIN_PASSWORD):
        return
    ok = bool(credentials) and secrets.compare_digest(
        credentials.username, config.ADMIN_USER
    ) and secrets.compare_digest(credentials.password, config.ADMIN_PASSWORD)
    if not ok:
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})


# ── Participant-facing flow ─────────────────────────────────────────────

@app.get("/")
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/photo_types")
def api_photo_types():
    return {"photo_types": data_access.load_photo_types(), "optional_group": list(config.OPTIONAL_GROUP)}


@app.post("/api/submissions")
async def api_create_submission(payload: dict):
    try:
        submission = data_access.create_submission(family_label=str(payload.get("family_label", "")))
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    return {"submission_id": submission.id}


@app.get("/api/submissions/{submission_id}/photos")
def api_submission_photos(submission_id: str):
    submission = data_access.get_submission(submission_id)
    if submission is None:
        raise HTTPException(404, "unknown submission")
    photos = data_access.list_photos(submission_id=submission_id)
    return {"photos": [{"photo_id": p.id, "photo_type": p.photo_type} for p in photos]}


@app.post("/api/photos")
async def api_upload_photo(
    background_tasks: BackgroundTasks,
    submission_id: str = Form(...),
    photo_type: str = Form(...),
    crop: str = Form(...),  # JSON string: {x, y, width, height}
    image: UploadFile = File(...),
):
    submission = data_access.get_submission(submission_id)
    if submission is None:
        raise HTTPException(404, "unknown submission")

    valid_types = {p["id"] for p in data_access.load_photo_types()}
    if photo_type not in valid_types:
        raise HTTPException(400, f"unknown photo_type {photo_type!r}")

    if image.content_type not in config.ALLOWED_CONTENT_TYPES:
        raise HTTPException(400, f"unsupported content type {image.content_type!r}")

    try:
        crop_data = json.loads(crop) if crop else None
        if crop_data is not None:
            for key in ("x", "y", "width", "height"):
                float(crop_data[key])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise HTTPException(400, "crop must be JSON with numeric x, y, width, height")

    image_bytes = await image.read()
    if len(image_bytes) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "image too large")
    if not image_bytes:
        raise HTTPException(400, "empty upload")

    face_result = face_check.check(image_bytes)
    if face_result.enabled and not face_result.passed:
        return JSONResponse(
            status_code=422,
            content={
                "error": "face_check_failed",
                "detail": face_result.detail,
                "face_check": face_result.__dict__,
            },
        )

    try:
        photo = await asyncio.to_thread(
            data_access.save_photo,
            submission=submission,
            photo_type=photo_type,
            image_bytes=image_bytes,
            crop=crop_data,
            face_check_result=face_result,
        )
    except Exception:
        logger.exception("failed to save photo for submission %s photo_type %s", submission_id, photo_type)
        raise HTTPException(500, "failed to save photo")

    # Re-uploading the same slot replaces the previous photo, so a slot
    # never ends up with two stored images.
    for existing in data_access.list_photos(submission_id=submission_id):
        if existing.photo_type == photo_type and existing.id != photo.id:
            await asyncio.to_thread(data_access.delete_photo, existing.id)

    if config.REMOTE_STORAGE_BACKEND != "none":
        background_tasks.add_task(sync_worker.sync_one, photo.id)

    return {"photo_id": photo.id, "face_check": photo.face_check}


# ── Admin (HTTP Basic, see require_admin) ───────────────────────────────

@app.get("/admin")
def admin_page(request: Request, _: None = Depends(require_admin)):
    submissions = data_access.list_submissions()
    all_photos = data_access.list_photos()
    photo_types = data_access.load_photo_types()
    type_ids = [t["id"] for t in photo_types]

    photos_by_submission: dict[str, list] = {}
    for photo in all_photos:
        photos_by_submission.setdefault(photo.submission_id, []).append(photo)

    rows = []
    for submission in submissions:
        photos = sorted(
            photos_by_submission.get(submission.id, []),
            key=lambda p: type_ids.index(p.photo_type) if p.photo_type in type_ids else 999,
        )
        rows.append({
            "submission": submission,
            "photos": photos,
            "done_count": len(photos),
            "total_count": len(type_ids),
        })

    return templates.TemplateResponse(request, "admin.html", {
        "rows": rows,
        "total_photos": len(all_photos),
        "remote_backend": config.REMOTE_STORAGE_BACKEND,
        "is_open": not (config.ADMIN_USER and config.ADMIN_PASSWORD),
    })


@app.get("/admin/photo/{photo_id}")
def admin_photo(photo_id: str, _: None = Depends(require_admin)):
    photo = data_access.get_photo(photo_id)
    if photo is None:
        raise HTTPException(404)
    path = data_access.photo_file_path(photo_id)
    if not path.exists():
        raise HTTPException(404, "image file missing on disk")
    return Response(content=path.read_bytes(), media_type="image/jpeg")


@app.get("/admin/photo/{photo_id}/cropped")
def admin_photo_cropped(photo_id: str, _: None = Depends(require_admin)):
    try:
        data = data_access.render_cropped(photo_id)
    except FileNotFoundError:
        raise HTTPException(404)
    return Response(content=data, media_type="image/jpeg")
