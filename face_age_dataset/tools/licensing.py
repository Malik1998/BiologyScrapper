"""May this photo be published (in a released dataset, a paper figure)?

Analysing a photo and publishing it are different questions: web picks carry
no licence at all, so they stay internal-only. Commons and Flickr files carry
the licence they were uploaded under, which decides what publishing requires.

    python tools/licensing.py      # (re)tag every slot in dataset/*/meta.json
"""

import glob
import json
import os
import re
import sys
from collections import Counter

# no conditions at all
FREE = re.compile(r"^(public domain|cc0|pdm|no restrictions|no known copyright|"
                  r"copyrighted free use|united states government)", re.I)
# free, but the author must be credited; -SA and GFDL also bind derivatives
ATTRIB = re.compile(r"^(cc by|attribution|gfdl|ogl|godl|european parliament)", re.I)


def publish_terms(entry):
    """(publishable, terms) for one slot entry."""
    if entry.get("source") == "web":
        return False, "no licence: web search pick, internal analysis only"
    lic = (entry.get("license") or "").strip()
    if not lic:
        return False, "licence unknown: check the source page before publishing"
    if FREE.match(lic):
        return True, "free: no conditions"
    if ATTRIB.match(lic):
        terms = f"credit author ({entry.get('author') or 'see source page'}), {lic}"
        if re.search(r"\bsa\b|gfdl", lic, re.I):
            terms += ", derivatives under the same licence"
        return True, terms
    return False, f"unrecognised licence {lic!r}: check before publishing"


def tag(entry):
    ok, terms = publish_terms(entry)
    entry["publishable"] = ok
    entry["publish_terms"] = terms
    return entry


def main():
    data = os.path.join(os.path.dirname(__file__), "..", "dataset")
    count = Counter()
    for mp in sorted(glob.glob(os.path.join(data, "*", "meta.json"))):
        m = json.load(open(mp))
        for e in m["slots"].values():
            if e.get("status") == "ok":
                tag(e)
                count[e["publishable"]] += 1
        s = m["slots"]
        pub = {k for k, e in s.items() if e.get("status") == "ok" and e.get("publishable")}
        m["publishable_minimum_set"] = ({"subject_now", "subject_young"} <= pub
                                        and bool(pub & {"father_40s", "mother_40s"}))
        json.dump(m, open(mp, "w"), ensure_ascii=False, indent=2)
    print(f"publishable: {count[True]}  internal only: {count[False]}")


if __name__ == "__main__":
    sys.exit(main())
