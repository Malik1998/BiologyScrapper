"""Exact age bounds for every photo, and whether they sit inside the window.

The Commons harvest admits a photo when the *middle* of its possible ages is
in the window, so a photo dated only "1963" of someone born in 1913 (age 49
or 50 -- fine) passes, but so does one of someone born in 1912 (50 or 51).
This writes, for every filled slot:

    age_min, age_max   youngest and oldest the person can have been
    in_window          both bounds inside the slot's nominal window
    in_slack_window    both bounds inside it widened by SLACK years (what the
                       harvest admits since 2026-09-29)

and per person `strict_minimum_set`: the minimum set counting only such
photos. Nothing is removed; filter on these fields.

    python tools/check_ages.py
"""

import glob
import json
import os
import sys

DATA = os.path.join(os.path.dirname(__file__), "..", "dataset")
WINDOW = {"subject_now": (40, 50), "subject_young": (20, 30),
          "father_40s": (40, 50), "mother_40s": (40, 50)}
SLACK = 2


def age_bounds(birth, date):
    """(youngest, oldest) for a birth date and a photo date of any precision."""
    by, bm, bd = (int(x) for x in birth.split("-"))
    parts = [int(x) for x in str(date).split("-")]
    y = parts[0]
    if len(parts) == 3:
        a = y - by - ((parts[1], parts[2]) < (bm, bd))
        return a, a
    if len(parts) == 2:
        return (y - by - ((parts[1], 1) < (bm, bd)),
                y - by - ((parts[1], 31) < (bm, bd)))
    return y - by - 1, y - by


def main():
    total = outside = strict = loose = 0
    for mp in sorted(glob.glob(os.path.join(DATA, "*", "meta.json"))):
        m = json.load(open(mp))
        s = m["slots"]
        for k, e in s.items():
            if e.get("status") != "ok":
                continue
            lo, hi = age_bounds(e["person_birth"], e["date_taken"])
            a, b = WINDOW[k]
            e.update(age_min=lo, age_max=hi, in_window=a <= lo and hi <= b,
                     in_slack_window=a - SLACK <= lo and hi <= b + SLACK)
            total += 1
            outside += not e["in_window"]
        # recomputed here too: a slot cleared in review leaves build's flags stale
        have = {k for k, e in s.items() if e.get("status") == "ok"}
        m["complete_slots"] = len(have)
        m["has_minimum_set"] = ({"subject_now", "subject_young"} <= have
                                and bool(have & {"father_40s", "mother_40s"}))
        good = {k for k, e in s.items() if e.get("status") == "ok" and e.get("in_window")}
        m["strict_minimum_set"] = ({"subject_now", "subject_young"} <= good
                                   and bool(good & {"father_40s", "mother_40s"}))
        strict += m["strict_minimum_set"]
        loose += bool(m.get("has_minimum_set"))
        json.dump(m, open(mp, "w"), ensure_ascii=False, indent=2)
    print(f"photos: {total}, a year outside the window: {outside}")
    print(f"minimum sets: {loose}, of them with every photo strictly in window: {strict}")


if __name__ == "__main__":
    sys.exit(main())
