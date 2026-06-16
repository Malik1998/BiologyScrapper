from __future__ import annotations

import os
from typing import Optional

import requests

from ..registry import register
from .base import RawResult, SearchBackend


@register("search_backend", "bing")
class BingBackend(SearchBackend):
    """Bing Image Search v7 (Azure Cognitive Services). Requires BING_SEARCH_KEY."""

    ENDPOINT = "https://api.bing.microsoft.com/v7.0/images/search"

    def __init__(self, api_key: Optional[str] = None, endpoint: Optional[str] = None):
        self.api_key = api_key or os.environ.get("BING_SEARCH_KEY")
        self.endpoint = endpoint or self.ENDPOINT

    def search(self, query: str, max_results: int = 20) -> list[RawResult]:
        if not self.api_key:
            raise RuntimeError("BING_SEARCH_KEY not set")
        resp = requests.get(
            self.endpoint,
            headers={"Ocp-Apim-Subscription-Key": self.api_key},
            params={"q": query, "count": max_results},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        results: list[RawResult] = []
        for r in data.get("value", [])[:max_results]:
            results.append(
                RawResult(
                    source_url=r.get("contentUrl", ""),
                    page_url=r.get("hostPageUrl", ""),
                    title=r.get("name", ""),
                    description=r.get("name", ""),
                    width=r.get("width", 0) or 0,
                    height=r.get("height", 0) or 0,
                )
            )
        return results
