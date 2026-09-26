"""Build one person's 4-photo set: subject at 40-50 and 20-30, each parent at 40-50.

Everything is driven from Wikidata (birth dates, parents, reference portraits,
Commons categories) so adding a person costs one name.
"""

import json
import os
import shutil
import sys

import cv2

sys.path.insert(0, os.path.dirname(__file__))
import commons as C
import face as F
from identity import (wikidata_person, wikidata_by_qid, commons_download,
                      embed_faces)

ROOT = os.path.join(os.path.dirname(__file__), "..")
DATA = os.path.join(ROOT, "dataset")
WORK = os.path.join(ROOT, "work")

# matching a 25-year-old against a mid-life reference portrait is genuinely
# harder, so the bar is lower there and we lean on the visual check instead
THRESH = {"subject_now": 0.32, "subject_young": 0.24,
          "father_40s": 0.30, "mother_40s": 0.30}


def has_by_year(cat):
    d = C.api(action="query", titles=f"Category:{cat} by year", prop="info")
    pages = d.get("query", {}).get("pages", [])
    return bool(pages) and not pages[0].get("missing")


PORTRAIT_HINT = ("portrait", "official", "headshot", "close-up", "closeup", "mugshot")


def prior_rank(r):
    """Order candidates by how likely the face fills the frame.

    Sorting by pixel dimensions alone favours wide event shots where the
    subject is a speck, so nudge portrait-ish files to the front.
    """
    t = r["title"].lower()
    bonus = 2.0 if any(h in t for h in PORTRAIT_HINT) else 0.0
    if r.get("from_portrait_cat"):
        bonus += 3.0
    px = min(r.get("w", 0), r.get("h", 0))
    tall = 1.0 if r.get("h", 0) >= r.get("w", 1) else 0.0   # portraits tend to be tall
    return -(bonus + tall + min(px / 3000.0, 1.0))


def harvest_slot(cat, birth, lo, hi):
    """Prefer by-year categories; fall back to metadata scanning."""
    rows = []
    if has_by_year(cat):
        try:
            rows = C.harvest_by_year(cat, birth, lo, hi)
        except Exception as e:
            print(f"    by_year failed: {e}")
    # By-year categories can be small AND polluted -- Charles III's 1990s years
    # are mostly commemorative plaques he unveiled, not photos of him. A low
    # threshold here silently suppressed the far richer flat harvest.
    if len(rows) < 50:
        try:
            more = C.harvest(cat, birth, lo, hi, depth=1)
            seen = {r["title"] for r in rows}
            rows += [m for m in more if m["title"] not in seen]
        except Exception as e:
            print(f"    flat harvest failed: {e}")
    # dedicated portrait categories are where the well-framed faces live
    for suffix in (" portraits", " official portraits"):
        try:
            extra = C.harvest(cat + suffix, birth, lo, hi, depth=1)
        except Exception:
            continue
        seen = {r["title"] for r in rows}
        for e in extra:
            e["from_portrait_cat"] = True
            if e["title"] not in seen:
                rows.append(e)
            else:
                for r in rows:
                    if r["title"] == e["title"]:
                        r["from_portrait_cat"] = True
    rows.sort(key=prior_rank)
    return rows


def _embed_main_face(path):
    """Embed the dominant face of a reference image.

    Taking faces[:1] (detection order) is wrong: Ravi Shankar's P18 portrait
    holds three faces, so the reference was built from a bystander and then
    matched itself at cosine 0.94. The subject of a portrait is the biggest,
    most central face.
    """
    img = cv2.imread(path)
    if img is None:
        return None, None
    h, w = img.shape[:2]
    det = F.detector((w, h))
    _, faces = det.detect(img)
    if faces is None or len(faces) == 0:
        return None, None
    cx, cy = w / 2.0, h / 2.0

    def rank(f):
        x, y, fw, fh = f[:4]
        centre = (((x + fw / 2) - cx) ** 2 + ((y + fh / 2) - cy) ** 2) ** 0.5
        return fw - 0.35 * centre
    best = max(faces, key=rank)
    embs = embed_faces(img, [best])
    return (embs[0] if embs else None), len(faces)


def reference_embedding(person, cache, fallback_rows=None):
    tried = []
    if person.get("image"):
        p = os.path.join(cache, f"ref_{person['qid']}.jpg")
        if not os.path.exists(p):
            try:
                commons_download(person["image"], p)
            except Exception:
                p = None
        if p:
            tried.append(p)
            emb, _ = _embed_main_face(p)
            if emb is not None:
                return emb

    # P18 can be unusable (Liv Tyler's cropped portrait yielded no detection),
    # and losing the reference silently downgrades selection to "biggest face",
    # which once picked a man for her. Try single-face candidates instead.
    for r in (fallback_rows or [])[:12]:
        q = os.path.join(cache, f"reffb_{person['qid']}_"
                         + "".join(c if c.isalnum() else "_" for c in r["title"][5:])[:60] + ".jpg")
        if not os.path.exists(q) and not F.fetch(F.thumb_url(r["title"], 1200), q):
            continue
        emb, nf = _embed_main_face(q)
        if emb is not None and nf == 1:
            print(f"       reference fell back to {r['title'][5:60]}")
            return emb
    return None


def crop_face(src, box, dest, pad=0.55):
    img = cv2.imread(src)
    if img is None:
        return False
    h, w = img.shape[:2]
    x, y, fw, fh = box
    cx, cy = x + fw / 2, y + fh / 2
    half = max(fw, fh) * (1 + pad) / 2
    x0, y0 = int(max(0, cx - half)), int(max(0, cy - half))
    x1, y1 = int(min(w, cx + half)), int(min(h, cy + half))
    cv2.imwrite(dest, img[y0:y1, x0:x1])
    return True


def build_person(name, slug=None, top=60):
    subj = wikidata_person(name)
    if not subj or not subj.get("birth"):
        print(f"!! cannot resolve {name}")
        return None
    if not slug:
        s = subj["label"].lower()
        slug = "".join(ch if ch.isalnum() else "-" for ch in s)
        while "--" in slug:
            slug = slug.replace("--", "-")
        slug = slug.strip("-")
    cache = os.path.join(WORK, "cache", slug)
    os.makedirs(cache, exist_ok=True)
    outdir = os.path.join(DATA, slug)

    father = wikidata_by_qid(subj["father"]) if subj.get("father") else None
    mother = wikidata_by_qid(subj["mother"]) if subj.get("mother") else None

    people = {
        "subject_now":   (subj,   40, 50),
        "subject_young": (subj,   20, 30),
        "father_40s":    (father, 40, 50),
        "mother_40s":    (mother, 40, 50),
    }

    meta = {
        "slug": slug,
        # the name as asked for: lets progress be rebuilt from the dataset alone
        "query_name": name,
        "subject": {"name": subj["label"], "qid": subj["qid"], "birth": subj["birth"]},
        "father": {"name": father["label"], "qid": father["qid"], "birth": father["birth"]} if father else None,
        "mother": {"name": mother["label"], "qid": mother["qid"], "birth": mother["birth"]} if mother else None,
        "slots": {},
    }

    for slot, (p, lo, hi) in people.items():
        entry = {"status": "missing", "candidates_found": 0}
        if not p:
            entry["reason"] = "parent unknown in Wikidata"
            meta["slots"][slot] = entry
            continue
        if not p.get("birth"):
            entry["reason"] = "no birth date"
            meta["slots"][slot] = entry
            continue
        # Someone who died young never reached this age window. Without this
        # guard, Diana (died at 36) still pulled 20 "aged 40-50" candidates
        # from mis-categorised files and relied on identity matching to reject
        # them -- a wrong answer waiting to happen.
        if p.get("death"):
            by = int(p["birth"][:4])
            age_at_death = int(p["death"][:4]) - by
            if age_at_death < lo:
                entry["reason"] = (f"died at ~{age_at_death}, never reached {lo}")
                entry["died"] = p["death"]
                meta["slots"][slot] = entry
                print(f"  [{slot}] {p['label']}: died at ~{age_at_death}, slot impossible")
                continue
            hi = min(hi, age_at_death)
        cat = p.get("commons_cat") or p["label"]
        print(f"  [{slot}] {p['label']} ({p['birth']}) age {lo}-{hi} cat={cat!r}")

        rows = harvest_slot(cat, p["birth"], lo, hi)
        entry["candidates_found"] = len(rows)
        if not rows:
            entry["reason"] = "no dated photos in age range"
            meta["slots"][slot] = entry
            continue

        ref = reference_embedding(p, cache, fallback_rows=rows)
        entry["reference_image"] = p.get("image")
        if ref is None:
            # No usable reference means the identity check is off: the pick is
            # then just "biggest face", which in a group photo is a coin flip.
            entry["identity_check"] = "unavailable"
            print("       ! no reference face; identity check disabled")
        scored = F.run(rows, os.path.join(cache, slot), top=top, ref_emb=ref,
                       identity_min=THRESH.get(slot, 0.30))

        usable = [s for s in scored if s["face"].get("score", 0) > 0]
        entry["candidates_scored"] = len(scored)
        entry["candidates_usable"] = len(usable)
        low_conf = False
        if not usable:
            # A reference portrait of a 75-year-old king matches a photo of him
            # at 41 only weakly. Rather than drop the slot silently, retry
            # relaxed and hand the result to the human review clearly labelled.
            relaxed = max(0.18, THRESH.get(slot, 0.30) - 0.10)
            scored = F.run(rows, os.path.join(cache, slot), top=top, ref_emb=ref,
                           identity_min=relaxed)
            usable = [s for s in scored if s["face"].get("score", 0) > 0]
            if usable:
                low_conf = True
                entry["relaxed_identity_min"] = relaxed
                print(f"       (relaxed to {relaxed:.2f}: {len(usable)} candidates, "
                      f"needs visual check)")
        if not usable:
            entry["reason"] = "no face passed identity/quality check"
            meta["slots"][slot] = entry
            continue

        best = usable[0]
        os.makedirs(outdir, exist_ok=True)
        ext = ".jpg"
        full = os.path.join(outdir, f"{slot}_age{best['age']}{ext}")

        # re-fetch large so the delivered crop is not limited by the 1400px
        # working copy we used for scoring
        hi_res = os.path.join(cache, slot, "hires_" + os.path.basename(best["local"]))
        box, src = best["face"]["box"], best["local"]
        if F.fetch(F.thumb_url(best["title"], width=3000), hi_res):
            a2 = F.analyse(hi_res, ref_emb=ref, identity_min=THRESH.get(slot, 0.30))
            if a2 and a2.get("score", 0) > 0 and a2.get("box"):
                box, src = a2["box"], hi_res
        shutil.copyfile(src, full)
        face_p = os.path.join(outdir, f"{slot}_age{best['age']}_face{ext}")
        crop_face(src, box, face_p)

        f = best["face"]
        entry.update({
            "status": "ok",
            "needs_visual_check": bool(low_conf or ref is None),
            "file": os.path.relpath(full, DATA),
            "face_crop": os.path.relpath(face_p, DATA),
            "person": p["label"],
            "person_birth": p["birth"],
            "age_at_photo": best["age"],
            "age_uncertainty_years": best.get("age_uncertainty", 0),
            "date_taken": best["date"],
            "date_precision": best["date_precision"],
            "date_source": best.get("date_source", "exif"),
            "date_conflict": best.get("date_conflict", False),
            "source_page": best["page"],
            "source_file_url": best["file_url"],
            "license": best.get("license"),
            "author": best.get("author"),
            "identity_cosine": f.get("identity"),
            "identity_margin": f.get("id_margin"),
            "faces_in_photo": f.get("n_faces"),
            "interocular_px": f.get("interocular"),
            "frontality": round(1 - min(f.get("yaw_asym", 1), 1), 3),
            "quality_score": f.get("score"),
            "quality_parts": f.get("parts"),
            "runners_up": [
                {"title": s["title"], "age": s["age"], "score": s["face"]["score"],
                 "identity": s["face"].get("identity"), "page": s["page"]}
                for s in usable[1:4]
            ],
        })
        meta["slots"][slot] = entry
        print(f"       -> age {best['age']} id={f.get('identity')} score={f['score']}")

    ok = sum(1 for s in meta["slots"].values() if s.get("status") == "ok")
    meta["complete_slots"] = ok
    meta["has_minimum_set"] = (meta["slots"]["subject_now"].get("status") == "ok"
                               and meta["slots"]["subject_young"].get("status") == "ok"
                               and any(meta["slots"][k].get("status") == "ok"
                                       for k in ("father_40s", "mother_40s")))
    if ok:
        os.makedirs(outdir, exist_ok=True)
        json.dump(meta, open(os.path.join(outdir, "meta.json"), "w"),
                  ensure_ascii=False, indent=2)
    return meta


if __name__ == "__main__":
    for nm in sys.argv[1:]:
        print(f"\n=== {nm}")
        m = build_person(nm)
        if m:
            print(f"  complete={m['complete_slots']}/4 minimum_set={m['has_minimum_set']}")
