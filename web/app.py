"""Interactive review app for non-programmers: browse downloaded candidates per
subject/photo_type, select the 4 final photos, crop them, then export.

Run with:
    .venv/bin/uvicorn web.app:app --reload
then open http://127.0.0.1:8000/
"""

from __future__ import annotations

import io
import json
import logging
import os
import queue
import threading
import zipfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel
from starlette.requests import Request

from src.models import CURRENT_YEAR, PHOTO_TYPES
from src.stages.export_local import ExportLocalStage
from src.stages.generate_html import GenerateHtmlStage

from . import add_subject as add_subject_flow
from . import data_access as da

app = FastAPI(title="Aging dataset review")

Path("data").mkdir(exist_ok=True)
app.mount("/data", StaticFiles(directory="data"), name="data")
app.mount("/static", StaticFiles(directory="web/static"), name="static")

templates = Jinja2Templates(env=Environment(
    loader=FileSystemLoader("web/templates"),
    cache_size=0,  # workaround: Jinja2 cache key includes unhashable dict on Python 3.14
))


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/library")
def library(request: Request):
    rows = []
    for subject in da.list_subjects():
        counts = {}
        for photo_type in PHOTO_TYPES:
            candidates = da.load_candidates(subject.id, photo_type)
            counts[photo_type] = {
                "total": len(candidates),
                "selected": sum(1 for c in candidates if c.status == "selected"),
            }
        rows.append({"subject": subject, "counts": counts})
    return templates.TemplateResponse(
        request, "library.html", {"rows": rows, "photo_types": PHOTO_TYPES}
    )


@app.get("/add")
def add_page(request: Request):
    return templates.TemplateResponse(request, "add.html")


@app.get("/api/add_subject/stream")
def add_subject_stream(name: str):
    name = name.strip()
    if not name:
        raise HTTPException(400, "name is required")

    def event_stream():
        events: "queue.Queue[tuple[str, ...]]" = queue.Queue()

        def log(message: str) -> None:
            events.put(("log", message))

        def on_images(subject_id: str, photo_type: str, cards: list[dict]) -> None:
            events.put(("images", subject_id, photo_type, cards))

        def worker() -> None:
            try:
                subject_id = add_subject_flow.run_add_subject(name, log, on_images=on_images)
                events.put(("done", subject_id))
            except Exception as e:
                events.put(("error", str(e)))

        threading.Thread(target=worker, daemon=True).start()

        while True:
            ev = events.get()
            kind = ev[0]
            if kind == "log":
                event = {"type": "log", "message": ev[1]}
            elif kind == "images":
                event = {"type": "images", "subject_id": ev[1], "photo_type": ev[2], "cards": ev[3]}
            elif kind == "done":
                event = {"type": "done", "subject_id": ev[1]}
            else:
                event = {"type": "error", "message": ev[1]}
            yield f"data: {json.dumps(event)}\n\n"
            if kind in ("done", "error"):
                break

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/subject/{subject_id}/data")
def subject_data_api(subject_id: str):
    subject = da.get_subject(subject_id)
    if subject is None:
        raise HTTPException(404, f"Unknown subject: {subject_id}")

    sections = []
    for photo_type in PHOTO_TYPES:
        candidates = da.load_candidates(subject_id, photo_type)
        person_label, _ = subject.person_for(photo_type)
        year_range = subject.year_range(photo_type)
        cards = [
            {
                "id": c.id,
                "image_url": da.to_url(c.cropped_path or c.local_path),
                "original_url": da.to_url(c.local_path),
                "status": c.status,
                "width": c.width,
                "height": c.height,
                "page_url": c.page_url,
                "has_crop": bool(c.cropped_path),
                "title": c.title,
                "description": c.description,
                "query": c.query,
            }
            for c in candidates
        ]
        sections.append({
            "photo_type": photo_type,
            "person_label": person_label,
            "year_range": list(year_range) if year_range else None,
            "cards": cards,
        })

    age = CURRENT_YEAR - subject.birth_year if not subject.death_year else None

    return {
        "id": subject.id,
        "name": subject.name,
        "birth_year": subject.birth_year,
        "death_year": subject.death_year,
        "age": age,
        "current_year": CURRENT_YEAR,
        "category": subject.category,
        "parents": {
            role: (
                {"name": p.name, "birth_year": p.birth_year, "death_year": p.death_year}
                if p
                else None
            )
            for role, p in subject.parents.items()
        },
        "sections": sections,
    }


@app.get("/subject/{subject_id}")
def subject_page(request: Request, subject_id: str):
    subject = da.get_subject(subject_id)
    if subject is None:
        raise HTTPException(404, f"Unknown subject: {subject_id}")

    sections = []
    for photo_type in PHOTO_TYPES:
        cards = [
            {
                "candidate": c,
                "image_url": da.to_url(c.cropped_path or c.local_path),
                "original_url": da.to_url(c.local_path),
            }
            for c in da.load_candidates(subject_id, photo_type)
        ]
        person_label, _ = subject.person_for(photo_type)
        sections.append({"photo_type": photo_type, "person_label": person_label, "cards": cards})

    return templates.TemplateResponse(
        request, "subject.html", {"subject": subject, "sections": sections}
    )


class SelectRequest(BaseModel):
    subject_id: str
    photo_type: str
    candidate_id: str
    selected: bool


@app.post("/api/select")
def api_select(req: SelectRequest):
    candidate = da.load_candidate(req.subject_id, req.photo_type, req.candidate_id)
    candidate.status = "selected" if req.selected else "candidate"
    da.save_candidate(candidate)
    return {"status": candidate.status}


class CropRequest(BaseModel):
    subject_id: str
    photo_type: str
    candidate_id: str
    left: float
    top: float
    right: float
    bottom: float


@app.post("/api/crop")
def api_crop(req: CropRequest):
    from PIL import Image

    candidate = da.load_candidate(req.subject_id, req.photo_type, req.candidate_id)
    src_path = Path(candidate.local_path)
    if not src_path.exists():
        raise HTTPException(404, f"Image file missing: {src_path}")

    with Image.open(src_path) as im:
        left = max(0, min(round(req.left), im.width - 1))
        top = max(0, min(round(req.top), im.height - 1))
        right = max(left + 1, min(round(req.right), im.width))
        bottom = max(top + 1, min(round(req.bottom), im.height))
        cropped = im.convert("RGB").crop((left, top, right, bottom))
        cropped_path = src_path.with_name(f"{src_path.stem}_crop.jpg")
        cropped.save(cropped_path, "JPEG", quality=90)

    candidate.crop_box = {"left": left, "top": top, "right": right, "bottom": bottom}
    candidate.cropped_path = str(cropped_path)
    da.save_candidate(candidate)
    return {"cropped_url": da.to_url(candidate.cropped_path)}


@app.post("/api/uncrop")
def api_uncrop(req: SelectRequest):  # only subject_id/photo_type/candidate_id are used
    candidate = da.load_candidate(req.subject_id, req.photo_type, req.candidate_id)
    if candidate.cropped_path:
        Path(candidate.cropped_path).unlink(missing_ok=True)
    candidate.cropped_path = None
    candidate.crop_box = None
    da.save_candidate(candidate)
    return {"image_url": da.to_url(candidate.local_path)}


@app.get("/api/export/zip")
def export_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for subject in da.list_subjects():
            for photo_type in PHOTO_TYPES:
                for c in da.load_candidates(subject.id, photo_type):
                    if c.status != "selected":
                        continue
                    src = Path(c.cropped_path or c.local_path)
                    if not src.exists():
                        continue
                    zf.write(src, f"{subject.id}/{photo_type}/{src.name}")
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=selected_photos.zip"},
    )


@app.post("/api/export/local")
def export_local():
    ctx = da.build_pipeline_context()
    ExportLocalStage(output_dir="data/selected").run(ctx)
    return {"status": "ok", "output_dir": "data/selected"}


@app.post("/api/export/html")
def export_html():
    ctx = da.build_pipeline_context()
    GenerateHtmlStage(output="data/review/index.html").run(ctx)
    return {"status": "ok", "path": "/data/review/index.html"}
