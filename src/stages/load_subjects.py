from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from ..llm.openrouter_client import OpenRouterClient
from ..models import Subject
from ..registry import register
from ..research import research_parent
from .base import PipelineContext, Stage


@register("stage", "load_subjects")
class LoadSubjectsStage(Stage):
    """Loads config/celebrities.json into ctx.subjects, optionally enriches
    low-confidence/unknown parent identities via search-grounded LLM lookups,
    and writes the resolved subject + computed year-ranges to data/subjects/<id>.json."""

    name = "load_subjects"

    def run(self, ctx: PipelineContext) -> None:
        config_path = self.params.get("config", "config/celebrities.json")
        data = json.loads(Path(config_path).read_text())
        subjects = [Subject.from_dict(d) for d in data["celebrities"]]

        if self.params.get("research_unknown_parents"):
            client = OpenRouterClient()
            if client.available:
                model = self.params.get("research_model", "google/gemini-2.5-flash")
                for subject in subjects:
                    _research_parents(subject, client, model, ctx.log)
            else:
                ctx.log(
                    "[load_subjects] research_unknown_parents=true but OPENROUTER_API_KEY "
                    "is not set; skipping identity research"
                )

        out_dir = Path("data/subjects")
        out_dir.mkdir(parents=True, exist_ok=True)
        for subject in subjects:
            payload = subject.to_dict()
            payload["year_ranges"] = {
                pt: (list(yr) if (yr := subject.year_range(pt)) else None) for pt in ctx.photo_types
            }
            (out_dir / f"{subject.id}.json").write_text(json.dumps(payload, indent=2))

        ctx.subjects = subjects
        ctx.log(f"[load_subjects] resolved {len(subjects)} subjects -> {out_dir}")


def _research_parents(subject: Subject, client: OpenRouterClient, model: str, log: Callable[[str], None]) -> None:
    for role in ("mother", "father"):
        parent = subject.parents.get(role)
        if parent is None or parent.confidence not in ("low", "unknown"):
            continue

        try:
            parsed = research_parent(client, model, subject.name, role)
        except Exception as e:
            log(f"[load_subjects] identity research failed for {subject.name}'s {role}: {e}")
            continue

        if parsed.get("name"):
            parent.name = parsed["name"]
            parent.birth_year = parsed.get("birth_year") or parent.birth_year
            parent.death_year = parsed.get("death_year") or parent.death_year
            parent.confidence = parsed.get("confidence", "low")
            log(
                f"[load_subjects] {subject.name}'s {role}: found {parent.name} "
                f"(confidence={parent.confidence})"
            )
