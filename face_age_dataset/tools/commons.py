"""Wikimedia Commons harvester: find dated photos of a person and compute age on each.

The whole point of using Commons is that files carry a date in their metadata,
so "age on this photo" is arithmetic instead of a guess.
"""

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date

API = "https://commons.wikimedia.org/w/api.php"
UA = "faces-dataset/0.1 (research dataset build; python-urllib)"

_last_call = [0.0]
MIN_GAP = 1.1  # Commons is strict; stay well under its limit


def api(**params):
    params.setdefault("format", "json")
    params.setdefault("formatversion", "2")
    body = urllib.parse.urlencode(params).encode()
    for attempt in range(6):
        gap = time.time() - _last_call[0]
        if gap < MIN_GAP:
            time.sleep(MIN_GAP - gap)
        req = urllib.request.Request(
            API, data=body,
            headers={"User-Agent": UA,
                     "Content-Type": "application/x-www-form-urlencoded",
                     "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                _last_call[0] = time.time()
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    raw = gzip.decompress(raw)
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            _last_call[0] = time.time()
            if e.code in (429, 503) and attempt < 5:
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except Exception:
            _last_call[0] = time.time()
            if attempt == 5:
                raise
            time.sleep(3 * (attempt + 1))


def category_files(category, depth=1, limit=1200):
    """Return file titles in a category, optionally descending into subcategories."""
    if not category.startswith("Category:"):
        category = "Category:" + category
    seen, files, queue = set(), [], [(category, 0)]
    while queue:
        cat, d = queue.pop(0)
        if cat in seen:
            continue
        seen.add(cat)
        cont = {}
        while True:
            data = api(action="query", list="categorymembers", cmtitle=cat,
                       cmlimit="500", cmtype="file|subcat", **cont)
            for m in data.get("query", {}).get("categorymembers", []):
                t = m["title"]
                if t.startswith("Category:"):
                    if d < depth:
                        queue.append((t, d + 1))
                elif t.startswith("File:"):
                    files.append(t)
            if "continue" in data and len(files) < limit:
                cont = data["continue"]
            else:
                break
        if len(files) >= limit:
            break
    return list(dict.fromkeys(files))


def imageinfo(titles):
    """Fetch size + extmetadata for a list of File: titles (batched by 50)."""
    out = {}
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        data = api(action="query", titles="|".join(batch), prop="imageinfo",
                   iiprop="url|size|extmetadata|mime",
                   iiextmetadatafilter="DateTimeOriginal|DateTime|License|LicenseShortName|Artist|Credit|ImageDescription|Categories")
        for p in data.get("query", {}).get("pages", []):
            ii = (p.get("imageinfo") or [{}])[0]
            if ii:
                out[p["title"]] = ii
    return out


DATE_PATTERNS = [
    (re.compile(r"(\d{4})-(\d{2})-(\d{2})"), "day"),
    (re.compile(r"(\d{4})-(\d{2})(?!\d)"), "month"),
    (re.compile(r"\b(\d{4})\b"), "year"),
]


def parse_date(raw):
    """Return (year, month, day|None, precision) from a messy Commons date string."""
    if not raw:
        return None
    txt = re.sub(r"<[^>]+>", " ", str(raw))
    for pat, prec in DATE_PATTERNS:
        m = pat.search(txt)
        if m:
            g = m.groups()
            y = int(g[0])
            if not (1900 <= y <= date.today().year):
                continue
            mo = int(g[1]) if len(g) > 1 else None
            d = int(g[2]) if len(g) > 2 else None
            if mo and not (1 <= mo <= 12):
                mo, d, prec = None, None, "year"
            return (y, mo, d, prec)
    return None


CAT_YEAR = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
# uploads of scanned archives carry the digitisation date in EXIF, not the shot date
ARCHIVE_HINT = re.compile(r"DPLA|WHPO|NARA|LOC\b|Library of Congress|National Archives"
                          r"|Bundesarchiv|scan", re.I)


def category_years(em, title=""):
    """Years mentioned in a file's own categories -- curator-assigned, so they
    describe the event rather than when someone ran a scanner."""
    raw = (em.get("Categories", {}) or {}).get("value") or ""
    years = set()
    for chunk in str(raw).split("|"):
        for m in CAT_YEAR.finditer(chunk):
            y = int(m.group(1))
            if 1900 <= y <= date.today().year:
                years.add(y)
    return sorted(years)


def resolve_date(em, title, raw_date):
    """Decide the real capture date, preferring category years over EXIF when
    they disagree -- that disagreement is the signature of a digitised archive."""
    exif = parse_date(raw_date)
    cyears = category_years(em, title)
    archival = bool(ARCHIVE_HINT.search(title))

    if exif and cyears and exif[0] not in cyears:
        # EXIF contradicts the curators. Trust them, and say so.
        best = min(cyears, key=lambda y: abs(y - exif[0])) if not archival else min(cyears)
        return (best, None, None, "year"), "category_override", True
    if exif and not cyears and archival:
        # archival scan with no corroborating year: unusable, we cannot date it
        return None, "unverifiable_archival", True
    if exif:
        return exif, "exif", False
    if cyears:
        return (min(cyears), None, None, "year"), "category_only", False
    return None, "none", False


def age_on(birth, taken):
    """Age in years plus uncertainty, given birth date and parsed photo date."""
    by, bm, bd = birth
    y, mo, d, prec = taken
    if prec == "day":
        a = y - by - ((mo, d) < (bm, bd))
        return a, a, 0
    if prec == "month":
        lo = y - by - ((mo, 31) < (bm, bd))
        hi = y - by - ((mo, 1) < (bm, bd))
        return round((lo + hi) / 2), lo, 1
    lo = y - by - 1
    hi = y - by
    return round((lo + hi) / 2), lo, 1


def harvest(category, birth, age_lo, age_hi, depth=1, min_px=600):
    by, bm, bd = [int(x) for x in birth.split("-")]
    titles = category_files(category, depth=depth)
    info = imageinfo(titles)
    rows = []
    for t, ii in info.items():
        if not str(ii.get("mime", "")).startswith("image/"):
            continue
        w, h = ii.get("width", 0), ii.get("height", 0)
        if min(w, h) < min_px:
            continue
        em = ii.get("extmetadata", {})
        raw = (em.get("DateTimeOriginal", {}) or {}).get("value") or \
              (em.get("DateTime", {}) or {}).get("value")
        parsed, dsrc, conflict = resolve_date(em, t, raw)
        if not parsed:
            continue
        age, age_lo_v, unc = age_on((by, bm, bd), parsed)
        if not (age_lo <= age <= age_hi):
            continue
        y, mo, d, prec = parsed
        rows.append({
            "title": t,
            "file_url": ii.get("url"),
            "page": ii.get("descriptionurl"),
            "w": w, "h": h,
            "date": f"{y:04d}" + (f"-{mo:02d}" if mo else "") + (f"-{d:02d}" if d else ""),
            "date_precision": prec,
            "date_source": dsrc,
            "date_conflict": conflict,
            "age": age,
            "age_uncertainty": unc if not conflict else max(unc, 1),
            "license": (em.get("LicenseShortName", {}) or {}).get("value"),
            "author": re.sub(r"<[^>]+>", "", str((em.get("Artist", {}) or {}).get("value") or ""))[:120].strip(),
        })
    rows.sort(key=lambda r: (-min(r["w"], r["h"])))
    return rows


YEAR_CAT = re.compile(r"\bin (\d{4})\b")


def harvest_by_year(person_cat, birth, age_lo, age_hi, min_px=600):
    """Harvest via 'X by year' subcategories.

    The year comes from the category name, which curators assign from the event
    itself -- unlike EXIF, it is not corrupted by later digitisation of archives.
    """
    by, bm, bd = [int(x) for x in birth.split("-")]
    base = person_cat if person_cat.startswith("Category:") else "Category:" + person_cat
    d = api(action="query", list="categorymembers",
            cmtitle=base + " by year", cmtype="subcat", cmlimit=200)
    year_cats = []
    for m in d.get("query", {}).get("categorymembers", []):
        mt = YEAR_CAT.search(m["title"])
        if not mt:
            continue
        yr = int(mt.group(1))
        # keep a year if any age it can imply falls in range
        if age_lo <= (yr - by) <= age_hi or age_lo <= (yr - by - 1) <= age_hi:
            year_cats.append((yr, m["title"]))
    rows = []
    budget = 900        # bound metadata cost; huge categories add little variety
    for yr, cat in sorted(year_cats):
        if budget <= 0:
            break
        titles = category_files(cat, depth=0)
        if not titles:
            continue
        titles = titles[:budget]
        budget -= len(titles)
        info = imageinfo(titles)
        for t, ii in info.items():
            if not str(ii.get("mime", "")).startswith("image/"):
                continue
            w, h = ii.get("width", 0), ii.get("height", 0)
            if min(w, h) < min_px:
                continue
            em = ii.get("extmetadata", {})
            raw = (em.get("DateTimeOriginal", {}) or {}).get("value") or ""
            parsed = parse_date(raw)
            # trust the category year; use EXIF only to sharpen month/day
            if parsed and parsed[0] == yr:
                age, _, unc = age_on((by, bm, bd), parsed)
                y, mo, dd, prec = parsed
                datestr = f"{y:04d}" + (f"-{mo:02d}" if mo else "") + (f"-{dd:02d}" if dd else "")
            else:
                age, _, unc = age_on((by, bm, bd), (yr, None, None, "year"))
                datestr, prec = str(yr), "year"
            if not (age_lo <= age <= age_hi):
                continue
            rows.append({
                "title": t,
                "file_url": ii.get("url"),
                "page": ii.get("descriptionurl"),
                "w": w, "h": h,
                "date": datestr,
                "date_precision": prec,
                "date_source": "category_year" if prec == "year" else "exif+category",
                "age": age,
                "age_uncertainty": unc,
                "license": (em.get("LicenseShortName", {}) or {}).get("value"),
                "author": re.sub(r"<[^>]+>", "", str((em.get("Artist", {}) or {}).get("value") or ""))[:120].strip(),
            })
    rows.sort(key=lambda r: -min(r["w"], r["h"]))
    return rows


if __name__ == "__main__":
    cat, birth, lo, hi = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    depth = int(sys.argv[5]) if len(sys.argv) > 5 else 1
    rows = harvest(cat, birth, lo, hi, depth=depth)
    print(json.dumps(rows, ensure_ascii=False, indent=1))
