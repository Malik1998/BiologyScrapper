"""Identity matching so we pick the right face out of a crowd.

Reference portraits come from Wikidata P18, which is curated per person. Each
candidate photo may contain many faces; we embed them all with SFace and keep
the one closest to the reference. Cosine similarity is also what tells us a
photo is of the wrong person entirely.
"""

import json
import threading
import os
import urllib.parse
import urllib.request

import cv2
import numpy as np

UA = "faces-dataset/0.2 (https://github.com/Malik1998/BiologyScrapper; research dataset build)"
SFACE = os.path.join(os.path.dirname(__file__), "..", "models", "sface.onnx")
# OpenCV's documented same-identity cosine threshold for SFace
SAME_ID = 0.363

_tls = threading.local()


def recognizer():
    """One recognizer per thread. A single shared SFace net is not thread-safe:
    under harvest_all -j 6 concurrent feature() calls handed one thread
    another's embedding, so identity scores belonged to the wrong face
    (Freddie Prinze Jr.'s slot scored 0.82 and cropped Sarah Michelle Gellar)."""
    r = getattr(_tls, "rec", None)
    if r is None:
        r = cv2.FaceRecognizerSF.create(SFACE, "")
        _tls.rec = r
    return r


import time

_wd_lock = threading.Lock()
_wd_last = [0.0]
WD_GAP = 1.2


WD_CACHE = os.path.join(os.path.dirname(__file__), "..", "work", "wd_cache")


def wd_get(url):
    """Throttled, retried and cached on disk.

    Every retry of a person used to look them and their parents up again, and
    Wikidata answered with 429s long after Commons had calmed down. Entities
    barely change, so one answer per URL is enough.
    """
    import hashlib
    cp = os.path.join(WD_CACHE, hashlib.sha1(url.encode()).hexdigest() + ".json")
    if os.path.exists(cp):
        try:
            return json.load(open(cp))
        except Exception:
            pass
    data = _wd_fetch(url)
    os.makedirs(WD_CACHE, exist_ok=True)
    tmp = cp + f".{threading.get_ident()}.tmp"
    json.dump(data, open(tmp, "w"))
    os.replace(tmp, cp)
    return data


def _wd_fetch(url):
    from commons import RateLimited
    backoff = (10, 30, 60)
    for attempt in range(len(backoff) + 1):
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
            if e.code in (429, 503):
                if attempt < len(backoff):
                    time.sleep(backoff[attempt])
                    continue
                raise RateLimited(f"Wikidata {e.code} after {attempt} retries")
            raise
        except Exception:
            if attempt >= 4:
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


def _norm(t):
    return " ".join(str(t or "").replace(",", " ").replace(".", " ").lower().split())


def _match(e, want):
    """2 = the item's own name, 1 = only an alias, 0 = neither.

    Aliases alone are not enough: Paul McCartney carries the alias
    "James McCartney", which is also his son's actual name.
    """
    own = {_norm(e.get("labels", {}).get("en", {}).get("value")),
           _norm(e.get("sitelinks", {}).get("enwiki", {}).get("title"))}
    if want in own:
        return 2
    if want in {_norm(a.get("value")) for a in e.get("aliases", {}).get("en", [])}:
        return 1
    return 0


def wikidata_person(name, qid=None):
    """Resolve a name to a real, dated human -- not merely the first search hit.

    wbsearchentities ranks "Angelina Jolie" with a namesake item ahead of the
    actress, so taking hits[0] silently builds the dataset around the wrong
    person. Score the top hits and keep the best-attested human instead --
    but an exact name/alias match outranks fame: fame alone turned
    "James McCartney" into Paul and "Cameron Douglas" into Cameron Bright.
    `qid` skips the search for names that stay ambiguous.
    """
    if qid:
        return _person_from_ids([qid], name)
    q = ("https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json"
         "&language=en&type=item&limit=8&search=" + urllib.parse.quote(name))
    hits = wd_get(q).get("search", [])
    if not hits:
        return None

    return _person_from_ids([h["id"] for h in hits[:6]], name)


def _person_from_ids(ids, name):
    # one batched call instead of six: checking candidates individually was
    # enough extra Wikidata load to start tripping 429 under parallel workers
    bulk = wd_get("https://www.wikidata.org/w/api.php?action=wbgetentities"
                  "&format=json&props=claims%7Csitelinks%7Clabels%7Caliases&languages=en"
                  "&ids=" + urllib.parse.quote("|".join(ids)))
    ents = bulk.get("entities", {})

    want = _norm(name)
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
        key = (2 if len(ids) == 1 else _match(e, want),
               len(e.get("sitelinks", {})),
               1 if cl.get("P18") else 0,
               1 if (cl.get("P22") or cl.get("P25")) else 0)
        if best_key is None or key > best_key:
            best, best_key, qid_best = e, key, qid_c
    if best is None:
        return None
    if best_key[0] == 0:
        print(f"!! no exact Wikidata match for {name!r}, using "
              f"{best_label(best, name)!r}; pin it with a qid in seed_people.json")
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


# citizenship (P27) -> language whose press to search in; only these, so
# Western subjects are not searched a second time in Russian for nothing
NATIVE_BY_COUNTRY = {
    "Q159": "ru", "Q15180": "ru", "Q34266": "ru",                  # Russia, USSR
    "Q79": "ar", "Q851": "ar", "Q878": "ar", "Q846": "ar", "Q810": "ar",
    "Q822": "ar", "Q398": "ar", "Q817": "ar", "Q842": "ar",        # Arab states
    "Q183": "de", "Q40": "de", "Q39": "de",                         # DE, AT, CH
    "Q34": "sv",                                                    # Sweden
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
    # names as the local press writes them, for web search: "Иван Ургант",
    # "تميم بن حمد آل ثاني" find photos the English name never does
    langs = []
    for c in claims.get("P27", []):
        cid = (c.get("mainsnak", {}).get("datavalue", {}).get("value") or {}).get("id")
        if NATIVE_BY_COUNTRY.get(cid) and NATIVE_BY_COUNTRY[cid] not in langs:
            langs.append(NATIVE_BY_COUNTRY[cid])
    native = []
    for lang in langs:
        v = e.get("labels", {}).get(lang, {}).get("value")
        if lang == "ru" and v and len(v.split()) == 3:
            v = f"{v.split()[0]} {v.split()[2]}"     # the press drops the patronymic
        if v and v != label and v not in native:
            native.append(v)
    return {"qid": qid, "label": label, "native_names": native,
            "birth": birth, "death": death,
            "image": img if isinstance(img, str) else None,
            "commons_cat": ccat if isinstance(ccat, str) else None}


def commons_download(file_name, dest, width=1280):
    import commons
    from face import thumb_url
    url = thumb_url("File:" + file_name, width)
    if not commons.download(url, dest, min_bytes=1000):
        raise FileNotFoundError(url)
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
