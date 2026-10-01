"""Tag every photo with how usable it is for rating, without removing anything.

Dermatology raters need comparable faces: near-frontal, level, eyes open,
neutral expression, sharp; colour vs black-and-white matters too. This
measures on the saved face crop:

    yaw        left/right turn: nose offset between the eyes (0 = frontal)
    pitch      up/down tilt: nose height between eye line and mouth line,
               relative to a frontal face
    roll       in-plane tilt of the eye line, degrees
    happy      P(happy) from OpenCV Zoo's expression model (> HAPPY = smiling);
               mouth width / eye distance is kept as `smile` but did not
               separate smiles from neutral faces, so it is no longer judged
    sharpness  Laplacian variance of the face
    colour     mean saturation of the face centre (> COLOUR_SAT = colour photo)

and writes e["qc"] = {measurements, "ok_for_rating": bool, "issues": [...]}.
Photos that fail stay in the dataset, marked, so a better one can be looked
for later. Per person: `rating_set` (minimum set of ok_for_rating photos)
and `rating_set_colour` (same, all in colour).

    python tools/quality_tags.py
"""

import glob
import json
import math
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import face as F  # noqa: E402

DATA = os.path.join(os.path.dirname(__file__), "..", "dataset")
LIMITS = {"yaw": 0.25, "pitch": 0.08, "roll": 12.0, "sharpness": 20.0}
HAPPY = 0.5
COLOUR_SAT = 0.20
PITCH_FRONTAL = None      # set from the data: median of the ratio


def measure(path):
    img = cv2.imread(path)
    if img is None:
        return None
    h, w = img.shape[:2]
    _, faces = F.detector((w, h)).detect(img)
    if faces is None or len(faces) == 0:
        return {"face_found": False}
    f = max(faces, key=lambda f: f[2] * float(f[-1]))
    p = f[4:14].reshape(5, 2)
    reye, leye, nose, rm, lm = p
    io = float(np.linalg.norm(leye - reye)) or 1.0
    eye_mid, mouth_mid = (reye + leye) / 2, (rm + lm) / 2
    yaw = abs(float(np.linalg.norm(nose - leye) - np.linalg.norm(nose - reye))) / io
    span = float(mouth_mid[1] - eye_mid[1]) or 1.0
    pitch_ratio = float(nose[1] - eye_mid[1]) / span
    roll = abs(math.degrees(math.atan2(leye[1] - reye[1], leye[0] - reye[0])))
    smile = float(np.linalg.norm(lm - rm)) / io
    x, y, fw, fh = [int(v) for v in f[:4]]
    crop = img[max(0, y):y + fh, max(0, x):x + fw]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.size else None
    sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var()) if gray is not None else 0.0
    c = img[h // 4:3 * h // 4, w // 4:3 * w // 4]
    sat = float(cv2.cvtColor(c, cv2.COLOR_BGR2HSV)[..., 1].mean()) / 255
    from expression import expression
    ex = expression(img, f) or {}
    return {"face_found": True, "yaw": round(yaw, 3), "pitch_ratio": round(pitch_ratio, 3),
            "happy": ex.get("happy"), "expression": max(ex, key=ex.get) if ex else None,
            "roll": round(roll, 1), "smile": round(smile, 3), "sharpness": round(sharp, 1),
            "saturation": round(sat, 3), "interocular": round(io, 1)}


def judge(q, pitch0):
    issues = []
    if not q or not q.get("face_found"):
        return False, ["no face detected in crop"]
    if q["yaw"] > LIMITS["yaw"]:
        issues.append("head turned")
    if abs(q["pitch_ratio"] - pitch0) > LIMITS["pitch"]:
        issues.append("looking up/down")
    if q["roll"] > LIMITS["roll"]:
        issues.append("head tilted")
    if q.get("happy") is None or q["happy"] > HAPPY:
        issues.append("smiling")
    if q["sharpness"] < LIMITS["sharpness"]:
        issues.append("blurry")
    return not issues, issues


def main():
    metas = sorted(glob.glob(os.path.join(DATA, "*", "meta.json")))
    measured = {}
    for mp in metas:
        m = json.load(open(mp))
        for k, e in m["slots"].items():
            if e.get("status") == "ok":
                measured[(mp, k)] = measure(os.path.join(DATA, e["face_crop"]))
    # Judge against the fixed reference the harvest and manual picks use, not
    # this run's median: the median drifts as photos are added, and a face on
    # the edge then flips between runs (Toby Stephens, Dale Earnhardt).
    from build import PITCH_FRONTAL as pitch0
    ratios = sorted(q["pitch_ratio"] for q in measured.values() if q and q.get("face_found"))
    print(f"median pitch ratio this run: {ratios[len(ratios) // 2]:.3f} (judged against {pitch0})")
    from collections import Counter
    issues_n, n_ok, n = Counter(), 0, 0
    sets = sets_col = full = full_col = 0
    for mp in metas:
        m = json.load(open(mp))
        s = m["slots"]
        for k, e in s.items():
            if e.get("status") != "ok":
                continue
            q = measured.get((mp, k)) or {}
            ok, iss = judge(q, pitch0)
            q.update(ok_for_rating=ok, issues=iss,
                     colour=bool(q.get("saturation", 0) > COLOUR_SAT))
            e["qc"] = q
            n += 1
            n_ok += ok
            issues_n.update(iss)

        def good(k, colour=False):
            e = s.get(k, {})
            return (e.get("status") == "ok" and e["qc"]["ok_for_rating"]
                    and (not colour or e["qc"]["colour"]))
        for colour in (False, True):
            v = good("subject_now", colour) and good("subject_young", colour) and (
                good("father_40s", colour) or good("mother_40s", colour))
            m["rating_set_colour" if colour else "rating_set"] = v
        a = all(good(k) for k in s)
        sets += m["rating_set"]
        sets_col += m["rating_set_colour"]
        full += a
        full_col += all(good(k, True) for k in s)
        json.dump(m, open(mp, "w"), ensure_ascii=False, indent=2)
    print(f"photos {n}, ok for rating {n_ok} ({n_ok / max(n, 1):.0%}); frontal pitch ratio {pitch0:.3f}")
    for k, v in issues_n.most_common():
        print(f"  {k}: {v}")
    print(f"rating-ready minimum sets: {sets} (all colour: {sets_col}); all four: {full} (colour: {full_col})")


if __name__ == "__main__":
    sys.exit(main())
