"""Sample a small test batch of parent-child pairs from KinFaceW-II only,
stratified evenly across the child's estimated age, for the FLR reliability
check (Step 2). Age comes from
../kinface_age_estimation/results/kinfacew_children_age_estimation.csv
(DeepFace age estimation run on the child photo of each pair only - parents'
ages were never estimated, so parent images get no age).

Sampling: group KinFaceW-II pairs by the child's predicted age (rounded to
an int), then round-robin across ages (youngest to oldest) taking one pair
per age per pass until --count pairs are picked, so ages with few available
pairs aren't over- or under-represented relative to their availability.

Like scripts/build_kinface_batch.py, this copies the sampled pairs into
data/kinface_photos/<relation>/ preserving KinFaceW's own filenames, and
writes data/annotations/batch.json - the fixed, ordered list every rater
scores. Refuses to overwrite an existing batch.json (pass --force) since
that would invalidate any in-progress/completed annotations - archive those
first if you really mean to resample.

Run with:
    .venv/bin/python -m scripts.build_kinface_ii_age_batch
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

RELATIONS = {
    "father-dau": {"parent": "father", "child": "daughter", "label": "Father-Daughter"},
    "father-son": {"parent": "father", "child": "son", "label": "Father-Son"},
    "mother-dau": {"parent": "mother", "child": "daughter", "label": "Mother-Daughter"},
    "mother-son": {"parent": "mother", "child": "son", "label": "Mother-Son"},
}

DEST_DIR = Path("data/kinface_photos")
BATCH_PATH = Path("data/annotations/batch.json")


def load_child_ages(csv_path: Path) -> list[dict]:
    """One row per KinFaceW-II pair: {relation, pair_id, child_age}."""
    rows = []
    with csv_path.open(newline="") as f:
        for row in csv.DictReader(f):
            if row["dataset"] != "KinFaceW-II" or row["status"] != "ok":
                continue
            rows.append({
                "relation": row["relation"],
                "pair_id": row["pair_id"],
                "child_age": round(float(row["predicted_age"])),
            })
    return rows


def stratified_sample_by_age(rows: list[dict], count: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    by_age: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_age[r["child_age"]].append(r)
    for bucket in by_age.values():
        rng.shuffle(bucket)

    ages_ascending = sorted(by_age)
    picked: list[dict] = []
    while len(picked) < count:
        progressed = False
        for age in ages_ascending:
            if len(picked) >= count:
                break
            bucket = by_age[age]
            if bucket:
                picked.append(bucket.pop())
                progressed = True
        if not progressed:
            break  # exhausted every age bucket before reaching `count`
    return picked


def build_batch(source_root: Path, csv_path: Path, count: int, seed: int) -> dict:
    rows = load_child_ages(csv_path)
    sampled = stratified_sample_by_age(rows, count, seed)

    DEST_DIR.mkdir(parents=True, exist_ok=True)
    images = []

    for pick in sampled:
        relation = pick["relation"]
        pair_id = pick["pair_id"]
        roles = RELATIONS[relation]
        dest_rel_dir = DEST_DIR / relation
        dest_rel_dir.mkdir(parents=True, exist_ok=True)

        for slot, role_key, age in (("1", "parent", None), ("2", "child", pick["child_age"])):
            filename = f"{pair_id}_{slot}.jpg"
            src = source_root / "images" / relation / filename
            if not src.exists():
                raise FileNotFoundError(f"Missing source image: {src}")
            dst = dest_rel_dir / filename
            shutil.copyfile(src, dst)
            images.append({
                "image_id": f"{relation}/{pair_id}_{slot}",
                "path": f"{relation}/{filename}",
                "relation": relation,
                "relation_label": roles["label"],
                "pair_index": pair_id,
                "role": role_key,
                "role_label": roles[role_key],
                "child_age": age,  # estimated age of the child; null for parent photos (never estimated)
            })

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source_root),
        "sampling": "stratified_by_child_age",
        "age_csv": str(csv_path),
        "count": count,
        "seed": seed,
        "images": images,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", default="../KinFaceW-II", help="KinFaceW-II dataset root (contains images/<relation>/)")
    p.add_argument(
        "--age-csv",
        default="../kinface_age_estimation/results/kinfacew_children_age_estimation.csv",
        help="DeepFace child-age estimation csv (see kinface_age_estimation/run_age_estimation.py)",
    )
    p.add_argument("--count", type=int, default=50, help="total pairs to sample, spread evenly across child ages")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--force", action="store_true", help="overwrite an existing batch.json")
    args = p.parse_args()

    if BATCH_PATH.exists() and not args.force:
        raise SystemExit(
            f"{BATCH_PATH} already exists - pass --force to resample. If people have already "
            "annotated against it, archive data/annotations/{{responses,raters.json,batch.json}} "
            "first so their work isn't silently invalidated."
        )

    source_root = Path(args.source).resolve()
    csv_path = Path(args.age_csv).resolve()
    if DEST_DIR.exists():
        shutil.rmtree(DEST_DIR)

    batch = build_batch(source_root, csv_path, args.count, args.seed)

    BATCH_PATH.parent.mkdir(parents=True, exist_ok=True)
    BATCH_PATH.write_text(json.dumps(batch, indent=2))

    n_pairs = len(batch["images"]) // 2
    ages = sorted({img["child_age"] for img in batch["images"] if img["child_age"] is not None})
    print(f"Wrote {len(batch['images'])} photos ({n_pairs} pairs) to {DEST_DIR}/")
    print(f"Child ages covered ({len(ages)} distinct): {ages}")
    print(f"Batch manifest: {BATCH_PATH}")


if __name__ == "__main__":
    main()
