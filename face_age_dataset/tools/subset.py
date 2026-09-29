"""A small, showable sample: people whose four photos are all freely licensed.

Picks the best-attested complete sets (sharp frontal faces, exact dates) with
a spread of birth decades, and writes them to one folder a biologist can open
without the rest of the dataset:

    python tools/subset.py -n 20 [--drop slug,slug] [--out work/biologists_subset]

Output: <out>/<slug>/<slot>.jpg (face crop, 400 px) and <slot>_full.jpg,
subset.csv with age, date and licence per photo, and index.html -- a contact
sheet, one row per person, credits under every photo as the licences require.
"""

import argparse
import csv
import glob
import html
import json
import os
from collections import defaultdict

import cv2

from check_ages import age_bounds

ROOT = os.path.join(os.path.dirname(__file__), "..")
DATA = os.path.join(ROOT, "dataset")
SLOTS = ("subject_young", "subject_now", "father_40s", "mother_40s")
LABEL = {"subject_young": "subject, 20-30", "subject_now": "subject, 40-50",
         "father_40s": "father, 40-50", "mother_40s": "mother, 40-50"}
PREC = {"day": 1.0, "month": 0.9, "year": 0.75}


def complete_sets(rating=False, slack=False):
    win = "in_slack_window" if slack else "in_window"
    for mp in sorted(glob.glob(os.path.join(DATA, "*", "meta.json"))):
        m = json.load(open(mp))
        s = m["slots"]
        if all(s.get(k, {}).get("status") == "ok" and s[k].get("publishable")
               and s[k].get(win)                             # run check_ages.py first
               and (not rating or (s[k].get("qc") or {}).get("ok_for_rating"))
               for k in SLOTS):
            yield m


def score(m):
    # the weakest photo decides how convincing the set is
    return min((e.get("quality_score") or 0) * PREC.get(e.get("date_precision"), 0.5)
               for e in (m["slots"][k] for k in SLOTS))


def pick(sets, n, drop):
    sets = sorted((m for m in sets if m["slug"] not in drop), key=score, reverse=True)
    # one child per couple: siblings share both parent photos, so a second
    # sibling adds no new parent faces to the sample
    seen, uniq = set(), []
    for m in sets:
        couple = ((m.get("father") or {}).get("qid"), (m.get("mother") or {}).get("qid"))
        if couple not in seen:
            seen.add(couple)
            uniq.append(m)
    by_decade = defaultdict(list)
    for m in uniq:
        by_decade[(m["subject"].get("birth") or "0")[:3]].append(m)
    out = []
    # round-robin over birth decades so the sample is not all one generation
    while len(out) < n and any(by_decade.values()):
        for d in sorted(by_decade):
            if by_decade[d] and len(out) < n:
                out.append(by_decade[d].pop(0))
    return sorted(out, key=lambda m: m["subject"].get("birth") or "")


def save(src, dst, side):
    img = cv2.imread(src)
    if img is None:
        return False
    h, w = img.shape[:2]
    f = side / max(h, w)
    if f < 1:
        img = cv2.resize(img, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(dst, img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return True


def age_range(e):
    # age_at_photo is the rounded middle of the range; recompute the bounds
    return age_bounds(e["person_birth"], e["date_taken"])


def credit(e):
    return f"{e.get('author') or 'unknown author'}, {e.get('license')}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=20)
    ap.add_argument("--drop", default="", help="comma-separated slugs to leave out")
    ap.add_argument("--rating", action="store_true",
                    help="only faces that pass quality_tags (frontal, level, neutral, sharp)")
    ap.add_argument("--slack", action="store_true",
                    help="ages may sit up to 2 years outside the window")
    ap.add_argument("--out", default=os.path.join(ROOT, "work", "biologists_subset"))
    a = ap.parse_args()
    people = pick(list(complete_sets(a.rating, a.slack)), a.n, set(filter(None, a.drop.split(","))))
    os.makedirs(a.out, exist_ok=True)

    rows, cards = [], []
    for m in people:
        slug = m["slug"]
        os.makedirs(os.path.join(a.out, slug), exist_ok=True)
        cells = []
        for k in SLOTS:
            e = m["slots"][k]
            face, full = f"{slug}/{k}.jpg", f"{slug}/{k}_full.jpg"
            save(os.path.join(DATA, e["face_crop"]), os.path.join(a.out, face), 400)
            save(os.path.join(DATA, e["file"]), os.path.join(a.out, full), 1200)
            lo, hi = age_range(e)
            age = f"{lo}" if lo == hi else f"{lo}-{hi}"
            rows.append({"person": m["subject"]["name"], "slot": k, "who": e["person"],
                         "born": e["person_birth"], "photo_date": e["date_taken"],
                         "date_precision": e["date_precision"], "age_min": lo, "age_max": hi,
                         "license": e.get("license"), "author": e.get("author"),
                         "source": e.get("source_page"), "file": face})
            cells.append(
                f'<figure><a href="{full}"><img src="{face}" alt="{html.escape(e["person"])}, age {age}" loading="lazy"></a>'
                f'<figcaption><span class="role">{html.escape(LABEL[k])}</span>'
                f'<span class="who">{html.escape(e["person"])}</span>'
                f'<span class="data">age {age} &middot; {html.escape(str(e["date_taken"]))}</span>'
                f'<a class="credit" href="{html.escape(e.get("source_page") or "")}">'
                f'{html.escape(credit(e))}</a></figcaption></figure>')
        cards.append(f'<section><h2>{html.escape(m["subject"]["name"])} '
                     f'<span>born {m["subject"].get("birth", "")[:4]}</span></h2>'
                     f'<div class="row">{"".join(cells)}</div></section>')

    with open(os.path.join(a.out, "subset.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(a.out, "index.html"), "w") as f:
        f.write(PAGE.replace("{N}", str(len(people))).replace("{P}", str(len(rows)))
                .replace("{WIN}", "every age within 2 years of its window" if a.slack
                         else "every age strictly inside its window")
                .replace("{QC}", "<li>frontal, level, neutral, sharp faces</li>" if a.rating else "")
                .replace("{CARDS}", "\n".join(cards)))
    print(f"{len(people)} people, {len(rows)} photos -> {a.out}")
    for m in people:
        print(f"  {m['slug']}  {score(m):.2f}")


PAGE = """<meta charset="utf-8"><title>Face Age Sample</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
:root{--bg:#f4f6f4;--card:#ffffff;--fg:#1b211e;--mut:#5f6b65;--line:#d9dfdb;--accent:#2d6a57;
  --sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;--mono:"IBM Plex Mono",ui-monospace,Menlo,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#121614;--card:#1a1f1c;--fg:#e4eae6;--mut:#94a19a;--line:#2a312d;--accent:#83c3ac;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#121614;--card:#1a1f1c;--fg:#e4eae6;--mut:#94a19a;--line:#2a312d;--accent:#83c3ac;color-scheme:dark}
body{background:var(--bg);color:var(--fg);font:15px/1.5 var(--sans)}
main{max-width:1100px;margin:0 auto;padding-inline:16px;padding-block:32px 64px}
header{display:grid;gap:10px;margin-bottom:28px}
.eyebrow{font:500 12px/1 var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--accent)}
h1{font-size:26px;line-height:1.2;font-weight:600;margin:0;text-wrap:balance}
.lead{margin:0;max-width:68ch;color:var(--mut)}
.key{display:flex;flex-wrap:wrap;gap:8px 20px;font:13px/1.4 var(--mono);color:var(--mut);margin:4px 0 0;padding:0;list-style:none}
.key b{color:var(--fg);font-weight:500}
.people{display:grid;gap:14px}
section{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px}
h2{font-size:17px;font-weight:600;margin:0 0 12px;text-wrap:balance}
h2 span{font:400 13px var(--mono);color:var(--mut);margin-left:6px}
.row{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}
@media (max-width:680px){.row{grid-template-columns:repeat(2,minmax(0,1fr))}}
figure{margin:0;display:grid;gap:8px;align-content:start}
figure>a{display:block;border-radius:4px;outline-offset:3px}
figure>a:focus-visible{outline:2px solid var(--accent)}
img{width:100%;max-width:100%;aspect-ratio:1;object-fit:cover;display:block;border-radius:4px;background:var(--line)}
figcaption{display:grid;gap:2px;font-size:13px;line-height:1.35}
.role{font:500 11px/1.3 var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--accent)}
.who{font-weight:500}
.data{font-family:var(--mono);font-variant-numeric:tabular-nums;color:var(--fg)}
.credit{font-size:11px;color:var(--mut);overflow-wrap:anywhere;text-decoration:none;margin-top:2px}
.credit:hover,.credit:focus-visible{text-decoration:underline}
@media print{@page{size:A4;margin:12mm}body{background:#fff;font-size:12px}main{padding-block:0}section{break-inside:avoid;border-color:#ccc}.row{grid-template-columns:repeat(4,minmax(0,1fr))!important}}
</style>
<main>
<header>
<span class="eyebrow">Sample for review &middot; {N} families</span>
<h1>Each person at 20&ndash;30 and at 40&ndash;50, next to their parents at 40&ndash;50</h1>
<p class="lead">Ages come from the birth date on Wikidata and the date the photo was taken. When only the year is known, the age is shown as a two-year range. Every photo is from Wikimedia Commons under a free licence; the line under each photo credits the author and links to the source page. Select a face to open the full photo.</p>
<ul class="key"><li><b>{N}</b> people</li><li><b>{P}</b> photos</li><li>one child per couple</li><li>{WIN}</li>{QC}<li>faces checked by eye</li></ul>
</header>
<div class="people">
{CARDS}
</div>
</main>
"""

if __name__ == "__main__":
    main()
