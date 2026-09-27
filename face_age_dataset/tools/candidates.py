"""Find people who are 40-50 now AND whose parents are photographable.

Guessing names from memory misses the real constraint: the parents. A subject
is only useful here if the parents themselves have Commons categories and
reference portraits, so we let Wikidata filter on exactly that.
"""

import json
import sys
import urllib.parse
import urllib.request
from datetime import date

ENDPOINT = "https://query.wikidata.org/sparql"
UA = "faces-dataset/0.2 (https://github.com/Malik1998/BiologyScrapper; research dataset build)"
THIS_YEAR = date.today().year

QUERY = """
SELECT ?p ?pLabel ?dob ?cat ?sl
       ?f ?fLabel ?fdob ?fcat
       ?m ?mLabel ?mdob ?mcat
WHERE {
  ?p wdt:P31 wd:Q5 ;
     wdt:P569 ?dob ;
     wdt:P373 ?cat ;
     wikibase:sitelinks ?sl .
  FILTER(YEAR(?dob) >= %d && YEAR(?dob) <= %d)
  FILTER(?sl >= 40)
  OPTIONAL { ?p wdt:P22 ?f . ?f wdt:P569 ?fdob ; wdt:P373 ?fcat . }
  OPTIONAL { ?p wdt:P25 ?m . ?m wdt:P569 ?mdob ; wdt:P373 ?mcat . }
  FILTER(BOUND(?f) || BOUND(?m))
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
ORDER BY DESC(?sl)
LIMIT 300
"""


def run_query(age_lo=40, age_hi=50):
    import time
    born_hi = THIS_YEAR - age_lo     # youngest allowed
    born_lo = THIS_YEAR - age_hi     # oldest allowed
    q = QUERY % (born_lo, born_hi)
    body = urllib.parse.urlencode({"query": q, "format": "json"}).encode()
    last = None
    for attempt in range(6):
        try:
            req = urllib.request.Request(
                ENDPOINT, data=body,
                headers={"User-Agent": UA,
                         "Accept": "application/sparql-results+json",
                         "Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = e
            # WDQS throttles to 1 req/min during outages; just wait it out
            wait = 65 if e.code == 429 else 20
            print(f"  WDQS {e.code}, retry in {wait}s ({attempt + 1}/6)", flush=True)
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


def collect(age_lo=40, age_hi=50):
    data = run_query(age_lo, age_hi)
    rows = {}
    for b in data["results"]["bindings"]:
        qid = b["p"]["value"].rsplit("/", 1)[-1]
        dob = b["dob"]["value"]
        by = year_of(dob)
        if not by:
            continue
        rec = rows.setdefault(qid, {
            "qid": qid,
            "name": b["pLabel"]["value"],
            "birth": dob[:10],
            "age_now": THIS_YEAR - by,
            "sitelinks": int(b["sl"]["value"]),
            "commons_cat": b["cat"]["value"],
            "father": None, "mother": None,
        })
        for role, pre in (("father", "f"), ("mother", "m")):
            if pre in b and rec[role] is None:
                pdob = b[pre + "dob"]["value"]
                ok, window = parent_ok(pdob, rec["age_now"])
                rec[role] = {
                    "qid": b[pre]["value"].rsplit("/", 1)[-1],
                    "name": b[pre + "Label"]["value"],
                    "birth": pdob[:10],
                    "commons_cat": b[pre + "cat"]["value"],
                    "window_40_50": window,
                    "feasible": ok,
                }
    out = []
    for r in rows.values():
        if not (age_lo <= r["age_now"] <= age_hi):
            continue
        feas = [x for x in (r["father"], r["mother"]) if x and x["feasible"]]
        if not feas:
            continue
        r["feasible_parents"] = len(feas)
        out.append(r)
    out.sort(key=lambda r: -r["sitelinks"])
    return out


if __name__ == "__main__":
    res = collect()
    json.dump(res, open(sys.argv[1] if len(sys.argv) > 1 else "work/candidates.json", "w"),
              ensure_ascii=False, indent=1)
    print(f"{len(res)} candidates\n")
    for r in res[:60]:
        ps = " + ".join(f"{p['name']}({p['birth'][:4]})"
                        for p in (r["father"], r["mother"]) if p and p["feasible"])
        print(f"{r['sitelinks']:4d}  {r['name']:<28} {r['age_now']}  <- {ps}")
