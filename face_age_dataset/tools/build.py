"""Build one person's 4-photo set: subject at 40-50 and 20-30, each parent at 40-50.

Everything is driven from Wikidata (birth dates, parents, reference portraits,
Commons categories) so adding a person costs one name.
"""

import json
import re
from urllib.parse import unquote
import os
import shutil
import sys

import cv2

sys.path.insert(0, os.path.dirname(__file__))
import commons as C
import flickr
import websearch
from review_web import rejected_urls
from licensing import tag as tag_licence
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


def by_year_category(cat):
    """The person's "... by year" subcategory, whatever its exact name.

    "Philippe of Belgium" holds "Philippe I of Belgium by year": looking only
    for "<cat> by year" found nothing, and the king got no photos at all.
    """
    d = C.api(action="query", list="categorymembers", cmtitle=f"Category:{cat}",
              cmtype="subcat", cmlimit="500")
    for m in d.get("query", {}).get("categorymembers", []):
        if m["title"].endswith(" by year"):
            return m["title"]
    return None


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


FLICKR_BELOW = 30   # ask Flickr / the web only when Commons is thin for this slot
USE_WEB = True


DEPICTS_BELOW = 50   # also ask Commons structured data when categories are thin


def harvest_slot(cat, birth, lo, hi, name=None, native_names=(), qid=None, use_web=True):
    """Prefer by-year categories; fall back to metadata scanning.

    Network failures propagate on purpose. They used to be caught and printed,
    which left rows empty and got the slot recorded as "no dated photos" --
    30 slots in one run, Nico Rosberg's 105 candidates among them.
    """
    rows = []
    cat = C.resolve_category(cat) if cat else None
    byc = by_year_category(cat) if cat else None
    if byc:
        rows = C.harvest_by_year(cat, birth, lo, hi, by_year_cat=byc)
    # By-year categories can be small AND polluted -- Charles III's 1990s years
    # are mostly commemorative plaques he unveiled, not photos of him. A low
    # threshold here silently suppressed the far richer flat harvest.
    if cat and len(rows) < 50:
        more = C.harvest(cat, birth, lo, hi, depth=1)
        seen = {r["title"] for r in rows}
        rows += [m for m in more if m["title"] not in seen]
    if qid and len(rows) < DEPICTS_BELOW:
        more = C.harvest_titles(C.depicts_files(qid), birth, lo, hi)
        seen = {r["title"] for r in rows}
        more = [m for m in more if m["title"] not in seen]
        if more:
            print(f"       depicts: +{len(more)} dated candidates")
        rows += more
    # dedicated portrait categories are where the well-framed faces live
    for suffix in ((" portraits", " official portraits") if cat else ()):
        # a missing category just lists nothing, so no try/except needed
        extra = C.harvest(cat + suffix, birth, lo, hi, depth=1)
        seen = {r["title"] for r in rows}
        for e in extra:
            e["from_portrait_cat"] = True
            if e["title"] not in seen:
                rows.append(e)
            else:
                for r in rows:
                    if r["title"] == e["title"]:
                        r["from_portrait_cat"] = True
    if name and len(rows) < FLICKR_BELOW:
        extra = flickr.harvest(name, birth, lo, hi)
        if extra:
            print(f"       flickr: +{len(extra)} candidates for {name}")
        rows += extra
    if name and USE_WEB and use_web and len(rows) < FLICKR_BELOW:
        extra = websearch.harvest(name, birth, lo, hi, native_names=native_names)
        print(f"       web search: +{len(extra)} dated candidates for {name}")
        rows += extra
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
        # a tight head-and-shoulders crop (Jamie Lee Curtis's P18) fills the
        # frame and YuNet finds nothing; with a border and at a smaller scale
        # the same face is detected
        pad = int(0.3 * max(h, w))
        img = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(127, 127, 127))
        k = 640 / max(img.shape[:2])
        img = cv2.resize(img, None, fx=k, fy=k)
        h, w = img.shape[:2]
        _, faces = F.detector((w, h)).detect(img)
    if faces is None or len(faces) == 0:
        return None, None
    cx, cy = w / 2.0, h / 2.0

    def rank(f):
        x, y, fw, fh = f[:4]
        centre = (((x + fw / 2) - cx) ** 2 + ((y + fh / 2) - cy) ** 2) ** 0.5
        return fw - 0.35 * centre
    # a big, central false detection must not beat a sure face: Ingrid
    # Klimke's portrait is her on horseback, and the horse's head (0.62)
    # outranked her face (0.94) on size, making a horse the reference
    top = max(float(f[-1]) for f in faces)
    faces = [f for f in faces if float(f[-1]) >= top - 0.15]
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
            except FileNotFoundError:
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
        if not os.path.exists(q) and not F.fetch(F.url_for(r, 1280), q):
            continue
        emb, nf = _embed_main_face(q)
        if emb is not None and nf == 1:
            print(f"       reference fell back to {r['title'][5:60]}")
            return emb
    return None


def _web_ok(s):
    """Web hits need a firm identity match: nearly every wrong-person pick in
    review was a relative or namesake scoring below websearch.WEB_ID_MIN."""
    if s.get("source") != "web":
        return True
    return (s["face"].get("identity") or 0) >= websearch.WEB_ID_MIN


def _deliver(best, cache, slot, ref):
    """(image path, face box) for the delivered crop.

    Re-fetch large so the crop is not limited by the 1400px working copy --
    but keep the face that was scored there. Re-choosing by identity in the
    big image let a stray detection win (a horse's head for Ingrid Klimke).
    """
    box, src = best["face"]["box"], best["local"]
    hi_res = os.path.join(cache, slot, "hires_" + os.path.basename(best["local"]))
    if not F.fetch(F.url_for(best, 3840), hi_res):
        return src, box
    im0, im1 = cv2.imread(src), cv2.imread(hi_res)
    if im0 is None or im1 is None:
        return src, box
    k = im1.shape[1] / im0.shape[1]
    want = [v * k for v in box]
    wx, wy = want[0] + want[2] / 2, want[1] + want[3] / 2
    a2 = F.analyse(hi_res, ref_emb=ref, identity_min=THRESH.get(slot, 0.30))
    if a2 and a2.get("score", 0) > 0 and a2.get("box"):
        b = a2["box"]
        bx, by = b[0] + b[2] / 2, b[1] + b[3] / 2
        if ((bx - wx) ** 2 + (by - wy) ** 2) ** 0.5 < 0.5 * max(want[2], want[3]):
            return hi_res, b
    return hi_res, [int(round(v)) for v in want]


def _crop_ok(face_path, ref, min_id=0.18):
    emb, n = _embed_main_face(face_path)
    if emb is None:
        return False
    if ref is None:
        return True
    from identity import cosine
    return cosine(emb, ref) >= min_id


def _strictly_in(birth, date, lo, hi):
    from check_ages import age_bounds
    if not date:
        return False
    a, b = age_bounds(birth, date)
    return lo <= a and b <= hi


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


# File titles that name something other than a photograph of a face. Every
# pattern here comes from a pick rejected in review: a banknote engraving
# (Bhumibol), a protest mural (Ninoy Aquino), a film poster (Kinski as
# Aguirre), a portrait painting (Guillaume), a tin with a printed portrait
# (Beatrix on Oranje Hagel), a green-card scan (Eduardo Bolsonaro).
NOT_A_PHOTO = re.compile(
    r"banknote|bank ?note|baht|\bstamps?\b|postage|\bcoins?\b(?! toss)|"
    r"poster\b|affiche|mural|graffiti|painting|oil on canvas|portrait by|schilderij|gem[aä]lde|"
    r"\bdrawing|sketch|caricature|cartoon|illustration|statue|sculpture|\bbust\b|wax ?(figure|museum|work)|"
    r"oranje hagel|\bblik\b|souvenir|"
    r"green card|permanent resident|passport|\bid card|identity card", re.I)
# Only admit a photo when both ends of its possible age range are in the
# window, not just the middle (185 photos dated to a bare year sat one year
# outside). Off by default until the policy is decided; harvest_all
# --strict-ages turns it on.
STRICT_AGES = False
# Nominal windows are 40-50 and 20-30, but a photo two years outside is as
# good for the analysis (agreed 2026-09-29: "2-3 years off does not matter").
# Harvest with this much slack either side; the nominal window stays in the
# meta so analysis can still filter to it (see check_ages.py).
AGE_SLACK = 2
# --requalify: redo filled slots whose photo fails the rating checks
# (quality_tags.py), keeping the old photo unless a candidate passes them
REQUALIFY = False
PITCH_FRONTAL = 0.575     # median nose-height ratio measured on the dataset


def build_person(name, slug=None, top=60, qid=None, father_qid=None,
                 mother_qid=None, web_slots=None):
    """Build or complete one person.

    Slots already filled in an existing meta.json are kept as they are, so a
    re-run only spends requests on what is still missing and can never make a
    finished slot worse. `qid` pins the subject; `father_qid`/`mother_qid`
    supply parents Wikidata does not link.
    """
    subj = wikidata_person(name, qid=qid)
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

    # the search result carries English labels only; the entity has the rest
    subj["native_names"] = wikidata_by_qid(subj["qid"]).get("native_names", [])
    father_qid = father_qid or subj.get("father")
    mother_qid = mother_qid or subj.get("mother")
    father = wikidata_by_qid(father_qid) if father_qid else None
    mother = wikidata_by_qid(mother_qid) if mother_qid else None

    prev = {}
    mp = os.path.join(outdir, "meta.json")
    if os.path.isfile(mp):
        try:
            old = json.load(open(mp))
            if old.get("subject", {}).get("qid") == subj["qid"]:
                prev = {k: v for k, v in old.get("slots", {}).items()
                        if (v.get("status") == "ok"
                            and os.path.isfile(os.path.join(DATA, v.get("file", ""))))
                        # a slot whose picks kept failing visual review is
                        # closed: Commons has only more copies of the same
                        # wrong photo left (Arlene Dahl as Lorenzo Lamas in
                        # three files); fill it by hand or not at all
                        or v.get("locked")}
        except Exception:
            pass

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

    # each slot is checked against its relatives' faces too: a candidate that
    # matches the son or the mother better than the person asked for is out
    relatives = {"subject": subj, "father": father, "mother": mother}
    rel_refs = {}

    def rel_ref(role):
        if role not in rel_refs:
            q = relatives.get(role)
            rel_refs[role] = reference_embedding(q, cache) if q else None
        return rel_refs[role]

    olds = {}
    for slot, (p, lo, hi) in people.items():
        old = None
        if slot in prev:
            e0 = prev[slot]
            if not (REQUALIFY and e0.get("status") == "ok" and e0.get("source") != "web"
                    and not (e0.get("qc") or {}).get("ok_for_rating", True)):
                meta["slots"][slot] = e0
                continue
            old = olds[slot] = e0
        entry = {"status": "missing", "candidates_found": 0,
                 "window": [lo, hi], "age_slack": AGE_SLACK}
        lo, hi = lo - AGE_SLACK, hi + AGE_SLACK
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

        rows = harvest_slot(cat, p["birth"], lo, hi, name=p["label"],
                            native_names=p.get("native_names", ()), qid=p.get("qid"),
                            # web picks cost a visual review each: spend them only
                            # where one photo completes a minimum set
                            use_web=web_slots is None or slot in web_slots)
        rejected = rejected_urls()
        # a file already used in another slot of this person is not a second photo
        # (not this slot's own old file: excluding it left requalified slots
        # with no rows at all, and the early exit below then dropped the photo)
        used = {e.get("source_file_url")
                for e in [v for k, v in prev.items() if k != slot] + list(meta["slots"].values())
                if e.get("status") == "ok"}
        rows = [r for r in rows
                if r.get("page") not in rejected and r.get("file_url") not in rejected
                and r.get("file_url") not in used
                and not NOT_A_PHOTO.search(unquote(str(r.get("title") or "") + " "
                                                   + str(r.get("search_title") or "")))]
        if STRICT_AGES:
            rows = [r for r in rows if _strictly_in(p["birth"], r.get("date"), lo, hi)]
        entry["candidates_found"] = len(rows)
        if not rows:
            entry["reason"] = "no dated photos in age range"
            meta["slots"][slot] = entry
            continue

        # never build the reference from a web hit: the candidate then matches
        # itself at cosine 1.0 (Keanu Reeves passed as Jacelyn Reeves that way)
        ref = reference_embedding(p, cache,
                                  fallback_rows=[r for r in rows if r.get("source") != "web"])
        entry["reference_image"] = p.get("image")
        if ref is None:
            # No usable reference means the identity check is off: the pick is
            # then just "biggest face", which in a group photo is a coin flip.
            entry["identity_check"] = "unavailable"
            print("       ! no reference face; identity check disabled")
        others = [r for r in (rel_ref(k) for k in ("subject", "father", "mother")
                              if relatives.get(k) is not p) if r is not None]
        scored = F.run(rows, os.path.join(cache, slot), top=top, ref_emb=ref,
                       identity_min=THRESH.get(slot, 0.30), other_refs=others)

        usable = [s for s in scored if s["face"].get("score", 0) > 0 and _web_ok(s)]
        entry["candidates_scored"] = len(scored)
        entry["candidates_usable"] = len(usable)
        low_conf = False
        if not usable:
            # A reference portrait of a 75-year-old king matches a photo of him
            # at 41 only weakly. Rather than drop the slot silently, retry
            # relaxed and hand the result to the human review clearly labelled.
            relaxed = max(0.18, THRESH.get(slot, 0.30) - 0.10)
            scored = F.run(rows, os.path.join(cache, slot), top=top, ref_emb=ref,
                           identity_min=relaxed, other_refs=others)
            usable = [s for s in scored if s["face"].get("score", 0) > 0 and _web_ok(s)]
            if usable:
                low_conf = True
                entry["relaxed_identity_min"] = relaxed
                print(f"       (relaxed to {relaxed:.2f}: {len(usable)} candidates, "
                      f"needs visual check)")
        if not usable:
            entry["reason"] = "no face passed identity/quality check"
            meta["slots"][slot] = entry
            continue

        # a licensed, curator-dated file beats a search hit of similar quality
        usable.sort(key=lambda s: (s.get("source") == "web", -s["face"]["score"]))
        os.makedirs(outdir, exist_ok=True)
        ext = ".jpg"
        from quality_tags import measure, judge
        best = fallback = None
        tried = []
        for cand in usable[:12]:
            full = os.path.join(outdir, f"{slot}_try{len(tried)}{ext}")
            face_p = os.path.join(outdir, f"{slot}_try{len(tried)}_face{ext}")
            src, box = _deliver(cand, cache, slot, ref)
            shutil.copyfile(src, full)
            crop_face(src, box, face_p)
            tried.append((full, face_p))
            # The crop must still show this person. It once showed a horse's
            # head, an ear, a hand, a guitar: the hi-res pass picked another
            # detection than the one scored on the working copy.
            if not _crop_ok(face_p, ref):
                print(f"       crop check failed for {cand['title'][5:60]}, trying next")
                continue
            q = measure(face_p) or {}
            ok, issues = judge(q, PITCH_FRONTAL)
            q.update(ok_for_rating=ok, issues=issues)
            cand["_qc"], cand["_files"] = q, (full, face_p)
            # raters need frontal, level, neutral, sharp faces: take the best
            # candidate that is, not just the best-scored one
            if ok:
                best = cand
                break
            if fallback is None and old is None:
                fallback = cand
            if old is None and len(tried) >= 5 and fallback is not None:
                break
        best = best or fallback
        keep = {best["_files"][0], best["_files"][1]} if best else set()
        for pair in tried:
            for q in pair:
                if q not in keep and os.path.exists(q):
                    os.remove(q)
        if best is None:
            if old is not None:
                meta["slots"][slot] = old          # nothing better: keep the old photo
                print("       no candidate passes the rating checks; kept the old photo")
                continue
            entry["reason"] = "no candidate survived the crop check"
            meta["slots"][slot] = entry
            continue
        if old is not None:
            for q in (old.get("file"), old.get("face_crop")):
                if q and os.path.exists(os.path.join(DATA, q)):
                    os.remove(os.path.join(DATA, q))
            entry["replaced"] = {"page": old.get("source_page"),
                                 "issues": (old.get("qc") or {}).get("issues")}
            print(f"       replaced (was: {', '.join((old.get('qc') or {}).get('issues') or [])})")
        full = os.path.join(outdir, f"{slot}_age{best['age']}{ext}")
        face_p = os.path.join(outdir, f"{slot}_age{best['age']}_face{ext}")
        os.replace(best["_files"][0], full)
        os.replace(best["_files"][1], face_p)
        entry["qc"] = best["_qc"]

        f = best["face"]
        entry.update({
            "status": "ok",
            # web hits are dated from a caption and unlicensed: always look
            "needs_visual_check": bool(low_conf or ref is None or best.get("source") == "web"),
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
            "source": best.get("source", "commons"),
            "search_title": best.get("search_title"),
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

    # a requalified slot never ends up worse than it was: every early exit
    # above ("no rows", "nothing passed identity") would otherwise lose it
    for slot, o in olds.items():
        if meta["slots"].get(slot, {}).get("status") != "ok":
            meta["slots"][slot] = o

    ok = sum(1 for s in meta["slots"].values() if s.get("status") == "ok")
    meta["complete_slots"] = ok
    meta["has_minimum_set"] = (meta["slots"]["subject_now"].get("status") == "ok"
                               and meta["slots"]["subject_young"].get("status") == "ok"
                               and any(meta["slots"][k].get("status") == "ok"
                                       for k in ("father_40s", "mother_40s")))
    pub = set()
    for k, e in meta["slots"].items():
        if e.get("status") == "ok" and tag_licence(e)["publishable"]:
            pub.add(k)
    meta["publishable_minimum_set"] = ({"subject_now", "subject_young"} <= pub
                                       and bool(pub & {"father_40s", "mother_40s"}))
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
