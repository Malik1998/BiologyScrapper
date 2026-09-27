"""Review sheets for picks that came from web search.

Each tile shows the whole photo with the chosen face boxed, and the facts the
age rests on (caption year, computed age, identity cosine, caption text), so a
reviewer -- human or model -- can confirm "right person, plausibly that age"
or reject it. Verdicts go into work/web_review.json:

    {"<slug>/<slot>": {"ok": false, "note": "wedding photo is 2008, not 2018"}}

and `apply` removes rejected slots from the dataset.
"""

import glob
import json
import os
import sys

import cv2
import numpy as np

ROOT = os.path.join(os.path.dirname(__file__), "..")
DATA = os.path.join(ROOT, "dataset")
OUT = os.path.join(DATA, "_sheets", "web_review")
VERDICTS = os.path.join(ROOT, "work", "web_review.json")
TILE = 520


def web_slots():
    for mp in sorted(glob.glob(os.path.join(DATA, "*", "meta.json"))):
        m = json.load(open(mp))
        for slot, e in m["slots"].items():
            if e.get("status") == "ok" and e.get("source") == "web":
                yield m, slot, e


def tile(m, slot, e):
    img = cv2.imread(os.path.join(DATA, e["file"]))
    face = cv2.imread(os.path.join(DATA, e["face_crop"]))
    canvas = np.full((TILE + 150, TILE * 2, 3), 255, np.uint8)
    for i, im in enumerate((img, face)):
        if im is None:
            continue
        h, w = im.shape[:2]
        k = TILE / max(h, w)
        im = cv2.resize(im, (int(w * k), int(h * k)))
        canvas[:im.shape[0], i * TILE:i * TILE + im.shape[1]] = im
    lines = [
        f"{m['slug']} / {slot}   age {e['age_at_photo']}  (year {e['date_taken']})",
        f"person: {e['person']}  born {e['person_birth']}   id={e.get('identity_cosine')}",
        f"caption: {(e.get('search_title') or '')[:95]}",
        f"page: {(e.get('source_page') or '')[:95]}",
    ]
    for i, t in enumerate(lines):
        cv2.putText(canvas, t, (8, TILE + 30 + 32 * i), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, (0, 0, 0), 1, cv2.LINE_AA)
    return canvas


def build():
    os.makedirs(OUT, exist_ok=True)
    done = json.load(open(VERDICTS)) if os.path.exists(VERDICTS) else {}
    n = 0
    for m, slot, e in web_slots():
        key = f"{m['slug']}/{slot}"
        if key in done:
            continue
        cv2.imwrite(os.path.join(OUT, key.replace("/", "__") + ".jpg"), tile(m, slot, e))
        n += 1
    print(f"{n} web picks to review -> {OUT}")


def apply():
    """Drop slots whose web pick was rejected; the slot becomes missing again."""
    done = json.load(open(VERDICTS)) if os.path.exists(VERDICTS) else {}
    for key, v in done.items():
        if v.get("ok"):
            continue
        slug, slot = key.split("/")
        mp = os.path.join(DATA, slug, "meta.json")
        if not os.path.exists(mp):
            continue
        m = json.load(open(mp))
        e = m["slots"].get(slot, {})
        if e.get("status") != "ok" or e.get("source") != "web":
            continue
        # remember the rejected file so a later re-run does not pick it again
        v["page"], v["file_url"] = e.get("source_page"), e.get("source_file_url")
        for f in (e.get("file"), e.get("face_crop")):
            if f and os.path.exists(os.path.join(DATA, f)):
                os.remove(os.path.join(DATA, f))
        m["slots"][slot] = {"status": "missing", "reason": "web pick rejected in review: "
                            + v.get("note", ""), "rejected_web_pick": e.get("source_page")}
        s = m["slots"]
        m["complete_slots"] = sum(1 for x in s.values() if x.get("status") == "ok")
        m["has_minimum_set"] = (s["subject_now"].get("status") == "ok"
                                and s["subject_young"].get("status") == "ok"
                                and any(s[k].get("status") == "ok" for k in ("father_40s", "mother_40s")))
        json.dump(m, open(mp, "w"), ensure_ascii=False, indent=2)
        print(f"rejected {key}: {v.get('note', '')}")
    json.dump(done, open(VERDICTS, "w"), ensure_ascii=False, indent=1)


def rejected_urls():
    done = json.load(open(VERDICTS)) if os.path.exists(VERDICTS) else {}
    return {u for v in done.values() if not v.get("ok")
            for u in (v.get("page"), v.get("file_url")) if u}


if __name__ == "__main__":
    {"build": build, "apply": apply}[sys.argv[1] if len(sys.argv) > 1 else "build"]()
