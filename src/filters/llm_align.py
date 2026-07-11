from __future__ import annotations

import json

from ..json_util import extract_json
from ..llm.openrouter_client import OpenRouterClient
from ..models import ImageCandidate
from ..registry import register
from .base import Filter, FilterContext

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "relevance": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["relevance", "reason"],
    "additionalProperties": False,
}


@register("filter", "llm_align")
class LLMAlignFilter(Filter):
    """Cheap text-only relevance check using search result metadata (title/description/
    source page) before spending a vision call on the actual pixels. Requires
    OPENROUTER_API_KEY; no-ops (passes candidates through unscored) if absent."""

    name = "llm_align"

    def __init__(self, **params):
        super().__init__(**params)
        self.client = OpenRouterClient()
        self.model = self.params.get("model", "qwen/qwen3.6-flash")

    def apply(self, candidates: list[ImageCandidate], ctx: FilterContext) -> list[ImageCandidate]:
        if not self.client.available:
            for c in candidates:
                c.scores.setdefault("llm_align", {"skipped": "OPENROUTER_API_KEY not set"})
            return candidates

        for c in candidates:
            if c.status == "filtered_out":
                continue
            lo, hi = c.target_year_range or ("?", "?")
            prompt = (
                f'We are looking for a photo of "{ctx.person_label}" taken roughly between '
                f"{lo} and {hi}.\n"
                "Candidate image metadata:\n"
                f"- title: {c.title}\n"
                f"- description: {c.description}\n"
                f"- source page: {c.page_url}\n\n"
                "Based only on this metadata (you cannot see the image), how likely is it that "
                "this image actually depicts that specific person around that time period? "
                'Respond with strict JSON only: {"relevance": <0-1 float>, "reason": "<short reason>"}'
            )
            try:
                raw = self.client.chat_text(
                    self.model, prompt, response_schema=RESPONSE_SCHEMA, response_schema_name="llm_align"
                )
                parsed = json.loads(extract_json(raw))
            except Exception as e:
                parsed = {"relevance": 0.5, "reason": f"llm_align error: {e}"}
            c.scores["llm_align"] = parsed

        return candidates
