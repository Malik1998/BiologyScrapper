"""Data access for the /annotate FLR reliability test (Step 2).

Storage layout (all under data/, gitignored - see web/data_access.py for the
sibling module this mirrors):

    data/kinface_photos/<relation>/<pair>_<1|2>.jpg   - copied by
        scripts/build_kinface_batch.py, same layout KinFaceW itself uses.
    data/annotations/batch.json                       - fixed, ordered list
        of individual photos every rater works through (see build_kinface_batch.py).
    data/annotations/raters.json                       - slug -> display name.
    data/annotations/responses/<rater_slug>/<image_id with "/" -> "__">.json
        - one file per (rater, photo): scores + comment + timestamp.

The batch is identical for every rater by construction, so "two of us score
the same batch independently" (the point of Step 2) doesn't need a clever
assignment algorithm: each rater just walks the shared list in order, and
/api/annotate/next skips whatever that rater has already submitted.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DATA_DIR = Path("data")
PHOTOS_DIR = DATA_DIR / "kinface_photos"
ANNOTATIONS_DIR = DATA_DIR / "annotations"
BATCH_PATH = ANNOTATIONS_DIR / "batch.json"
RATERS_PATH = ANNOTATIONS_DIR / "raters.json"
RESPONSES_DIR = ANNOTATIONS_DIR / "responses"
SCHEMA_PATH = Path("config/annotation_schema.json")


class BatchNotBuilt(Exception):
    pass


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    if not slug:
        raise ValueError("name must contain at least one letter or digit")
    return slug


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def load_batch() -> dict:
    if not BATCH_PATH.exists():
        raise BatchNotBuilt(
            "No batch yet - run `.venv/bin/python -m scripts.build_kinface_ii_age_batch` "
            "(or scripts.build_kinface_batch) first."
        )
    return json.loads(BATCH_PATH.read_text())


def _response_path(rater_slug: str, image_id: str) -> Path:
    safe_image_id = image_id.replace("/", "__")
    return RESPONSES_DIR / rater_slug / f"{safe_image_id}.json"


def _register_rater(rater_slug: str, display_name: str) -> None:
    raters = {}
    if RATERS_PATH.exists():
        raters = json.loads(RATERS_PATH.read_text())
    entry = raters.get(rater_slug, {"first_seen": datetime.now(timezone.utc).isoformat()})
    entry["display_name"] = display_name
    raters[rater_slug] = entry
    RATERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RATERS_PATH.write_text(json.dumps(raters, indent=2))


def _completed_image_ids(rater_slug: str) -> set[str]:
    return set(_load_responses(rater_slug))


def _load_responses(rater_slug: str) -> dict[str, dict]:
    """image_id -> saved response, for one rater."""
    rater_dir = RESPONSES_DIR / rater_slug
    if not rater_dir.exists():
        return {}
    out = {}
    for f in rater_dir.glob("*.json"):
        try:
            record = json.loads(f.read_text())
            out[record["image_id"]] = record
        except Exception:
            continue
    return out


def image_url(image: dict) -> str:
    return f"/data/kinface_photos/{image['path']}"


def next_image_for(display_name: str) -> Optional[dict]:
    """The next photo this rater hasn't submitted yet, or None if they've
    finished the whole shared batch."""
    rater_slug = slugify(display_name)
    _register_rater(rater_slug, display_name.strip())
    batch = load_batch()
    done = _completed_image_ids(rater_slug)
    for image in batch["images"]:
        if image["image_id"] not in done:
            out = dict(image)
            out["image_url"] = image_url(image)
            return out
    return None


def progress_for(display_name: str) -> dict:
    rater_slug = slugify(display_name)
    batch = load_batch()
    done = _completed_image_ids(rater_slug)
    total = len(batch["images"])
    return {"done": len(done), "total": total, "complete": len(done) >= total}


def submit_response(display_name: str, image_id: str, scores: dict, comment: str) -> dict:
    rater_slug = slugify(display_name)
    batch = load_batch()
    valid_ids = {img["image_id"] for img in batch["images"]}
    if image_id not in valid_ids:
        raise ValueError(f"Unknown image_id for this batch: {image_id}")

    _register_rater(rater_slug, display_name.strip())

    record = {
        "rater": display_name.strip(),
        "rater_slug": rater_slug,
        "image_id": image_id,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "scores": scores,
        "comment": comment,
    }
    path = _response_path(rater_slug, image_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2))
    return record


def my_responses(display_name: str) -> list[dict]:
    """This rater's own saved responses, in batch order, each with the image
    details merged in - powers the "my scored photos" review/edit panel."""
    rater_slug = slugify(display_name)
    batch = load_batch()
    responses = _load_responses(rater_slug)
    out = []
    for image in batch["images"]:
        response = responses.get(image["image_id"])
        if response is None:
            continue
        out.append({
            **image,
            "image_url": image_url(image),
            "scores": response["scores"],
            "comment": response["comment"],
            "submitted_at": response["submitted_at"],
        })
    return out


def team_progress() -> dict:
    """Per-image rater counts + per-rater completion, so the team can see
    when a photo has enough independent scores to check agreement on."""
    batch = load_batch()
    raters = {}
    if RATERS_PATH.exists():
        raters = json.loads(RATERS_PATH.read_text())

    counts: dict[str, list[str]] = {img["image_id"]: [] for img in batch["images"]}
    for rater_slug in raters:
        for image_id in sorted(_completed_image_ids(rater_slug)):
            if image_id in counts:
                counts[image_id].append(raters[rater_slug]["display_name"])

    images = [
        {
            "image_id": img["image_id"],
            "raters": counts[img["image_id"]],
            "rater_count": len(counts[img["image_id"]]),
        }
        for img in batch["images"]
    ]
    return {
        "total_images": len(batch["images"]),
        "raters": [
            {"display_name": v["display_name"], **progress_for(v["display_name"])}
            for v in raters.values()
        ],
        "images": images,
    }
