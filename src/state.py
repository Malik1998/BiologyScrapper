"""Resumability: tracks which (subject, photo_type, stage) units of work are done
so re-running the pipeline skips expensive search/download/LLM calls unless --force."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ProgressState:
    def __init__(self, path: str = "state/progress.json"):
        self.path = Path(path)
        self._data: dict[str, Any] = {}
        if self.path.exists():
            self._data = json.loads(self.path.read_text())

    @staticmethod
    def _key(subject_id: str, photo_type: str, stage: str) -> str:
        return f"{subject_id}:{photo_type}:{stage}"

    def is_done(self, subject_id: str, photo_type: str, stage: str) -> bool:
        entry = self._data.get(self._key(subject_id, photo_type, stage))
        return bool(entry and entry.get("status") == "done")

    def mark_done(self, subject_id: str, photo_type: str, stage: str, **extra: Any) -> None:
        self._data[self._key(subject_id, photo_type, stage)] = {"status": "done", **extra}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2))
