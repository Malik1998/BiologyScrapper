from __future__ import annotations

import json
from pathlib import Path

from ..filters.base import FilterContext
from ..models import ImageCandidate
from ..registry import get as registry_get
from ..registry import register
from .base import PipelineContext, Stage


@register("stage", "filter_chain")
class FilterChainStage(Stage):
    """Runs the configured ordered list of filters (heuristic / llm_align / vlm_verify /
    future custom filters) over each (subject, photo_type)'s candidates, then marks the
    top_k highest-scoring, non-filtered candidates as status="selected"."""

    name = "filter_chain"

    def run(self, ctx: PipelineContext) -> None:
        chain_cfg = self.params.get("chain", [])
        top_k = self.params.get("top_k", 4)

        active_filters = []
        for f_cfg in chain_cfg:
            if not f_cfg.get("enabled", True):
                continue
            filter_cls = registry_get("filter", f_cfg["type"])
            active_filters.append(filter_cls(**f_cfg.get("params", {})))

        for subject in ctx.iter_subjects():
            for photo_type in ctx.photo_types:
                raw_dir = Path("data/raw") / subject.id / photo_type
                if not raw_dir.exists():
                    continue

                candidates = _load_candidates(raw_dir)
                if not candidates:
                    continue

                person_label, _parent = subject.person_for(photo_type)
                fctx = FilterContext(
                    subject=subject, photo_type=photo_type, person_label=person_label, raw_dir=str(raw_dir)
                )

                for f in active_filters:
                    candidates = f.apply(candidates, fctx)

                _rank_and_select(candidates, top_k)

                for c in candidates:
                    sidecar = Path(c.local_path).with_suffix(Path(c.local_path).suffix + ".json")
                    sidecar.write_text(json.dumps(c.to_dict(), indent=2))

                n_selected = sum(1 for c in candidates if c.status == "selected")
                ctx.log(f"[filter_chain] {subject.id}/{photo_type}: {n_selected}/{len(candidates)} selected")

        ctx.state.save()


def _load_candidates(raw_dir: Path) -> list[ImageCandidate]:
    candidates = []
    for sidecar in sorted(raw_dir.glob("*.json")):
        try:
            candidates.append(ImageCandidate.from_dict(json.loads(sidecar.read_text())))
        except Exception:
            continue
    return candidates


def _score(c: ImageCandidate) -> float:
    if c.status == "filtered_out":
        return -1.0
    total, n = 0.0, 0
    llm_relevance = c.scores.get("llm_align", {}).get("relevance")
    if isinstance(llm_relevance, (int, float)):
        total += llm_relevance
        n += 1
    vlm_verdict = c.scores.get("vlm_verify", {}).get("verdict")
    if isinstance(vlm_verdict, (int, float)):
        total += vlm_verdict
        n += 1
    return total / n if n else 0.5  # neutral default when no scorer ran


def _rank_and_select(candidates: list[ImageCandidate], top_k: int) -> None:
    for c in candidates:
        if c.status != "filtered_out":
            c.status = "candidate"

    ranked = sorted(candidates, key=_score, reverse=True)
    selected = 0
    for c in ranked:
        if _score(c) < 0:
            continue
        if selected < top_k:
            c.status = "selected"
            selected += 1
