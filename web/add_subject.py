"""On-demand "add a new subject" flow for the review app.

Given a free-text name typed into the web UI:
1. If the name isn't already in config/celebrities.json, research it via
   search-grounded LLM lookup (src.research.research_person) and add it.
2. Run the pipeline (search_images -> filter_chain -> export_local ->
   generate_html) for just that subject.

Progress is reported through a `log(message)` callback so the web app can
stream it to the browser while the work runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from src.llm.openrouter_client import OpenRouterClient
from src.pipeline import run_pipeline_for_subject
from src.research import research_person
from src.text_util import slugify

RESEARCH_MODEL = "qwen/qwen3.6-flash"
CONFIG_PATH = Path("config/celebrities.json")


def _needs_research(entry: dict) -> bool:
    """Return True if the cached entry is missing parent birth years for both parents."""
    parents = entry.get("parents") or {}
    mother = parents.get("mother") or {}
    father = parents.get("father") or {}
    return mother.get("birth_year") is None and father.get("birth_year") is None


def ensure_subject_in_config(name: str, log: Callable[[str], None]) -> str:
    """Return the subject id for `name`.

    Always re-researches from the web when invoked via the site, so that
    stale cached entries with missing parent birth years get updated.
    Falls back to the cached entry only if the LLM client is unavailable.
    """
    subject_id = slugify(name)
    config = json.loads(CONFIG_PATH.read_text())
    existing = {c["id"]: c for c in config["celebrities"]}

    client = OpenRouterClient()
    if not client.available:
        if subject_id in existing:
            log(f"OPENROUTER_API_KEY not set — reusing cached entry for '{name}'.")
            return subject_id
        raise RuntimeError("OPENROUTER_API_KEY is not set; cannot research new subjects.")

    cached = existing.get(subject_id)
    if cached and not _needs_research(cached):
        log(f"'{name}' already in config with complete parent info, skipping re-research.")
        return subject_id

    if cached:
        log(f"'{name}' found in config but parent birth years are missing — re-researching…")
    else:
        log(f"Searching the web for information about '{name}'…")

    try:
        parsed = research_person(client, RESEARCH_MODEL, name)
    except Exception as e:
        if cached:
            log(f"Re-research failed ({e}) — keeping cached entry for '{name}'.")
            return subject_id
        raise RuntimeError(
            f"Web research for '{name}' failed ({e}). Add this subject to "
            "config/celebrities.json manually, or retry once OpenRouter is reachable."
        ) from e

    if parsed.get("birth_year") is None:
        if cached:
            log(f"Re-research found no birth year — keeping cached entry for '{name}'.")
            return subject_id
        raise RuntimeError(
            f"Could not determine a birth year for '{name}' from web search "
            f"(notes: {parsed.get('notes', '')!r}). Add this subject to "
            "config/celebrities.json manually."
        )

    entry = {
        "id": subject_id,
        "name": name,
        "category": parsed.get("category", "other"),
        "birth_year": parsed["birth_year"],
        "death_year": parsed.get("death_year"),
        "parents": parsed.get("parents") or {"mother": None, "father": None},
        "notes": parsed.get("notes", ""),
    }
    mother = (entry["parents"] or {}).get("mother") or {}
    father = (entry["parents"] or {}).get("father") or {}
    log(
        f"Found '{name}': category={entry['category']}, born {entry['birth_year']}; "
        f"mother={mother.get('name') or 'unknown'} "
        f"(b.{mother.get('birth_year') or '?'}), "
        f"father={father.get('name') or 'unknown'} "
        f"(b.{father.get('birth_year') or '?'})"
    )

    existing[subject_id] = entry
    config["celebrities"] = list(existing.values())
    CONFIG_PATH.write_text(json.dumps(config, indent=2))
    log(f"{'Updated' if cached else 'Added'} '{name}' in config/celebrities.json.")
    return subject_id


def run_add_subject(
    name: str,
    log: Callable[[str], None],
    on_images: Callable[[str, str, list[dict]], None] | None = None,
) -> str:
    """Research (if new) and run the pipeline for one subject. Returns the
    subject id so the caller can show/redirect to its results page."""
    subject_id = ensure_subject_in_config(name, log)
    run_pipeline_for_subject(subject_id, log=log, on_images=on_images)
    return subject_id


def run_add_subjects(
    names: list[str],
    log: Callable[[str], None],
    on_images: Callable[[str, str, list[dict]], None] | None = None,
    on_subject_done: Callable[[str, str, str, str | None], None] | None = None,
) -> list[dict]:
    """Research and run the pipeline for a batch of subjects, one at a time.

    A failure on one name is logged and skipped rather than aborting the rest
    of the batch. `on_subject_done(name, subject_id, status, error)` fires
    after each name, with status "ok" or "error" (subject_id is "" on error).
    Returns a list of {"name", "subject_id", "status", "error"} results.
    """
    results = []
    total = len(names)
    for i, name in enumerate(names, start=1):
        log(f"[{i}/{total}] Starting \"{name}\"…")
        try:
            subject_id = run_add_subject(name, log, on_images=on_images)
            results.append({"name": name, "subject_id": subject_id, "status": "ok", "error": None})
            log(f"[{i}/{total}] Done \"{name}\" -> {subject_id}")
            if on_subject_done:
                on_subject_done(name, subject_id, "ok", None)
        except Exception as e:
            log(f"[{i}/{total}] FAILED \"{name}\": {e}")
            results.append({"name": name, "subject_id": "", "status": "error", "error": str(e)})
            if on_subject_done:
                on_subject_done(name, "", "error", str(e))
    return results
