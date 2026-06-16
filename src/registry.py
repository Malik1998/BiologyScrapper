"""Tiny plugin registry so pipeline.yaml can reference stages/search backends/filters
by name without the orchestrator importing every implementation directly."""

from __future__ import annotations

_REGISTRY: dict[str, dict[str, type]] = {
    "stage": {},
    "search_backend": {},
    "filter": {},
}


def register(kind: str, name: str):
    def deco(cls: type) -> type:
        _REGISTRY.setdefault(kind, {})[name] = cls
        return cls

    return deco


def get(kind: str, name: str) -> type:
    try:
        return _REGISTRY[kind][name]
    except KeyError as e:
        available = list(_REGISTRY.get(kind, {}).keys())
        raise KeyError(f"No {kind} registered as '{name}'. Available: {available}") from e


def available(kind: str) -> list[str]:
    return list(_REGISTRY.get(kind, {}).keys())
