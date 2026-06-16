from __future__ import annotations

import json

from ..json_util import extract_json
from ..llm.openrouter_client import OpenRouterClient
from ..models import ImageCandidate
from ..registry import register
from .base import Filter, FilterContext


@register("filter", "vlm_verify")
class VLMVerifyFilter(Filter):
    """Vision check on the actual downloaded image: identity match, estimated age,
    and basic quality flags. Requires OPENROUTER_API_KEY; no-ops if absent."""

    name = "vlm_verify"

    def __init__(self, **params):
        super().__init__(**params)
        self.client = OpenRouterClient()
        self.model = self.params.get("model", "google/gemini-2.5-flash")

    def apply(self, candidates: list[ImageCandidate], ctx: FilterContext) -> list[ImageCandidate]:
        if not self.client.available:
            for c in candidates:
                c.scores.setdefault("vlm_verify", {"skipped": "OPENROUTER_API_KEY not set"})
            return candidates

        for c in candidates:
            if c.status == "filtered_out":
                continue
            lo, hi = c.target_year_range or ("?", "?")
            prompt = (
                f'Look at this image. We want a usable photo of "{ctx.person_label}" '
                f"taken when they were roughly the age they'd be in {lo}-{hi}.\n"
                "Respond with strict JSON only, no markdown:\n"
                "{\n"
                '  "identity_match": "yes" | "no" | "unsure",\n'
                '  "estimated_age_or_year": "<best guess>",\n'
                '  "single_person_visible": true | false,\n'
                '  "face_clearly_visible": true | false,\n'
                '  "quality_ok": true | false,\n'
                '  "verdict": <0-1 float, overall usability score>,\n'
                '  "reason": "<short reason>"\n'
                "}"
            )
            try:
                raw = self.client.chat_vision(self.model, prompt, c.local_path)
                parsed = json.loads(extract_json(raw))
            except Exception as e:
                parsed = {"verdict": 0.5, "reason": f"vlm_verify error: {e}"}
            c.scores["vlm_verify"] = parsed

        return candidates
