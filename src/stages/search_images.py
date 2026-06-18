from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image

from ..models import ImageCandidate
from ..registry import get as registry_get
from ..registry import register
from .base import PipelineContext, Stage

EXT_BY_CONTENT_TYPE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


@register("stage", "search_images")
class SearchImagesStage(Stage):
    """Bulk image discovery + download. For each (subject, photo_type), builds a
    query from the subject/parent name and computed target year-range, runs the
    configured search backend, and saves each image + a metadata sidecar JSON
    under data/raw/<subject_id>/<photo_type>/. No filtering/scoring happens here."""

    name = "search_images"

    def run(self, ctx: PipelineContext) -> None:
        backend_name = self.params.get("backend", "duckduckgo")
        max_results = self.params.get("max_results_per_query", 20)
        year_step = self.params.get("year_step", 3)
        backend = registry_get("search_backend", backend_name)()
        images_limit = ctx.limits.get("images_per_type")

        for subject in ctx.iter_subjects():
            for photo_type in ctx.photo_types:
                if not ctx.force and ctx.state.is_done(subject.id, photo_type, self.name):
                    ctx.log(f"[search_images] skip {subject.id}/{photo_type} (already done)")
                    continue

                person_label, _ = subject.person_for(photo_type)
                year_range = subject.year_range(photo_type)
                if year_range is None:
                    ctx.log(f"[search_images] {subject.id}/{photo_type}: no valid year range, skipping")
                    continue

                # Warn when parent birth year was estimated
                if photo_type in ("mother_50_60", "father_50_60"):
                    role = "mother" if photo_type.startswith("mother") else "father"
                    parent = subject.parents.get(role)
                    if parent is None or parent.birth_year is None:
                        ctx.log(
                            f"[search_images] {subject.id}/{photo_type}: "
                            f"parent birth year unknown — using estimated range {year_range}"
                        )

                out_dir = Path("data/raw") / subject.id / photo_type
                out_dir.mkdir(parents=True, exist_ok=True)

                years = _year_points(year_range, year_step)
                ctx.log(
                    f"[search_images] {subject.id}/{photo_type}: "
                    f"{len(years)} queries for {person_label!r} — years {years}"
                )

                downloaded = 0
                for year in years:
                    if images_limit and downloaded >= images_limit:
                        break
                    query = _build_query(person_label, year)
                    ctx.log(f"[search_images]   query={query!r}")
                    try:
                        results = backend.search(query, max_results=max_results)
                    except Exception as e:
                        ctx.log(f"[search_images]   search failed: {e}")
                        continue

                    for raw in results:
                        if images_limit and downloaded >= images_limit:
                            break
                        if _download(raw, subject, photo_type, person_label, year_range, query, out_dir):
                            downloaded += 1

                ctx.state.mark_done(subject.id, photo_type, self.name, downloaded=downloaded)
                ctx.log(f"[search_images] {subject.id}/{photo_type}: downloaded {downloaded} image(s)")

                if ctx.on_images and downloaded > 0:
                    cards = _load_cards(out_dir)
                    ctx.on_images(subject.id, photo_type, cards)

        ctx.state.save()


def _load_cards(out_dir: Path) -> list[dict]:
    cards = []
    for sidecar in sorted(out_dir.glob("*.json")):
        try:
            data = json.loads(sidecar.read_text())
            cards.append({
                "id": data["id"],
                "image_url": data.get("cropped_path") or data["local_path"],
                "title": data.get("title", ""),
                "description": data.get("description", ""),
                "width": data.get("width"),
                "height": data.get("height"),
                "status": data.get("status", "candidate"),
            })
        except Exception:
            continue
    return cards


def _year_points(year_range: tuple[int, int], step: int) -> list[int]:
    """Return evenly-spaced years within [lo, hi], always including hi."""
    lo, hi = year_range
    years = list(range(lo, hi + 1, max(1, step)))
    if years[-1] != hi:
        years.append(hi)
    return years


def _build_query(person_label: str, year: int) -> str:
    return f"{person_label} {year} photo"


def _download(raw, subject, photo_type, person_label, year_range, query, out_dir: Path) -> bool:
    try:
        resp = requests.get(raw.source_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        content = resp.content
    except Exception:
        return False

    digest = hashlib.sha1(content).hexdigest()[:16]
    ext = _guess_ext(raw.source_url, resp.headers.get("Content-Type", ""))
    local_path = out_dir / f"{digest}.{ext}"

    if local_path.exists():
        return False  # already have this exact image (dedup by content hash)

    local_path.write_bytes(content)
    try:
        with Image.open(local_path) as im:
            width, height = im.size
    except Exception:
        local_path.unlink(missing_ok=True)
        return False

    candidate = ImageCandidate(
        id=digest,
        subject_id=subject.id,
        photo_type=photo_type,
        person_label=person_label,
        target_year_range=year_range,
        source_url=raw.source_url,
        page_url=raw.page_url,
        local_path=str(local_path),
        width=width,
        height=height,
        query=query,
        title=raw.title,
        description=raw.description,
    )
    sidecar = local_path.with_suffix(local_path.suffix + ".json")
    sidecar.write_text(json.dumps(candidate.to_dict(), indent=2))
    return True


def _guess_ext(url: str, content_type: str) -> str:
    path = urlparse(url).path
    if "." in path:
        ext = path.rsplit(".", 1)[-1].lower()
        if ext == "jpeg":
            return "jpg"
        if ext in ("jpg", "png", "webp", "gif"):
            return ext
    return EXT_BY_CONTENT_TYPE.get(content_type.split(";")[0].strip(), "jpg")
