"""Flickr as a second source of dated, openly licensed photos.

Commons is curated but thin for many people -- especially parents in the
1990s-2000s and event photos of their children. Flickr holds much of that same
event photography, with `date_taken` from the camera and an explicit licence,
so the age on a photo is still arithmetic rather than a guess.

Needs a (free) API key in FLICKR_API_KEY or in work/flickr_key (gitignored);
without it this source is skipped.
"""

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

import commons as C

API = "https://api.flickr.com/services/rest/"
_KEY_FILE = os.path.join(os.path.dirname(__file__), "..", "work", "flickr_key")


def _load_key():
    k = os.environ.get("FLICKR_API_KEY")
    if not k and os.path.exists(_KEY_FILE):
        k = open(_KEY_FILE).read().strip()
    return k or None


KEY = _load_key()

# Only licences that allow reuse in a dataset: CC BY (4), CC BY-SA (5),
# no known copyright restrictions (7), US Government work (8), CC0 (9),
# Public Domain Mark (10). NC/ND variants are left out on purpose.
LICENSES = {"4": "CC BY 2.0", "5": "CC BY-SA 2.0", "7": "No known copyright restrictions",
            "8": "United States Government Work", "9": "CC0 1.0", "10": "Public Domain Mark 1.0"}

_last = [0.0]
_lock = threading.Lock()
GAP = 1.0           # Flickr allows 3600 calls/hour per key
_warned = [False]


def enabled():
    if not KEY and not _warned[0]:
        _warned[0] = True
        print("  (flickr: FLICKR_API_KEY not set, source skipped)", flush=True)
    return bool(KEY)


def _call(**params):
    params.update(api_key=KEY, format="json", nojsoncallback=1)
    url = API + "?" + urllib.parse.urlencode(params)
    for attempt in range(len(C.BACKOFF) + 1):
        C._wait_turn(_last, _lock, GAP)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": C.UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.load(r)
            if data.get("stat") != "ok":
                raise RuntimeError(f"flickr: {data.get('message')}")
            return data
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                if attempt == len(C.BACKOFF):
                    raise C.RateLimited(f"Flickr {e.code} after {attempt} retries")
                time.sleep(C.BACKOFF[attempt])
                continue
            raise


def _pick(p, keys):
    for k in keys:
        if p.get("url_" + k):
            return p["url_" + k], int(p.get("width_" + k) or 0), int(p.get("height_" + k) or 0)
    return None, 0, 0


def harvest(name, birth, age_lo, age_hi, max_pages=2, min_px=600):
    """Rows in the same shape as commons.harvest, for one person and age range."""
    if not enabled():
        return []
    # "Prince Harry, Duke of Sussex" is nobody's Flickr tag; the part before
    # the comma is how photographers caption people
    name = name.split(",")[0].strip()
    by, bm, bd = [int(x) for x in birth.split("-")]
    # the whole window in which any day could give an age inside the range
    lo = f"{by + age_lo:04d}-{bm:02d}-{bd:02d}"
    hi = f"{by + age_hi + 1:04d}-{bm:02d}-{bd:02d}"
    rows, seen = [], set()
    for page in range(1, max_pages + 1):
        d = _call(method="flickr.photos.search", text=f'"{name}"',
                  license=",".join(LICENSES), min_taken_date=lo, max_taken_date=hi,
                  content_type=1, media="photos", sort="relevance",
                  extras="date_taken,license,owner_name,url_l,url_c,url_k,url_o,o_dims",
                  per_page=250, page=page)
        photos = d.get("photos", {})
        for p in photos.get("photo", []):
            if p["id"] in seen:
                continue
            seen.add(p["id"])
            # granularity 0 = exact date; unknown dates are camera defaults
            if str(p.get("datetakenunknown")) == "1" or str(p.get("datetakengranularity", "0")) != "0":
                continue
            m = re.match(r"(\d{4})-(\d{2})-(\d{2})", p.get("datetaken", ""))
            if not m:
                continue
            taken = (int(m.group(1)), int(m.group(2)), int(m.group(3)), "day")
            age, _, unc = C.age_on((by, bm, bd), taken)
            if not (age_lo <= age <= age_hi):
                continue
            small, w, h = _pick(p, ("l", "c"))
            big, bw, bh = _pick(p, ("o", "k", "l"))
            if not small or min(bw or w, bh or h) < min_px:
                continue
            rows.append({
                # a Commons-style title keeps cache file names and logs uniform;
                # dl_url/big_url tell the downloader it is not a Commons file
                "title": f"File:flickr_{p['id']}.jpg",
                "source": "flickr",
                "dl_url": small,
                "big_url": big,
                "file_url": big,
                "page": f"https://www.flickr.com/photos/{p['owner']}/{p['id']}",
                "w": bw or w, "h": bh or h,
                "date": p["datetaken"][:10],
                "date_precision": "day",
                "date_source": "flickr_date_taken",
                "date_conflict": False,
                "age": age,
                "age_uncertainty": unc,
                "license": LICENSES.get(str(p.get("license"))),
                "author": (p.get("ownername") or "")[:120],
            })
        if page >= int(photos.get("pages", 1)):
            break
    return rows
