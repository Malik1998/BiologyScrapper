from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class RawResult:
    source_url: str  # direct image URL
    page_url: str = ""
    title: str = ""
    description: str = ""
    width: int = 0
    height: int = 0


class SearchBackend(ABC):
    @abstractmethod
    def search(self, query: str, max_results: int = 20) -> list[RawResult]:
        ...
