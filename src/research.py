"""Search-grounded identity research.

Used by scripts/build_celebrities_config.py and the web "add subject" flow to
look up a person's birth year, category, and parents' identities. Instead of
asking an LLM to recall facts from memory (prone to hallucination), this runs
a few DuckDuckGo text searches first and asks the LLM to extract structured
facts *only* from those search results.
"""

from __future__ import annotations

import json

from .json_util import extract_json
from .llm.openrouter_client import OpenRouterClient


# ddgs's default "duckduckgo" text backend requires a TLS 1.3 client context that
# some Python/OpenSSL builds reject outright; these backends need no API keys and
# work reliably across environments.
TEXT_SEARCH_BACKENDS = "wikipedia,yahoo,yandex,brave"


def web_search_snippets(query: str, max_results: int = 5) -> list[dict]:
    """Plain-text web search. Returns [{title, body, href}, ...]."""
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results, backend=TEXT_SEARCH_BACKENDS))


def _gather_snippets(queries: list[str], max_results_per_query: int = 4) -> list[dict]:
    snippets = []
    for query in queries:
        try:
            snippets.extend(web_search_snippets(query, max_results=max_results_per_query))
        except Exception:
            continue
    return snippets


def _format_snippets(snippets: list[dict]) -> str:
    if not snippets:
        return "(no search results found)"
    return "\n\n".join(
        f"[{i}] {s.get('title', '')}\n{s.get('body', '')}\nSource: {s.get('href', '')}"
        for i, s in enumerate(snippets, 1)
    )


PERSON_PROMPT = """\
You are researching the public figure "{name}" for a dataset about visible aging \
across generations. The dataset needs photos of this person and their parents at \
specific ages, so you need their birth year and their parents' identities.

Base your answer ONLY on the web search results below. Do not use any other \
knowledge, and do not invent details that aren't supported by these results.

Search results:
{context}

Respond with strict JSON only, matching exactly this schema:
{{
  "category": "<actor|athlete|politician|royal|other>",
  "birth_year": <int or null>,
  "death_year": <int or null>,
  "parents": {{
    "mother": {{"name": <string or null>, "birth_year": <int or null>, "death_year": <int or null>, "confidence": "<high|medium|low|unknown>"}},
    "father": {{"name": <string or null>, "birth_year": <int or null>, "death_year": <int or null>, "confidence": "<high|medium|low|unknown>"}}
  }},
  "notes": "<short note on caveats, e.g. parents not public figures, or what the search results didn't cover>"
}}

Use "confidence": "high" only if a search result directly states the parent's name \
AND approximate birth year. If a field isn't supported by the search results, use \
null and "confidence": "unknown".
"""


def research_person(client: OpenRouterClient, model: str, name: str) -> dict:
    """Search the web for `name` and ask the LLM to extract a structured profile
    (category, birth/death years, parents) grounded in those results."""
    snippets = _gather_snippets([f"{name} biography born", f"{name} parents mother father"])
    prompt = PERSON_PROMPT.format(name=name, context=_format_snippets(snippets))
    raw = client.chat_text(model, prompt)
    return json.loads(extract_json(raw))


PARENT_PROMPT = """\
You are researching the identity of {subject}'s {role} for a dataset about visible \
aging across generations.

Base your answer ONLY on the web search results below. Do not use any other \
knowledge, and do not invent details that aren't supported by these results.

Search results:
{context}

Respond with strict JSON only, matching exactly this schema:
{{"name": <string or null>, "birth_year": <int or null>, "death_year": <int or null>, "confidence": "<high|medium|low|unknown>"}}

Use "confidence": "high" only if a search result directly states the {role}'s name \
AND approximate birth year. If the {role}'s identity isn't supported by the search \
results, set "name" to null and "confidence" to "unknown".
"""


def research_parent(client: OpenRouterClient, model: str, subject_name: str, role: str) -> dict:
    """Search the web for `subject_name`'s mother/father and ask the LLM to extract
    their identity, grounded in those results."""
    snippets = _gather_snippets([f"{subject_name} {role} name", f"{subject_name} parents {role}"])
    prompt = PARENT_PROMPT.format(subject=subject_name, role=role, context=_format_snippets(snippets))
    raw = client.chat_text(model, prompt)
    return json.loads(extract_json(raw))
