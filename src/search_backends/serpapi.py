from __future__ import annotations

import os
from typing import Optional

import requests

from ..registry import register
from .base import RawResult, SearchBackend


@register("search_backend", "serpapi")
class SerpApiBackend(SearchBackend):
    """Google Images via SerpAPI. Requires SERPAPI_KEY."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("SERPAPI_KEY")

    def search(self, query: str, max_results: int = 20) -> list[RawResult]:
        if not self.api_key:
            raise RuntimeError("SERPAPI_KEY not set")
        resp = requests.get(
            "https://serpapi.com/search",
            params={
                "engine": "google_images",
                "q": query,
                "api_key": self.api_key,
                "num": max_results,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        results: list[RawResult] = []
        for r in data.get("images_results", [])[:max_results]:
            results.append(
                RawResult(
                    source_url=r.get("original", r.get("thumbnail", "")),
                    page_url=r.get("link", ""),
                    title=r.get("title", ""),
                    description=r.get("title", ""),
                    width=r.get("original_width", 0) or 0,
                    height=r.get("original_height", 0) or 0,
                )
            )
        return results
