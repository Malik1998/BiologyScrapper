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
