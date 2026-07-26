"""Sample a small test batch of parent-child pairs from KinFaceW for the FLR
reliability check (Step 2). Copies the chosen pairs into data/kinface_photos/
preserving KinFaceW's own <relation>/<pair>_1.jpg (parent) / _2.jpg (child)
layout, and writes data/annotations/batch.json - the fixed, ordered list of
individual photos that every rater will independently score.

Run with:
    .venv/bin/python -m scripts.build_kinface_batch
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

RELATIONS = {
    "father-dau": {"parent": "father", "child": "daughter", "label": "Father-Daughter"},
    "father-son": {"parent": "father", "child": "son", "label": "Father-Son"},
    "mother-dau": {"parent": "mother", "child": "daughter", "label": "Mother-Daughter"},
    "mother-son": {"parent": "mother", "child": "son", "label": "Mother-Son"},
}

PAIR_RE = re.compile(r"^[a-z]+_(?P<idx>\d+)_(?P<slot>[12])\.jpg$", re.IGNORECASE)

DEST_DIR = Path("data/kinface_photos")
BATCH_PATH = Path("data/annotations/batch.json")


def discover_pairs(source_dir: Path, relation: str) -> dict[str, dict[str, Path]]:
    """pair index -> {"1": path, "2": path} for one relation folder."""
    pairs: dict[str, dict[str, Path]] = {}
    rel_dir = source_dir / relation
    for f in rel_dir.glob("*.jpg"):
        m = PAIR_RE.match(f.name)
        if not m:
            continue
        pairs.setdefault(m.group("idx"), {})[m.group("slot")] = f
    return {idx: slots for idx, slots in pairs.items() if "1" in slots and "2" in slots}


def build_batch(source_root: Path, per_relation: int, seed: int) -> dict:
    rng = random.Random(seed)
    images = []
    DEST_DIR.mkdir(parents=True, exist_ok=True)

    for relation, roles in RELATIONS.items():
        pairs = discover_pairs(source_root / "images", relation)
        if not pairs:
            raise FileNotFoundError(f"No pairs found for '{relation}' under {source_root}/images")
        chosen_idx = rng.sample(sorted(pairs), k=min(per_relation, len(pairs)))

        dest_rel_dir = DEST_DIR / relation
        dest_rel_dir.mkdir(parents=True, exist_ok=True)

        for idx in sorted(chosen_idx):
            slots = pairs[idx]
            for slot, role_key in (("1", "parent"), ("2", "child")):
                src = slots[slot]
                dst = dest_rel_dir / src.name
                shutil.copyfile(src, dst)
                image_id = f"{relation}/{src.stem}"
                images.append({
                    "image_id": image_id,
                    "path": f"{relation}/{src.name}",
                    "relation": relation,
                    "relation_label": roles["label"],
                    "pair_index": idx,
                    "role": role_key,
                    "role_label": roles[role_key],
                })

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source_root),
        "per_relation": per_relation,
        "seed": seed,
        "images": images,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", default="../KinFaceW-I", help="KinFaceW dataset root (contains images/<relation>/)")
    p.add_argument("--per-relation", type=int, default=5, help="pairs to sample per relation (x4 relations)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--force", action="store_true", help="overwrite an existing batch.json")
    args = p.parse_args()

    if BATCH_PATH.exists() and not args.force:
        raise SystemExit(f"{BATCH_PATH} already exists - pass --force to resample (this reshuffles the fixed batch raters are working through, so only do this before anyone has started).")

    source_root = Path(args.source).resolve()
    batch = build_batch(source_root, args.per_relation, args.seed)

    BATCH_PATH.parent.mkdir(parents=True, exist_ok=True)
    BATCH_PATH.write_text(json.dumps(batch, indent=2))

    n_pairs = len(batch["images"]) // 2
    print(f"Wrote {len(batch['images'])} photos ({n_pairs} pairs) to {DEST_DIR}/")
    print(f"Batch manifest: {BATCH_PATH}")


if __name__ == "__main__":
    main()
