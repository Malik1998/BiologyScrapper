"""Transparent relay for OpenRouter's chat-completions endpoint.

Run this on a server that can reach openrouter.ai directly (i.e. not blocked
at the network/edge level), then point OPENROUTER_BASE_URL at it from a
server where OpenRouter itself is blocked - see README > "LLM telemetry".

The relay never sees or stores an API key of its own: it forwards whatever
Authorization header the caller sends straight through to OpenRouter, so the
real key stays in the caller's .env only. Has no auth of its own - keep it
off the open internet (firewall to trusted IPs only).

Run with:
    pip install fastapi "uvicorn[standard]" requests
    uvicorn relay.app:app --host 0.0.0.0 --port 8787
"""

from __future__ import annotations

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/v1/chat/completions")
async def chat_completions(request: Request):
    auth = request.headers.get("authorization")
    if not auth:
        raise HTTPException(401, "missing Authorization header")

    body = await request.body()
    resp = requests.post(
        OPENROUTER_API_URL,
        headers={"Authorization": auth, "Content-Type": "application/json"},
        data=body,
        timeout=90,
    )
    return JSONResponse(content=resp.json(), status_code=resp.status_code)
