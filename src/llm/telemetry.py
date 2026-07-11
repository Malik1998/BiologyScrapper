"""Optional Langfuse tracing for OpenRouter calls.

Fully opt-in: if the `langfuse` package isn't installed, or LANGFUSE_PUBLIC_KEY /
LANGFUSE_SECRET_KEY aren't set, `LangfuseTracer` degrades to a no-op. Tracing
must never turn into a hard dependency or break an actual LLM call, so every
Langfuse SDK interaction is wrapped and logged rather than raised.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager

logger = logging.getLogger(__name__)

try:
    from langfuse import get_client as _get_langfuse_client
except ImportError:
    _get_langfuse_client = None


def _redact_content(content):
    if not isinstance(content, list):
        return content
    redacted = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "image_url":
            redacted.append({"type": "image_url", "image_url": "<elided>"})
        else:
            redacted.append(part)
    return redacted


def _redact_messages(messages: list[dict]) -> list[dict]:
    return [{**m, "content": _redact_content(m.get("content"))} for m in messages]


class _NullSpan:
    def success(self, data, usage):
        pass

    def error(self):
        pass


class _LangfuseSpan:
    def __init__(self, observation):
        self._observation = observation

    def success(self, data: dict, usage: dict):
        try:
            output = data["choices"][0]["message"]["content"]
        except Exception:
            output = data
        self._observation.update(
            output=output,
            usage_details={
                "input": usage.get("prompt_tokens"),
                "output": usage.get("completion_tokens"),
                "total": usage.get("total_tokens"),
            },
        )

    def error(self):
        self._observation.update(level="ERROR")


class LangfuseTracer:
    def __init__(self):
        self.enabled = bool(
            _get_langfuse_client
            and os.environ.get("LANGFUSE_PUBLIC_KEY")
            and os.environ.get("LANGFUSE_SECRET_KEY")
        )
        self._client = _get_langfuse_client() if self.enabled else None

    @contextmanager
    def generation(self, model: str, messages: list[dict], kwargs: dict):
        if not self.enabled:
            yield _NullSpan()
            return

        cm = None
        try:
            cm = self._client.start_as_current_observation(
                as_type="generation",
                name="openrouter-chat",
                model=model,
                input=_redact_messages(messages),
                metadata=kwargs or None,
            )
            observation = cm.__enter__()
        except Exception:
            logger.warning("langfuse tracing unavailable, continuing without it", exc_info=True)
            yield _NullSpan()
            return

        try:
            yield _LangfuseSpan(observation)
        finally:
            cm.__exit__(None, None, None)
            try:
                self._client.flush()
            except Exception:
                logger.warning("langfuse flush failed", exc_info=True)
