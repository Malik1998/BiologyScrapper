"""Generate/refresh config/celebrities.json from a plain list of names.

For each name, runs a few DuckDuckGo web searches and asks an LLM (via
OpenRouter) to extract birth year, category, and parent identities from those
search results (src.research.research_person) -- the LLM is grounded in
search snippets rather than relying on its own memory.

This is how new subjects get added to the pipeline: add a name to
config/names.txt and re-run this script, rather than hand-writing JSON.

Usage:
    python -m scripts.build_celebrities_config
    python -m scripts.build_celebrities_config --names-file config/names.txt
    python -m scripts.build_celebrities_config --names "Tom Hanks" "Meryl Streep"
    python -m scripts.build_celebrities_config --overwrite   # re-research names already in the config

Requires OPENROUTER_API_KEY. Existing entries are preserved as-is unless
--overwrite is passed or the entry is for a name not yet in the config.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.llm.openrouter_client import OpenRouterClient
from src.research import research_person
from src.text_util import slugify

DEFAULT_METADATA = {
    "description": (
        "Source-of-truth list of subjects for the aging-prediction labeling dataset. "
        "Each subject needs 4 photos: self at 50-60, self at 30-40, mother at 50-60, "
        "father at 50-60."
    ),
    "photo_types": {
        "self_50_60": "Subject's own photo while aged 50-60",
        "self_30_40": "Subject's own photo while aged 30-40 (roughly 15-25 years earlier)",
        "mother_50_60": "Subject's mother's photo while aged 50-60",
        "father_50_60": "Subject's father's photo while aged 50-60",
    },
    "notes": (
        "birth_year/death_year are used by the pipeline to compute target year-ranges for "
        "each photo_type. confidence on parent entries reflects how sure we are of the "
        "parent's identity/name; 'low' or 'unknown' entries can be refreshed by re-running "
        "this script with --overwrite, or via the load_subjects research_unknown_parents option."
    ),
}

def research_subject(client: OpenRouterClient, model: str, name: str, subject_id: str) -> dict:
    parsed = research_person(client, model, name)
    if parsed.get("birth_year") is None:
        raise ValueError(
            f"could not determine birth_year from search results "
            f"(notes: {parsed.get('notes', '')!r}); add this subject manually"
        )
    return {
        "id": subject_id,
        "name": name,
        "category": parsed.get("category", "other"),
        "birth_year": parsed["birth_year"],
        "death_year": parsed.get("death_year"),
        "parents": parsed.get("parents") or {"mother": None, "father": None},
        "notes": parsed.get("notes", ""),
    }


def load_names(args: argparse.Namespace) -> list[str]:
    if args.names:
        return args.names
    names_path = Path(args.names_file)
    if not names_path.exists():
        sys.exit(f"Names file not found: {names_path}")
    return [
        line.strip()
        for line in names_path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def main(argv: list[str] | None = None) -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--names-file", default="config/names.txt", help="text file, one name per line")
    parser.add_argument("--names", nargs="+", help="names to add/refresh (overrides --names-file)")
    parser.add_argument("--output", default="config/celebrities.json")
    parser.add_argument("--model", default="google/gemini-2.5-flash")
    parser.add_argument(
        "--overwrite", action="store_true", help="re-research names that already exist in --output"
    )
    args = parser.parse_args(argv)

    names = load_names(args)

    output_path = Path(args.output)
    if output_path.exists():
        config = json.loads(output_path.read_text())
        config.setdefault("metadata", DEFAULT_METADATA)
    else:
        config = {"metadata": DEFAULT_METADATA, "celebrities": []}

    existing_by_id = {c["id"]: c for c in config.get("celebrities", [])}

    client = OpenRouterClient()
    if not client.available:
        sys.exit("OPENROUTER_API_KEY not set; cannot research subjects.")

    for name in names:
        subject_id = slugify(name)
        if subject_id in existing_by_id and not args.overwrite:
            print(f"[build_celebrities_config] {name}: already in config, skipping (use --overwrite to refresh)")
            continue

        print(f"[build_celebrities_config] researching {name}...")
        try:
            existing_by_id[subject_id] = research_subject(client, args.model, name, subject_id)
        except Exception as e:
            print(f"[build_celebrities_config] failed for {name}: {e}")

    config["celebrities"] = list(existing_by_id.values())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(config, indent=2))
    print(f"[build_celebrities_config] wrote {len(config['celebrities'])} subjects -> {output_path}")


if __name__ == "__main__":
    main()
