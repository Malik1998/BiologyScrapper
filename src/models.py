from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

CURRENT_YEAR = datetime.date.today().year

PHOTO_TYPES = ["self_50_60", "self_30_40", "mother_50_60", "father_50_60"]


@dataclass
class ParentInfo:
    name: Optional[str] = None
    birth_year: Optional[int] = None
    death_year: Optional[int] = None
    confidence: str = "unknown"

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> Optional["ParentInfo"]:
        if d is None:
            return None
        return cls(
            name=d.get("name"),
            birth_year=d.get("birth_year"),
            death_year=d.get("death_year"),
            confidence=d.get("confidence", "unknown"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Subject:
    id: str
    name: str
    category: str
    birth_year: int
    death_year: Optional[int]
    parents: dict[str, Optional[ParentInfo]]
    notes: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Subject":
        parents_d = d.get("parents") or {}
        return cls(
            id=d["id"],
            name=d["name"],
            category=d.get("category", ""),
            birth_year=d["birth_year"],
            death_year=d.get("death_year"),
            parents={
                "mother": ParentInfo.from_dict(parents_d.get("mother")),
                "father": ParentInfo.from_dict(parents_d.get("father")),
            },
            notes=d.get("notes", ""),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "birth_year": self.birth_year,
            "death_year": self.death_year,
            "parents": {
                role: (parent.to_dict() if parent else None)
                for role, parent in self.parents.items()
            },
            "notes": self.notes,
        }

    def person_for(self, photo_type: str) -> tuple[str, Optional[ParentInfo]]:
        """Return (display name to search for, ParentInfo or None) for a photo_type."""
        if photo_type.startswith("self_"):
            return self.name, None
        if photo_type == "mother_50_60":
            parent = self.parents.get("mother")
            label = parent.name if parent and parent.name else f"{self.name}'s mother"
            return label, parent
        if photo_type == "father_50_60":
            parent = self.parents.get("father")
            label = parent.name if parent and parent.name else f"{self.name}'s father"
            return label, parent
        raise ValueError(f"Unknown photo_type: {photo_type}")

    def year_range(
        self, photo_type: str, current_year: int = CURRENT_YEAR
    ) -> Optional[tuple[int, int]]:
        """Compute the [start, end] year window for a photo_type, clamped to the
        subject's lifespan and the current year. Returns None if no sensible
        window exists (e.g. parent identity/birth year unknown, or the person
        died before reaching the target age range)."""
        if photo_type in ("self_50_60", "self_30_40"):
            birth_year, death_year = self.birth_year, self.death_year
        elif photo_type in ("mother_50_60", "father_50_60"):
            role = "mother" if photo_type.startswith("mother") else "father"
            parent = self.parents.get(role)
            if parent is None or parent.birth_year is None:
                return None
            birth_year, death_year = parent.birth_year, parent.death_year
        else:
            raise ValueError(f"Unknown photo_type: {photo_type}")

        if photo_type.endswith("30_40"):
            lo, hi = birth_year + 30, birth_year + 40
        else:
            lo, hi = birth_year + 50, birth_year + 60

        hi = min(hi, current_year)
        if death_year is not None:
            hi = min(hi, death_year)
        if hi < lo:
            return None
        return (lo, hi)


@dataclass
class ImageCandidate:
    id: str
    subject_id: str
    photo_type: str
    person_label: str
    target_year_range: Optional[tuple[int, int]]
    source_url: str
    page_url: str = ""
    local_path: str = ""
    width: int = 0
    height: int = 0
    query: str = ""
    title: str = ""
    description: str = ""
    scores: dict[str, Any] = field(default_factory=dict)
    status: str = "candidate"  # candidate | filtered_out | selected
    crop_box: Optional[dict[str, float]] = None  # {left, top, right, bottom} in source pixel coords
    cropped_path: Optional[str] = None  # set once a crop has been saved via the review app

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.target_year_range is not None:
            d["target_year_range"] = list(self.target_year_range)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ImageCandidate":
        d = dict(d)
        tyr = d.get("target_year_range")
        d["target_year_range"] = tuple(tyr) if tyr else None
        return cls(**d)
