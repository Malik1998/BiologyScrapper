"""Find people who are 40-50 now AND whose parents are photographable.

Guessing names from memory misses the real constraint: the parents. A subject
is only useful here if the parents themselves have Commons categories and
reference portraits, so we let Wikidata filter on exactly that.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date

ENDPOINT = "https://query.wikidata.org/sparql"
UA = "faces-dataset/0.2 (https://github.com/Malik1998/BiologyScrapper; research dataset build)"
THIS_YEAR = date.today().year

# Subjects born %d-%d: old enough to have been photographed at 40-50 at some
# point, young enough that their 20s fall in the era of dated digital photos.
# Being 40-50 *now* is not required -- the subject_now slot only needs a
# photo taken at 40-50.
# One query per parent role with the parent REQUIRED: that join is small and
# drives the plan. OPTIONAL parents made WDQS scan every dated human (504).
QUERY = """
SELECT ?p ?pLabel ?dob ?cat ?sl ?x ?xLabel ?xdob ?xcat
WHERE {
  ?p wdt:%s ?x .
  ?x wdt:P373 ?xcat ; wdt:P569 ?xdob .
  ?p wdt:P373 ?cat ; wdt:P569 ?dob ; wikibase:sitelinks ?sl .
  FILTER(YEAR(?dob) >= %d && YEAR(?dob) <= %d)
  FILTER(?sl >= %d)
  ?p wdt:P31 wd:Q5 .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""


def run_query(born_lo=1950, born_hi=1985, min_sitelinks=8, prop="P22"):
    import time
    q = QUERY % (prop, born_lo, born_hi, min_sitelinks)
    body = urllib.parse.urlencode({"query": q, "format": "json"}).encode()
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(
                ENDPOINT, data=body,
                headers={"User-Agent": UA,
                         "Accept": "application/sparql-results+json",
                         "Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=180) as r:
                # labels can carry raw control characters (a tab in a name)
                return json.loads(r.read().decode("utf-8"), strict=False)
        except urllib.error.HTTPError as e:
            last = e
            # WDQS throttles to 1 req/min during outages; just wait it out
            wait = 65 if e.code == 429 else 20
            print(f"  WDQS {e.code}, retry in {wait}s ({attempt + 1}/4)", flush=True)
            time.sleep(wait)
        except Exception as e:
            last = e
            time.sleep(20)
    raise last


def year_of(iso):
    try:
        return int(iso[:4]) if not iso.startswith("-") else None
    except Exception:
        return None


def parent_ok(pdob, subject_age_now):
    """Parent is useful if some real year exists where they were 40-50."""
    py = year_of(pdob)
    if not py:
        return False, None
    lo_year, hi_year = py + 40, py + 50
    # that window has to have actually happened, and photography has to exist
    if hi_year < 1920:
        return False, None
    return lo_year <= THIS_YEAR, (lo_year, min(hi_year, THIS_YEAR))


def collect(born_lo=1950, born_hi=1985, min_sitelinks=8):
    rows = {}
    # one query per decade: the whole range at a low sitelink bar times out
    chunks = [(lo, min(lo + 9, born_hi)) for lo in range(born_lo, born_hi + 1, 10)]
    for (role, prop), (lo, hi) in [(r, c) for r in (("father", "P22"), ("mother", "P25"))
                                   for c in chunks]:
        bindings = run_query(lo, hi, min_sitelinks, prop)["results"]["bindings"]
        print(f"  {role} {lo}-{hi}: {len(bindings)} rows", flush=True)
        for b in bindings:
            qid = b["p"]["value"].rsplit("/", 1)[-1]
            dob = b["dob"]["value"]
            if not year_of(dob):
                continue
            rec = rows.setdefault(qid, {
                "qid": qid,
                "name": b["pLabel"]["value"],
                "birth": dob[:10],
                "sitelinks": int(b["sl"]["value"]),
                "commons_cat": b["cat"]["value"],
                "father": None, "mother": None,
            })
            if rec[role] is None:
                pdob = b["xdob"]["value"]
                ok, window = parent_ok(pdob, None)
                rec[role] = {
                    "qid": b["x"]["value"].rsplit("/", 1)[-1],
                    "name": b["xLabel"]["value"],
                    "birth": pdob[:10],
                    "commons_cat": b["xcat"]["value"],
                    "window_40_50": window,
                    "feasible": ok,
                }
    out = [r for r in rows.values()
           if any(x and x["feasible"] for x in (r["father"], r["mother"]))
           and not r["name"].startswith("Q")]          # no English label
    return out


def category_sizes(cats):
    """files + subcategories per Commons category, 50 titles per request."""
    sys.path.insert(0, os.path.dirname(__file__))
    import commons as C
    sizes, cats = {}, sorted(set(cats))
    for i in range(0, len(cats), 50):
        batch = ["Category:" + c for c in cats[i:i + 50]]
        d = C.api(action="query", titles="|".join(batch), prop="categoryinfo", redirects="1")
        back = {r["to"]: r["from"] for r in d.get("query", {}).get("redirects", [])}
        for p in d.get("query", {}).get("pages", []):
            ci = p.get("categoryinfo") or {}
            t = back.get(p["title"], p["title"])[len("Category:"):]
            # a subcategory of a person is usually a year or an event: count it
            # as several files
            sizes[t] = ci.get("files", 0) + 10 * ci.get("subcats", 0)
    return sizes


def rank(cands, min_subject=15, min_parent=8):
    """Keep people whose own and whose parent's categories are big enough to
    plausibly hold dated photos at the ages we need; best-covered first."""
    cats = [c["commons_cat"] for c in cands]
    for c in cands:
        cats += [p["commons_cat"] for p in (c["father"], c["mother"]) if p]
    sz = category_sizes(cats)
    out = []
    for c in cands:
        s = sz.get(c["commons_cat"], 0)
        par = [(sz.get(p["commons_cat"], 0), p) for p in (c["father"], c["mother"])
               if p and p["feasible"]]
        best = max((x for x, _ in par), default=0)
        c["subject_size"], c["parent_size"] = s, best
        if s >= min_subject and best >= min_parent:
            c["score"] = min(s, 300) * min(best, 300)
            out.append(c)
    out.sort(key=lambda c: -c["score"])
    return out


if __name__ == "__main__":
    import os
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default="work/candidates.json")
    ap.add_argument("--born", default="1950-1985", help="subject birth years, e.g. 1930-1986")
    ap.add_argument("--min-sitelinks", type=int, default=8)
    ap.add_argument("--min-subject", type=int, default=15, help="min files in the subject's category")
    ap.add_argument("--min-parent", type=int, default=8, help="min files in the parent's category")
    a = ap.parse_args()
    out_path = a.out
    lo, hi = (int(x) for x in a.born.split("-"))
    cands = collect(lo, hi, a.min_sitelinks)
    print(f"{len(cands)} people with a parent on Commons")
    ranked = rank(cands, a.min_subject, a.min_parent)
    json.dump(ranked, open(out_path, "w"), ensure_ascii=False, indent=1)
    print(f"{len(ranked)} with big enough categories -> {out_path}\n")
    for r in ranked[:40]:
        ps = " + ".join(f"{p['name']}({p['birth'][:4]})"
                        for p in (r["father"], r["mother"]) if p and p["feasible"])
        print(f"{r['subject_size']:5d} {r['parent_size']:5d}  {r['name']:<28} {r['birth'][:4]}  <- {ps}")
