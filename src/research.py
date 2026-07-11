"""Search-grounded identity research.

Used by scripts/build_celebrities_config.py and the web "add subject" flow to
look up a person's birth year, category, and parents' identities. Instead of
asking an LLM to recall facts from memory (prone to hallucination), this runs
a few DuckDuckGo text searches first and asks the LLM to extract structured
facts *only* from those search results.
"""

from __future__ import annotations

import json
import re

from .json_util import extract_json
from .llm.openrouter_client import OpenRouterClient

# Fallback when the LLM extraction step fails outright (rate limit, network
# block, etc.) but the web search itself succeeded: search snippets often
# already contain the birth year in plain text ("born June 4, 1975", "(1975-)"),
# so a birth year alone is enough to let search_images run instead of losing
# the search results entirely.
_BIRTH_YEAR_RE = re.compile(r"\bborn\b[^.\n]{0,40}?\b(1[89]\d{2}|20[0-4]\d)\b", re.IGNORECASE)


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


def _guess_birth_year(snippets: list[dict]) -> int | None:
    match = _BIRTH_YEAR_RE.search(_format_snippets(snippets))
    return int(match.group(1)) if match else None


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


PARENT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": ["string", "null"]},
        "birth_year": {"type": ["integer", "null"]},
        "death_year": {"type": ["integer", "null"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low", "unknown"]},
    },
    "required": ["name", "birth_year", "death_year", "confidence"],
    "additionalProperties": False,
}

PERSON_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": ["actor", "athlete", "politician", "royal", "other"]},
        "birth_year": {"type": ["integer", "null"]},
        "death_year": {"type": ["integer", "null"]},
        "parents": {
            "type": "object",
            "properties": {"mother": PARENT_SCHEMA, "father": PARENT_SCHEMA},
            "required": ["mother", "father"],
            "additionalProperties": False,
        },
        "notes": {"type": "string"},
    },
    "required": ["category", "birth_year", "death_year", "parents", "notes"],
    "additionalProperties": False,
}


def research_person(client: OpenRouterClient, model: str, name: str) -> dict:
    """Search the web for `name` and ask the LLM to extract a structured profile
    (category, birth/death years, parents) grounded in those results.

    If the LLM step itself fails (rate limit, network block, bad response),
    falls back to a plain regex birth-year guess from the search snippets
    already gathered, so search_images can still run instead of losing the
    whole subject."""
    snippets = _gather_snippets([f"{name} biography born", f"{name} parents mother father"])
    prompt = PERSON_PROMPT.format(name=name, context=_format_snippets(snippets))
    try:
        raw = client.chat_text(model, prompt, response_schema=PERSON_SCHEMA, response_schema_name="person")
        return json.loads(extract_json(raw))
    except Exception as e:
        birth_year = _guess_birth_year(snippets)
        return {
            "category": "other",
            "birth_year": birth_year,
            "death_year": None,
            "parents": {"mother": None, "father": None},
            "notes": (
                f"LLM research failed ({e}); "
                + (f"birth year {birth_year} guessed from search snippets." if birth_year else "birth year unknown.")
            ),
        }


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
    raw = client.chat_text(model, prompt, response_schema=PARENT_SCHEMA, response_schema_name="parent")
    return json.loads(extract_json(raw))
