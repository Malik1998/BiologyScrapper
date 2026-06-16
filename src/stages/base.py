from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from ..models import PHOTO_TYPES, Subject
from ..state import ProgressState


@dataclass
class PipelineContext:
    subjects: list[Subject]
    limits: dict[str, Any]
    config: dict[str, Any]
    state: ProgressState
    force: bool = False
    photo_types: list[str] = field(default_factory=lambda: list(PHOTO_TYPES))
    log: Callable[[str], None] = print

    def iter_subjects(self) -> list[Subject]:
        subj_limit = self.limits.get("subjects")
        subjects = self.subjects
        if isinstance(subj_limit, list):
            wanted = set(subj_limit)
            subjects = [s for s in subjects if s.id in wanted]
        elif isinstance(subj_limit, int):
            subjects = subjects[:subj_limit]
        return subjects


class Stage(ABC):
    name: str = "stage"

    def __init__(self, **params):
        self.params = params

    @abstractmethod
    def run(self, ctx: PipelineContext) -> None:
        ...
