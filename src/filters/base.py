from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import ImageCandidate, Subject


@dataclass
class FilterContext:
    subject: Subject
    photo_type: str
    person_label: str
    raw_dir: str  # directory containing the downloaded images for this (subject, photo_type)


class Filter(ABC):
    name: str = "filter"

    def __init__(self, **params):
        self.params = params

    @abstractmethod
    def apply(self, candidates: list[ImageCandidate], ctx: FilterContext) -> list[ImageCandidate]:
        """Annotate candidates[i].scores[self.name] = {...} and/or set
        candidates[i].status = "filtered_out" to drop a candidate. Must not
        change the length or order semantics in a way other filters can't rely on."""
