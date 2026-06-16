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

RESEARCH_MODEL = "google/gemini-2.5-flash"
CONFIG_PATH = Path("config/celebrities.json")


def ensure_subject_in_config(name: str, log: Callable[[str], None]) -> str:
    """Return the subject id for `name`, adding it to config/celebrities.json
    via search-grounded research if it isn't already there."""
    subject_id = slugify(name)
    config = json.loads(CONFIG_PATH.read_text())
    existing = {c["id"]: c for c in config["celebrities"]}

    if subject_id in existing:
        log(f"'{name}' is already in config/celebrities.json, reusing it.")
        return subject_id

    log(f"Searching the web for information about '{name}'...")
    client = OpenRouterClient()
    if not client.available:
        raise RuntimeError("OPENROUTER_API_KEY is not set; cannot research new subjects.")

    parsed = research_person(client, RESEARCH_MODEL, name)
    if parsed.get("birth_year") is None:
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
        f"mother={mother.get('name') or 'unknown'}, father={father.get('name') or 'unknown'}"
    )

    existing[subject_id] = entry
    config["celebrities"] = list(existing.values())
    CONFIG_PATH.write_text(json.dumps(config, indent=2))
    log(f"Added '{name}' to config/celebrities.json as '{subject_id}'.")
    return subject_id


def run_add_subject(name: str, log: Callable[[str], None]) -> str:
    """Research (if new) and run the pipeline for one subject. Returns the
    subject id so the caller can show/redirect to its results page."""
    subject_id = ensure_subject_in_config(name, log)
    run_pipeline_for_subject(subject_id, log=log)
    return subject_id
