from __future__ import annotations

from ..registry import register
from .base import RawResult, SearchBackend


@register("search_backend", "duckduckgo")
class DuckDuckGoBackend(SearchBackend):
    """Free image search, no API key. Backed by the duckduckgo_search / ddgs package."""

    def search(self, query: str, max_results: int = 20) -> list[RawResult]:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            try:
                from ddgs import DDGS
            except ImportError as e:
                raise RuntimeError(
                    "Neither duckduckgo_search nor ddgs is installed; "
                    "run `pip install duckduckgo_search`"
                ) from e

        results: list[RawResult] = []
        with DDGS() as ddgs:
            for r in ddgs.images(query, max_results=max_results):
                results.append(
                    RawResult(
                        source_url=r.get("image", ""),
                        page_url=r.get("url", ""),
                        title=r.get("title", ""),
                        description=r.get("title", ""),
                        width=r.get("width", 0) or 0,
                        height=r.get("height", 0) or 0,
                    )
                )
        return results
