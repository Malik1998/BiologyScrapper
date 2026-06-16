from __future__ import annotations

from PIL import Image

from ..models import ImageCandidate
from ..registry import register
from .base import Filter, FilterContext


@register("filter", "heuristic")
class HeuristicFilter(Filter):
    """Pure-Python checks (resolution, aspect ratio) - always available, no API needed."""

    name = "heuristic"

    def apply(self, candidates: list[ImageCandidate], ctx: FilterContext) -> list[ImageCandidate]:
        min_width = self.params.get("min_width", 400)
        min_height = self.params.get("min_height", 400)
        max_aspect_ratio = self.params.get("max_aspect_ratio", 2.5)

        for c in candidates:
            width, height = c.width, c.height
            if not width or not height:
                try:
                    with Image.open(c.local_path) as im:
                        width, height = im.size
                    c.width, c.height = width, height
                except Exception:
                    c.scores["heuristic"] = {"pass": False, "reasons": ["unreadable image"]}
                    c.status = "filtered_out"
                    continue

            reasons = []
            if width < min_width or height < min_height:
                reasons.append(f"resolution {width}x{height} below minimum {min_width}x{min_height}")
            aspect_ratio = max(width, height) / max(1, min(width, height))
            if aspect_ratio > max_aspect_ratio:
                reasons.append(f"aspect ratio {aspect_ratio:.2f} exceeds max {max_aspect_ratio}")

            passed = not reasons
            c.scores["heuristic"] = {"pass": passed, "reasons": reasons, "width": width, "height": height}
            if not passed:
                c.status = "filtered_out"

        return candidates
