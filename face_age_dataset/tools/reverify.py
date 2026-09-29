"""Recompute each photo's identity on the face that was actually cropped.

Until the per-thread recognizer fix, parallel harvests could score one face
and crop another (a shared SFace net handed embeddings across threads). This
embeds every saved face crop against the slot person's Wikidata portrait,
single-threaded, and records it next to the harvest-time score:

    identity_crop     cosine of the saved crop to the reference portrait

    python tools/reverify.py            # writes the field, prints a summary
"""

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from build import _embed_main_face, WORK  # noqa: E402
from identity import cosine, commons_download, wikidata_by_qid  # noqa: E402

DATA = os.path.join(os.path.dirname(__file__), "..", "dataset")
ROLE = {"subject_now": "subject", "subject_young": "subject",
        "father_40s": "father", "mother_40s": "mother"}


def ref_for(slug, qid, cache={}):
    if qid in cache:
        return cache[qid]
    p = os.path.join(WORK, "cache", slug, f"ref_{qid}.jpg")
    if not os.path.exists(p):
        img = wikidata_by_qid(qid).get("image")
        if img:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            try:
                commons_download(img, p)
            except Exception:
                p = None
        else:
            p = None
    emb = _embed_main_face(p)[0] if p and os.path.exists(p) else None
    cache[qid] = emb
    return emb


def main():
    rows = []
    for mp in sorted(glob.glob(os.path.join(DATA, "*", "meta.json"))):
        m = json.load(open(mp))
        changed = False
        for k, e in m["slots"].items():
            if e.get("status") != "ok":
                continue
            who = m["subject"] if ROLE[k] == "subject" else (m.get(ROLE[k]) or {})
            ref = ref_for(m["slug"], who.get("qid")) if who.get("qid") else None
            crop = _embed_main_face(os.path.join(DATA, e["face_crop"]))[0]
            v = round(cosine(crop, ref), 3) if ref is not None and crop is not None else None
            e["identity_crop"] = v
            changed = True
            rows.append((m["slug"], k, e.get("identity_cosine"), v, e.get("source")))
        if changed:
            json.dump(m, open(mp, "w"), ensure_ascii=False, indent=2)
    json.dump(rows, open(os.path.join(WORK, "reverify.json"), "w"), ensure_ascii=False)
    have = [r for r in rows if r[3] is not None]
    print(f"{len(rows)} photos, {len(have)} with a reference")
    for t in (0.20, 0.25, 0.30, 0.363):
        print(f"  crop identity < {t}: {sum(r[3] < t for r in have)}")


if __name__ == "__main__":
    sys.exit(main())
