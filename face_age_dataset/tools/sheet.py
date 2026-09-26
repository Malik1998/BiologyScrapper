"""Contact sheets: one row per person, one column per slot.

Reviewing 4 separate images per person does not scale. A sheet puts a whole
batch in front of the eye at once, with the age and identity score written on
each tile so a wrong pick is obvious without opening any JSON.
"""

import json
import os
import sys

import cv2
import numpy as np

ROOT = os.path.join(os.path.dirname(__file__), "..")
DATA = os.path.join(ROOT, "dataset")
SLOTS = [("subject_now", "NOW 40-50"), ("subject_young", "YOUNG 20-30"),
         ("father_40s", "FATHER 40-50"), ("mother_40s", "MOTHER 40-50")]

CELL = 230
LABEL = 46
FONT = cv2.FONT_HERSHEY_SIMPLEX


def tile(meta, slot):
    cell = np.full((CELL + LABEL, CELL, 3), 32, np.uint8)
    s = meta["slots"].get(slot, {})
    if s.get("status") != "ok":
        reason = (s.get("reason") or "missing")[:26]
        cv2.putText(cell, "--", (CELL // 2 - 18, CELL // 2), FONT, 0.9, (90, 90, 90), 2)
        cv2.putText(cell, reason, (4, CELL + 18), FONT, 0.34, (110, 110, 200), 1)
        found = s.get("candidates_found")
        if found is not None:
            cv2.putText(cell, f"cands={found}", (4, CELL + 34), FONT, 0.34, (110, 110, 140), 1)
        return cell

    p = os.path.join(DATA, s.get("face_crop") or s.get("file"))
    img = cv2.imread(p)
    if img is None:
        cv2.putText(cell, "read fail", (10, CELL // 2), FONT, 0.6, (0, 0, 200), 2)
        return cell
    h, w = img.shape[:2]
    sc = CELL / max(h, w)
    img = cv2.resize(img, (max(1, int(w * sc)), max(1, int(h * sc))))
    y0 = (CELL - img.shape[0]) // 2
    x0 = (CELL - img.shape[1]) // 2
    cell[y0:y0 + img.shape[0], x0:x0 + img.shape[1]] = img

    age = s.get("age_at_photo")
    unc = s.get("age_uncertainty_years", 0)
    idc = s.get("identity_cosine")
    eye = s.get("interocular_px") or 0
    prec = (s.get("date_precision") or "?")[:3]
    warn = s.get("date_conflict")

    a_txt = f"age {age}" + (f"+-{unc}" if unc else "")
    cv2.putText(cell, a_txt, (4, CELL + 16), FONT, 0.46, (120, 255, 120), 1)
    cv2.putText(cell, f"{s.get('date_taken','?')}({prec})", (4, CELL + 31), FONT, 0.36,
                (60, 200, 255) if warn else (180, 180, 180), 1)
    id_col = (120, 255, 120) if (idc or 0) >= 0.45 else (80, 190, 255)
    cv2.putText(cell, f"id {idc:.2f}" if idc is not None else "id --",
                (4, CELL + 44), FONT, 0.38, id_col, 1)
    cv2.putText(cell, f"eye{int(eye)}", (CELL - 62, CELL + 44), FONT, 0.38, (170, 170, 170), 1)
    return cell


def sheet(metas, out_path, title="faces dataset"):
    head = 34
    name_col = 190
    rows = []
    for m in metas:
        cells = [tile(m, s) for s, _ in SLOTS]
        strip = np.hstack(cells)
        lab = np.full((strip.shape[0], name_col, 3), 24, np.uint8)
        nm = m["subject"]["name"][:22]
        cv2.putText(lab, nm, (6, 26), FONT, 0.5, (255, 255, 255), 1)
        cv2.putText(lab, f"b.{m['subject']['birth'][:4]}", (6, 48), FONT, 0.42, (170, 170, 170), 1)
        f = (m.get("father") or {}).get("name", "-")
        mo = (m.get("mother") or {}).get("name", "-")
        cv2.putText(lab, f"F {f[:20]}", (6, 72), FONT, 0.36, (150, 190, 255), 1)
        cv2.putText(lab, f"M {mo[:20]}", (6, 90), FONT, 0.36, (255, 190, 150), 1)
        ok = m.get("complete_slots", 0)
        cv2.putText(lab, f"{ok}/4  {'MIN-SET' if m.get('has_minimum_set') else ''}",
                    (6, 116), FONT, 0.4,
                    (120, 255, 120) if m.get("has_minimum_set") else (120, 120, 120), 1)
        rows.append(np.hstack([lab, strip]))

    body = np.vstack(rows) if rows else np.zeros((10, 10, 3), np.uint8)
    # title on its own line so it cannot collide with the first column label
    header = np.full((head * 2, body.shape[1], 3), 16, np.uint8)
    cv2.putText(header, title, (8, 23), FONT, 0.55, (255, 255, 255), 1)
    x = name_col
    for _, lbl in SLOTS:
        cv2.putText(header, lbl, (x + 6, head + 23), FONT, 0.45, (200, 220, 255), 1)
        x += CELL
    out = np.vstack([header, body])
    cv2.imwrite(out_path, out)
    return out_path, out.shape


def load_all():
    metas = []
    for slug in sorted(os.listdir(DATA)):
        mp = os.path.join(DATA, slug, "meta.json")
        if os.path.isfile(mp):
            metas.append(json.load(open(mp)))
    return metas


if __name__ == "__main__":
    per = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    metas = load_all()
    os.makedirs(os.path.join(DATA, "_sheets"), exist_ok=True)
    made = []
    for i in range(0, len(metas), per):
        chunk = metas[i:i + per]
        p = os.path.join(DATA, "_sheets", f"sheet_{i // per + 1:02d}.jpg")
        path, shape = sheet(chunk, p, f"faces dataset  batch {i // per + 1}  "
                                       f"({len(chunk)} people)")
        made.append((path, shape))
        print(path, shape)
    print(f"{len(metas)} people -> {len(made)} sheet(s)")
