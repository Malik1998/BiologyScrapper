"""Put a hand-found photo into one slot, replacing what is there.

For slots Commons cannot fill well -- a colour, neutral, frontal photo of a
parent at 40-50 is rare there before the 1990s -- a photo found by hand
(film still, press photo with a known date) goes in through here. The face
is still chosen and checked by identity against the Wikidata reference, and
the photo is measured like any other; the old photo is recorded under
`replaced` and its files are moved to work/replaced/.

    python tools/manual_pick.py SLUG SLOT IMAGE_URL PAGE_URL DATE "EVIDENCE"
"""

import json
import os
import shutil
import sys
import urllib.request

import cv2

sys.path.insert(0, os.path.dirname(__file__))
import build  # noqa: E402
import face as F  # noqa: E402
from identity import wikidata_by_qid, embed_faces, cosine  # noqa: E402
from quality_tags import measure, judge, tinted_bw, COLOUR_SAT  # noqa: E402
from check_ages import age_bounds  # noqa: E402

ROLE = {"subject_now": "subject", "subject_young": "subject",
        "father_40s": "father", "mother_40s": "mother"}
MIN_ID = 0.36          # SFace same-identity threshold; web hits need a firm match


def main(slug, slot, image, page, date, evidence):
    mp = os.path.join(build.DATA, slug, "meta.json")
    m = json.load(open(mp))
    who = m[ROLE[slot]]
    p = wikidata_by_qid(who["qid"])
    cache = os.path.join(build.WORK, "cache", slug)
    os.makedirs(cache, exist_ok=True)
    ref = build.reference_embedding(p, cache)
    if ref is None:
        sys.exit("no reference face for " + who["name"])

    raw = os.path.join(cache, f"manual_{slot}.jpg")
    if os.path.isfile(image):          # e.g. a frame taken from a dated video
        shutil.copyfile(image, raw)
    else:
        req = urllib.request.Request(image, headers={"User-Agent": "Mozilla/5.0"})
        open(raw, "wb").write(urllib.request.urlopen(req, timeout=30).read())
    img = cv2.imread(raw)
    if img is None:
        sys.exit("not an image")
    h, w = img.shape[:2]
    _, faces = F.detector((w, h)).detect(img)
    if faces is None or len(faces) == 0:
        sys.exit("no face")
    embs = embed_faces(img, faces)
    ids = [cosine(e, ref) for e in embs]
    i = max(range(len(ids)), key=ids.__getitem__)
    print(f"{len(faces)} face(s); identity to {who['name']}: {[round(x, 2) for x in ids]}")
    if ids[i] < MIN_ID:
        sys.exit(f"best identity {ids[i]:.2f} < {MIN_ID}: not added")

    lo, hi = age_bounds(who["birth"], date)
    win = (20, 30) if slot == "subject_young" else (40, 50)
    if lo < win[0] - 2 or hi > win[1] + 2:
        sys.exit(f"age {lo}-{hi} outside {win} +-2: not added")
    age = (lo + hi) // 2

    outdir = os.path.dirname(mp)
    full = os.path.join(outdir, f"{slot}_age{age}.jpg")
    face_p = os.path.join(outdir, f"{slot}_age{age}_face.jpg")
    tmp_full, tmp_face = full + ".new.jpg", face_p + ".new.jpg"
    shutil.copyfile(raw, tmp_full)
    build.crop_face(raw, faces[i][:4], tmp_face)
    q = measure(tmp_face) or {}
    ok, issues = judge(q, build.PITCH_FRONTAL)
    tinted = tinted_bw(tmp_full, date)
    q.update(ok_for_rating=ok, issues=issues,
             colour=bool(q.get("saturation", 0) > COLOUR_SAT) and not tinted)

    old = m["slots"].get(slot, {})
    if old.get("status") == "ok":
        for k in ("file", "face_crop"):
            src = os.path.join(build.DATA, old[k])
            if os.path.exists(src):
                dst = os.path.join(build.WORK, "replaced", old[k])
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
    os.replace(tmp_full, full)
    os.replace(tmp_face, face_p)
    m["slots"][slot] = {
        "status": "ok", "window": list(win), "age_slack": 2,
        "file": os.path.relpath(full, build.DATA),
        "face_crop": os.path.relpath(face_p, build.DATA),
        "person": who["name"], "person_birth": who["birth"],
        "age_at_photo": age, "age_uncertainty_years": (hi - lo + 1) // 2,
        "date_taken": date, "date_precision": {1: "year", 2: "month", 3: "day"}[len(date.split("-"))],
        "date_source": "manual", "date_evidence": evidence,
        "source": "web", "source_page": page, "source_file_url": image,
        "license": None, "identity_cosine": round(ids[i], 3),
        "faces_in_photo": len(faces), "needs_visual_check": True,
        "manual": True, "qc": q, "tinted_bw": tinted,
        "replaced": ({"page": old.get("source_page"), "issues": (old.get("qc") or {}).get("issues")}
                     if old.get("status") == "ok" else None),
    }
    json.dump(m, open(mp, "w"), ensure_ascii=False, indent=2)
    print(f"{slug}/{slot}: age {age}, id {ids[i]:.2f}, rating-ready {ok} {issues}, colour {q['colour']}")


if __name__ == "__main__":
    main(*sys.argv[1:7])
