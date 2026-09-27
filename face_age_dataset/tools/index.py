"""Aggregate per-person meta.json into one index plus a readable report."""

import csv
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
            "date_source": "exif | category_year | category_override | category_only "
                           "| flickr_date_taken | search_title_year",
            "date_conflict": "true when EXIF disagreed with curator categories "
                             "(digitised archives) and the category year won",
            "identity_cosine": "SFace similarity to the Wikidata P18 reference; "
                               "this is how the right face is picked out of a group",
        },
        "counts": {
            "people": len(people),
            "full_4_slots": sum(1 for p in people if p.get("complete_slots") == 4),
            "minimum_set": sum(1 for p in people if p.get("has_minimum_set")),
            "3_slots": sum(1 for p in people if p.get("complete_slots") == 3),
        },
        "people": [],
    }
    def who(x):
        return {"name": x["name"], "qid": x.get("qid"), "birth": x.get("birth")} if x else None

    for p in people:
        index["people"].append({
            "slug": p["slug"],
            "subject": p["subject"]["name"],
            "subject_birth": p["subject"].get("birth"),
            "father": who(p.get("father")),
            "mother": who(p.get("mother")),
            "complete_slots": p.get("complete_slots", 0),
            "has_minimum_set": p.get("has_minimum_set", False),
            "slots": {s: {
                "status": p["slots"].get(s, {}).get("status"),
                "age": p["slots"].get(s, {}).get("age_at_photo"),
                "person": p["slots"].get(s, {}).get("person"),
                "person_birth": p["slots"].get(s, {}).get("person_birth"),
                "date_taken": p["slots"].get(s, {}).get("date_taken"),
                "date_precision": p["slots"].get(s, {}).get("date_precision"),
                "source": p["slots"].get(s, {}).get("source", "commons")
                          if p["slots"].get(s, {}).get("status") == "ok" else None,
                "file": p["slots"].get(s, {}).get("file"),
                "identity_cosine": p["slots"].get(s, {}).get("identity_cosine"),
                "reason": p["slots"].get(s, {}).get("reason"),
            } for s in SLOTS},
        })
    json.dump(index, open(os.path.join(DATA, "index.json"), "w"),
              ensure_ascii=False, indent=2)

    # summary first: how many people are usable, and how complete
    by_n = {k: sum(1 for p in people if p.get("complete_slots", 0) == k) for k in range(5)}
    with_parent3 = sum(1 for p in people if p.get("complete_slots") == 3 and p.get("has_minimum_set"))
    summary = [
        f"people: {len(people)}",
        f"4 photos (now + young + father + mother): {by_n[4]}",
        f"3 photos: {by_n[3]}  (of them now + young + a parent: {with_parent3})",
        f"minimum set (now + young + at least one parent): "
        f"{sum(1 for p in people if p.get('has_minimum_set'))}",
        f"2 photos: {by_n[2]}   1 photo: {by_n[1]}",
        "",
    ]
    # each cell: age on the photo and the year it was taken, "46/1993"
    lines = summary + [f"{'person':<30}{'born':>6}{'now':>10}{'young':>10}"
             f"{'father':>10}{'f.born':>7}{'mother':>10}{'m.born':>7}   set"]
    lines.append("-" * 97)
    for p in index["people"]:
        def cell(s):
            d = p["slots"][s]
            if d["status"] != "ok":
                return "-"
            return f"{d['age']}/{str(d['date_taken'])[:4]}" + ("*" if d["source"] == "web" else "")
        def yr(x):
            return (x or {}).get("birth", "")[:4] if x and x.get("birth") else "-"
        lines.append(f"{p['subject'][:29]:<30}{(p['subject_birth'] or '-')[:4]:>6}"
                     f"{cell('subject_now'):>10}{cell('subject_young'):>10}"
                     f"{cell('father_40s'):>10}{yr(p['father']):>7}"
                     f"{cell('mother_40s'):>10}{yr(p['mother']):>7}"
                     f"   {'OK' if p['has_minimum_set'] else '..'}")
    lines.append("")
    lines.append("cell = age on photo / year taken; * = from web search (check pending)")
    report = "\n".join(lines)

    # one row per photo, for loading into pandas / a spreadsheet
    cols = ["slug", "slot", "person", "person_birth", "date_taken", "date_precision",
            "age_at_photo", "age_uncertainty_years", "source", "license", "identity_cosine",
            "needs_visual_check", "file", "face_crop", "source_page",
            "subject", "subject_birth", "father", "father_birth", "mother", "mother_birth"]
    with open(os.path.join(DATA, "photos.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for p in people:
            fam = {"subject": p["subject"]["name"], "subject_birth": p["subject"].get("birth"),
                   "father": (p.get("father") or {}).get("name"),
                   "father_birth": (p.get("father") or {}).get("birth"),
                   "mother": (p.get("mother") or {}).get("name"),
                   "mother_birth": (p.get("mother") or {}).get("birth")}
            for s in SLOTS:
                e = p["slots"].get(s, {})
                if e.get("status") != "ok":
                    continue
                w.writerow({**e, **fam, "slug": p["slug"], "slot": s,
                            "source": e.get("source", "commons")})
    open(os.path.join(DATA, "report.txt"), "w").write(report + "\n")
    return index, report


if __name__ == "__main__":
    idx, rep = build()
    print(rep)
    print()
    print(json.dumps(idx["counts"], indent=1))
