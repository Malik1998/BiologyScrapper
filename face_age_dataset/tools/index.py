"""Aggregate per-person meta.json into one index plus a readable report."""

import json
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
DATA = os.path.join(ROOT, "dataset")

SLOTS = ["subject_now", "subject_young", "father_40s", "mother_40s"]


def build():
    people = []
    for slug in sorted(os.listdir(DATA)):
        mp = os.path.join(DATA, slug, "meta.json")
        if os.path.isfile(mp):
            people.append(json.load(open(mp)))

    index = {
        "generated_for_ages": {"subject": [40, 50], "parents": [40, 50],
                               "subject_young": [20, 30]},
        "slot_meaning": {
            "subject_now": "the person today, aged 40-50",
            "subject_young": "the same person aged 20-30",
            "father_40s": "their father aged 40-50",
            "mother_40s": "their mother aged 40-50",
        },
        "verification": {
            "age": "date_taken minus birth date; date_precision says how exact",
            "date_source": "exif | category_year | category_override | category_only",
            "date_conflict": "true when EXIF disagreed with curator categories "
                             "(digitised archives) and the category year won",
            "identity_cosine": "SFace similarity to the Wikidata P18 reference; "
                               "this is how the right face is picked out of a group",
        },
        "counts": {
            "people": len(people),
            "full_4_slots": sum(1 for p in people if p.get("complete_slots") == 4),
            "minimum_set": sum(1 for p in people if p.get("has_minimum_set")),
        },
        "people": [],
    }
    for p in people:
        index["people"].append({
            "slug": p["slug"],
            "subject": p["subject"]["name"],
            "complete_slots": p.get("complete_slots", 0),
            "has_minimum_set": p.get("has_minimum_set", False),
            "slots": {s: {
                "status": p["slots"].get(s, {}).get("status"),
                "age": p["slots"].get(s, {}).get("age_at_photo"),
                "file": p["slots"].get(s, {}).get("file"),
                "identity_cosine": p["slots"].get(s, {}).get("identity_cosine"),
                "reason": p["slots"].get(s, {}).get("reason"),
            } for s in SLOTS},
        })
    json.dump(index, open(os.path.join(DATA, "index.json"), "w"),
              ensure_ascii=False, indent=2)

    lines = [f"{'person':<26}{'now':>7}{'young':>8}{'father':>9}{'mother':>9}   set"]
    lines.append("-" * 68)
    for p in index["people"]:
        def cell(s):
            d = p["slots"][s]
            return str(d["age"]) if d["status"] == "ok" else "-"
        lines.append(f"{p['subject']:<26}{cell('subject_now'):>7}"
                     f"{cell('subject_young'):>8}{cell('father_40s'):>9}"
                     f"{cell('mother_40s'):>9}   {'OK' if p['has_minimum_set'] else '..'}")
    report = "\n".join(lines)
    open(os.path.join(DATA, "report.txt"), "w").write(report + "\n")
    return index, report


if __name__ == "__main__":
    idx, rep = build()
    print(rep)
    print()
    print(json.dumps(idx["counts"], indent=1))
