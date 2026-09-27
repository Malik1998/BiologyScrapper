"""Web image search (via the `ddgs` metasearch library) as a last-resort source.

Used only when Commons is thin for a slot. The age still has to be arithmetic,
so a result counts only if the year is written in its own caption ("... at
the 2005 Oscars") and no other year, in the caption or URL, contradicts it. That gives
year precision at best, and the pages carry no reusable licence -- so every
pick from here is flagged for a visual check and is for internal research
only, never for redistribution.
"""

import hashlib
import re
import threading
import time
from datetime import date
from urllib.parse import urlparse

import commons as C

# Stock-photo previews are watermarked across the face, which ruins both the
# landmark geometry and the identity match; their licences also forbid reuse.
BLOCKED = ("gettyimages", "alamy", "shutterstock", "istockphoto", "dreamstime",
           "depositphotos", "123rf", "agefotostock", "pond5", "bigstockphoto",
           "stock.adobe", "zimbio", "pinterest", "pinimg",
           # From the first visual review (106 picks, 60 rejected): these hosts
           # caption an item by its release/sale year, while the photo on it is
           # older -- album covers, trading cards, film thumbnails, fan art.
           "youtube.", "ytimg.", "youtu.be", "ebay.", "etsy.", "discogs.",
           "abebooks.", "amazon.", "deviantart.", "fanaticscollect",
           "auctions.yahoo", "magazinecollectors", "tumblr.", "agemdb.")
# Caption words that mean "the year is of a product or an article, not of the
# photo": covers, cards, posters, reissues, look-ahead pieces.
BAD_CAPTION = re.compile(
    r"\b(album|cd|lp|vinyl|reissue|cover|topps|card|autograph|signed|poster|"
    r"souvenir|full movie|trailer|box office|net worth|forecast|upcoming|tickets|"
    r"birthday|collection|issue)\b", re.I)
MONTHS = {m: i + 1 for i, m in enumerate(
    "january february march april may june july august september october november december".split())}
MONTHS.update({m: i + 1 for i, m in enumerate(
    "janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split())})
MONTHS.update({m[:3]: n for m, n in list(MONTHS.items()) if len(m) > 3})
WEB_ID_MIN = 0.40   # every wrong-person pick in review but two was below this
YEAR = re.compile(r"(?<!\d)(19[5-9]\d|20[0-4]\d)(?!\d)")

_last = [0.0]
_lock = threading.Lock()
GAP = 2.0
PER_QUERY = 40


def _search(query):
    from ddgs import DDGS
    for attempt in range(len(C.BACKOFF) + 1):
        C._wait_turn(_last, _lock, GAP)
        try:
            return list(DDGS().images(query, max_results=PER_QUERY))
        except Exception as e:
            msg = str(e).lower()
            if "ratelimit" in msg or "429" in msg or "202" in msg:
                if attempt == len(C.BACKOFF):
                    raise C.RateLimited(f"web search rate-limited: {e}")
                time.sleep(C.BACKOFF[attempt])
                continue
            if "no results" in msg:
                return []
            if attempt >= 2:
                return []
            time.sleep(3)
    return []


def _years_in(r):
    text = " ".join(str(r.get(k) or "") for k in ("title", "url", "image"))
    return {int(y) for y in YEAR.findall(text) if int(y) <= date.today().year}


def harvest(name, birth, age_lo, age_hi, min_px=500):
    name = name.split(",")[0].strip()
    by, bm, bd = [int(x) for x in birth.split("-")]
    first = _norm(name).split() or [""]
    last = first[-1]
    rows, seen = [], set()
    for year in range(by + age_lo, min(by + age_hi + 1, date.today().year) + 1):
        for r in _search(f'"{name}" {year}'):
            img = r.get("image") or ""
            if not img or img in seen:
                continue
            seen.add(img)
            host = urlparse(img).netloc + " " + urlparse(r.get("url") or "").netloc
            if any(b in host for b in BLOCKED):
                continue
            title = r.get("title") or ""
            # The caption has to name this person, first name included: with
            # the surname alone, "James McCartney" matched photos of Paul and
            # "Ben Quayle" photos of Dan.
            tn = _norm(title + " " + (r.get("url") or ""))
            if not all(t in tn.split() for t in (first[0], last)):
                continue
            if BAD_CAPTION.search(title):
                continue
            years = _years_in(r)
            if years != {year}:
                continue            # no year stated, or several: cannot date it
            # The year must be in the caption. A year only in the URL is the
            # article's date: Peter Phillips' 2008 wedding photo came back as
            # "2018" from a 2018 article URL, i.e. age 40 instead of 30.
            if str(year) not in (r.get("title") or ""):
                continue
            try:
                w, h = int(r.get("width") or 0), int(r.get("height") or 0)
            except ValueError:
                w = h = 0
            if w and h and min(w, h) < min_px:
                continue
            taken = _caption_date(title, year) or (year, None, None, "year")
            age, lo_age, unc = C.age_on((by, bm, bd), taken)
            # Without a full date the age is one of two values; both must be in
            # range (10 review rejects were a birthday away from the window).
            if not (age_lo <= lo_age and lo_age + unc <= age_hi):
                continue
            prec = taken[3]
            rows.append({
                "title": "File:web_" + hashlib.sha1(img.encode()).hexdigest()[:16] + ".jpg",
                "source": "web",
                "dl_url": img,
                "big_url": img,
                "file_url": img,
                "page": r.get("url"),
                "w": w, "h": h,
                "date": f"{taken[0]:04d}" + (f"-{taken[1]:02d}" if taken[1] else "")
                        + (f"-{taken[2]:02d}" if taken[2] else ""),
                "date_precision": prec,
                "date_source": "search_title_year",
                "date_conflict": False,
                "age": age,
                "age_uncertainty": unc,
                "license": None,
                "author": urlparse(r.get("url") or img).netloc,
                "search_title": (r.get("title") or "")[:200],
            })
    return rows


def _caption_date(title, year):
    """A full date in the caption, if there is one, for exact age."""
    t = title.lower()
    m = re.search(r"(\d{1,2})[./](\d{1,2})[./](%d)" % year, t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 and b <= 12:
            return (year, b, a, "day")          # dd.mm.yyyy
        if b > 12 and a <= 12:
            return (year, a, b, "day")          # mm/dd/yyyy
        if "." in m.group(0) and b <= 12:
            return (year, b, a, "day")          # dotted dates are European
        return None                             # 03/04/2020: ambiguous
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th|er)?\s+([a-zéû]+)\.?,?\s+%d" % year, t)
    if m and m.group(2) in MONTHS:
        return (year, MONTHS[m.group(2)], int(m.group(1)), "day")
    m = re.search(r"([a-zéû]+)\.?\s+(\d{1,2}),?\s+%d" % year, t)
    if m and m.group(1) in MONTHS:
        return (year, MONTHS[m.group(1)], int(m.group(2)), "day")
    m = re.search(r"\b([a-zéû]+)\s+%d" % year, t)
    if m and m.group(1) in MONTHS:
        return (year, MONTHS[m.group(1)], None, "month")
    return None


def _norm(t):
    return " ".join(re.sub(r"[^\w\s]", " ", str(t).lower()).split())
