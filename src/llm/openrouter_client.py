"""Thin OpenRouter client used by the optional llm_align / vlm_verify filters and
the load_subjects identity-research step. Every consumer checks `.available`
first so the pipeline runs fine with no API key configured."""

from __future__ import annotations

import base64
import mimetypes
import os
from typing import Optional

import requests

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def chat(self, model: str, messages: list[dict], **kwargs) -> dict:
        if not self.available:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        resp = requests.post(
            OPENROUTER_API_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={"model": model, "messages": messages, **kwargs},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    def chat_text(self, model: str, prompt: str, system: Optional[str] = None, **kwargs) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        result = self.chat(model, messages, **kwargs)
        return result["choices"][0]["message"]["content"]

    def chat_vision(
        self, model: str, prompt: str, image_path: str, system: Optional[str] = None, **kwargs
    ) -> str:
        mime, _ = mimetypes.guess_type(image_path)
        mime = mime or "image/jpeg"
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            }
        )
        result = self.chat(model, messages, **kwargs)
        return result["choices"][0]["message"]["content"]
