"""Identity matching so we pick the right face out of a crowd.

Reference portraits come from Wikidata P18, which is curated per person. Each
candidate photo may contain many faces; we embed them all with SFace and keep
the one closest to the reference. Cosine similarity is also what tells us a
photo is of the wrong person entirely.
"""

import json
import os
import urllib.parse
import urllib.request

import cv2
import numpy as np

UA = "faces-dataset/0.1 (research dataset build)"
SFACE = os.path.join(os.path.dirname(__file__), "..", "models", "sface.onnx")
# OpenCV's documented same-identity cosine threshold for SFace
SAME_ID = 0.363

_rec = None


def recognizer():
    global _rec
    if _rec is None:
        _rec = cv2.FaceRecognizerSF.create(SFACE, "")
    return _rec


import threading
import time

_wd_lock = threading.Lock()
_wd_last = [0.0]
WD_GAP = 1.2


def wd_get(url):
    """Throttled + retried: parallel workers otherwise trip Wikidata's 429."""
    for attempt in range(5):
        with _wd_lock:
            gap = time.time() - _wd_last[0]
            if gap < WD_GAP:
                time.sleep(WD_GAP - gap)
            _wd_last[0] = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < 4:
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except Exception:
            if attempt == 4:
                raise
            time.sleep(3 * (attempt + 1))


HUMAN = "Q5"


def best_label(entity, fallback):
    """Prefer the English Wikipedia article title over the Wikidata label.

    Labels get vandalised: Kelly Osbourne's item (Q231182) carried the label
    "Paolo Maldini Osbourne" while every claim on it was still correct. The
    sitelink is a far more stable name for the same entity.
    """
    sl = entity.get("sitelinks", {}).get("enwiki", {}).get("title")
    if sl:
        return sl
    return entity.get("labels", {}).get("en", {}).get("value") or fallback


def wikidata_person(name):
    """Resolve a name to a real, dated human -- not merely the first search hit.

    wbsearchentities ranks "Angelina Jolie" with a namesake item ahead of the
    actress, so taking hits[0] silently builds the dataset around the wrong
    person. Score the top hits and keep the best-attested human instead.
    """
    q = ("https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json"
         "&language=en&type=item&limit=8&search=" + urllib.parse.quote(name))
    hits = wd_get(q).get("search", [])
    if not hits:
        return None

    ids = [h["id"] for h in hits[:6]]
    # one batched call instead of six: checking candidates individually was
    # enough extra Wikidata load to start tripping 429 under parallel workers
    bulk = wd_get("https://www.wikidata.org/w/api.php?action=wbgetentities"
                  "&format=json&props=claims%7Csitelinks%7Clabels&languages=en"
                  "&ids=" + urllib.parse.quote("|".join(ids)))
    ents = bulk.get("entities", {})

    best, best_key, qid_best = None, None, None
    for qid_c in ids:
        e = ents.get(qid_c)
        if not e or "missing" in e:
            continue
        cl = e.get("claims", {})
        types = {c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
                 for c in cl.get("P31", [])}
        if HUMAN not in types:
            continue
        if not cl.get("P569"):          # no birth date -> cannot compute any age
            continue
        key = (len(e.get("sitelinks", {})),
               1 if cl.get("P18") else 0,
               1 if (cl.get("P22") or cl.get("P25")) else 0)
        if best_key is None or key > best_key:
            best, best_key, qid_best = e, key, qid_c
    if best is None:
        return None
    e, qid = best, qid_best
    claims = e.get("claims", {})

    def first(pid):
        c = claims.get(pid)
        if not c:
            return None
        return c[0].get("mainsnak", {}).get("datavalue", {}).get("value")

    dob = first("P569")
    birth = None
    if isinstance(dob, dict) and dob.get("time"):
        t = dob["time"]  # +1980-02-27T00:00:00Z
        birth = t[1:11]
    img = first("P18")
    def ref(pid):
        v = first(pid)
        return v.get("id") if isinstance(v, dict) else None
    ccat = first("P373")
    return {
        "qid": qid,
        "label": best_label(e, name),
        "birth": birth,
        "image": img if isinstance(img, str) else None,
        "commons_cat": ccat if isinstance(ccat, str) else None,
        "father": ref("P22"),
        "mother": ref("P25"),
    }


def wikidata_by_qid(qid):
    ent = wd_get(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json")
    e = ent["entities"][qid]
    claims = e.get("claims", {})

    def first(pid):
        c = claims.get(pid)
        if not c:
            return None
        return c[0].get("mainsnak", {}).get("datavalue", {}).get("value")

    dob = first("P569")
    birth = None
    if isinstance(dob, dict) and dob.get("time"):
        birth = dob["time"][1:11]
    dod = first("P570")
    death = dod["time"][1:11] if isinstance(dod, dict) and dod.get("time") else None
    img = first("P18")
    ccat = first("P373")
    label = best_label(e, ccat if isinstance(ccat, str) else qid)
    return {"qid": qid, "label": label,
            "birth": birth, "death": death,
            "image": img if isinstance(img, str) else None,
            "commons_cat": ccat if isinstance(ccat, str) else None}


def commons_download(file_name, dest, width=1200):
    name = file_name.replace(" ", "_")
    url = ("https://commons.wikimedia.org/wiki/Special:FilePath/"
           + urllib.parse.quote(name) + f"?width={width}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as r:
        data = r.read()
    with open(dest, "wb") as f:
        f.write(data)
    return dest


def embed_faces(img, faces):
    """Return list of L2-normalised embeddings aligned to `faces` rows."""
    rec = recognizer()
    out = []
    for f in faces:
        try:
            aligned = rec.alignCrop(img, f)
            v = rec.feature(aligned).flatten().astype(np.float32)
            n = np.linalg.norm(v)
            out.append(v / n if n else v)
        except Exception:
            out.append(None)
    return out


def cosine(a, b):
    if a is None or b is None:
        return -1.0
    return float(np.dot(a, b))
