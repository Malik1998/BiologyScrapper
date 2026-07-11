"""Read/write helpers shared by the FastAPI review app. Operates on the same
data/raw/<subject>/<photo_type>/<id>.<ext>.json sidecar files the CLI pipeline
produces, so the web app and `python -m src.pipeline run` stay in sync."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from src.models import ImageCandidate, Subject
from src.stages.base import PipelineContext
from src.state import ProgressState

DATA_DIR = Path("data")
RAW_DIR = DATA_DIR / "raw"
SUBJECTS_DIR = DATA_DIR / "subjects"
META_SCHEMA_PATH = Path("config/image_meta_schema.json")

ROLE_BY_PHOTO_TYPE = {
    "self_50_60": "self",
    "self_30_40": "self",
    "self_with_parents_30_40": "self_with_parents",
    "mother_50_60": "mother",
    "father_50_60": "father",
}


def list_subjects() -> list[Subject]:
    subjects = []
    for f in sorted(SUBJECTS_DIR.glob("*.json")):
        d = json.loads(f.read_text())
        d.pop("year_ranges", None)
        subjects.append(Subject.from_dict(d))
    return subjects


def get_subject(subject_id: str) -> Optional[Subject]:
    path = SUBJECTS_DIR / f"{subject_id}.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text())
    d.pop("year_ranges", None)
    return Subject.from_dict(d)


def candidates_dir(subject_id: str, photo_type: str) -> Path:
    return RAW_DIR / subject_id / photo_type


def load_candidates(subject_id: str, photo_type: str) -> list[ImageCandidate]:
    directory = candidates_dir(subject_id, photo_type)
    if not directory.exists():
        return []
    candidates = []
    for sidecar in sorted(directory.glob("*.json")):
        try:
            candidates.append(ImageCandidate.from_dict(json.loads(sidecar.read_text())))
        except Exception:
            continue
    return candidates


def _sidecar_path(subject_id: str, photo_type: str, candidate_id: str) -> Path:
    directory = candidates_dir(subject_id, photo_type)
    matches = list(directory.glob(f"{candidate_id}.*.json"))
    if not matches:
        raise FileNotFoundError(f"No sidecar for {subject_id}/{photo_type}/{candidate_id}")
    return matches[0]


def load_candidate(subject_id: str, photo_type: str, candidate_id: str) -> ImageCandidate:
    sidecar = _sidecar_path(subject_id, photo_type, candidate_id)
    return ImageCandidate.from_dict(json.loads(sidecar.read_text()))


def save_candidate(candidate: ImageCandidate) -> None:
    sidecar = _sidecar_path(candidate.subject_id, candidate.photo_type, candidate.id)
    sidecar.write_text(json.dumps(candidate.to_dict(), indent=2))


def to_url(path: str) -> str:
    """Map a local 'data/...' filesystem path to the URL served by the /data static mount."""
    return "/" + Path(path).as_posix()


def build_pipeline_context() -> PipelineContext:
    """Minimal context for re-running export_local / generate_html stages on demand."""
    return PipelineContext(subjects=list_subjects(), limits={}, config={}, state=ProgressState(), force=False)


def load_meta_schema() -> list[dict]:
    """The configurable list of per-image metadata fields shown in the review
    app's Meta modal. Edit config/image_meta_schema.json to add/remove fields
    - no code changes needed."""
    return json.loads(META_SCHEMA_PATH.read_text())["fields"]


def compute_meta_suggestions(subject: Subject, photo_type: str, candidate: ImageCandidate) -> dict:
    """Best-effort defaults for the fields in the schema that declare a
    `source`, derived from context we already know when searching for this
    photo (e.g. "this is condition 50-60 mother of subject born <year>").
    Visual attributes (smiling, beard, ...) are deliberately never guessed."""
    role = ROLE_BY_PHOTO_TYPE.get(photo_type)

    year_range = candidate.target_year_range or subject.year_range(photo_type)
    year = round(sum(year_range) / 2) if year_range else None

    birth_year = None
    if role in ("self", "self_with_parents"):
        birth_year = subject.birth_year
    elif role in ("mother", "father"):
        parent = subject.parents.get(role)
        birth_year = (parent.birth_year if parent else None) or (subject.birth_year - 27)

    age = (year - birth_year) if (year is not None and birth_year is not None) else None

    suggestions = {"estimated_year": year, "role_from_photo_type": role, "estimated_age": age}
    return {
        field["key"]: suggestions[field["source"]]
        for field in load_meta_schema()
        if field.get("source") in suggestions and suggestions[field["source"]] is not None
    }


def save_candidate_meta(subject_id: str, photo_type: str, candidate_id: str, meta: dict) -> ImageCandidate:
    candidate = load_candidate(subject_id, photo_type, candidate_id)
    candidate.meta = meta
    save_candidate(candidate)
    return candidate
