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
        backend = registry_get("search_backend", backend_name)()
        images_limit = ctx.limits.get("images_per_type")

        for subject in ctx.iter_subjects():
            for photo_type in ctx.photo_types:
                if not ctx.force and ctx.state.is_done(subject.id, photo_type, self.name):
                    ctx.log(f"[search_images] skip {subject.id}/{photo_type} (already done)")
                    continue

                person_label, _parent = subject.person_for(photo_type)
                year_range = subject.year_range(photo_type)
                if year_range is None:
                    ctx.log(f"[search_images] {subject.id}/{photo_type}: no valid year range, skipping")
                    continue

                query = _build_query(person_label, year_range)
                out_dir = Path("data/raw") / subject.id / photo_type
                out_dir.mkdir(parents=True, exist_ok=True)

                ctx.log(f"[search_images] {subject.id}/{photo_type}: query={query!r}")
                try:
                    results = backend.search(query, max_results=max_results)
                except Exception as e:
                    ctx.log(f"[search_images] search failed for {query!r}: {e}")
                    continue

                downloaded = 0
                for raw in results:
                    if images_limit and downloaded >= images_limit:
                        break
                    if _download(raw, subject, photo_type, person_label, year_range, query, out_dir):
                        downloaded += 1

                ctx.state.mark_done(subject.id, photo_type, self.name, downloaded=downloaded)
                ctx.log(f"[search_images] {subject.id}/{photo_type}: downloaded {downloaded} image(s)")

        ctx.state.save()


def _build_query(person_label: str, year_range: tuple[int, int]) -> str:
    lo, hi = year_range
    return f"{person_label} {lo}" if lo == hi else f"{person_label} {lo}-{hi}"


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
