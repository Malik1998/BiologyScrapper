"""Download Commons candidates and score how well the face is visible.

Score favours: exactly one face, large in frame, frontal (from YuNet's 5
landmarks), and sharp. Group shots are penalised because we cannot tell which
face belongs to the subject without identity matching.
"""

import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request

import cv2
import numpy as np

UA = "faces-dataset/0.2 (https://github.com/Malik1998/BiologyScrapper; research dataset build)"
MODEL = os.path.join(os.path.dirname(__file__), "..", "models", "yunet.onnx")
# below this cosine we refuse to claim the face is the subject
IDENTITY_MIN = 0.30
# eye-to-eye distance in the 1280px working copy; below this the face is a
# speck in an event photo and no amount of upscaling will show features
MIN_INTEROCULAR = 30.0


# Wikimedia only serves these thumbnail widths; any other width is answered
# with 429 ("use thumbnail images in sizes listed on w.wiki/GHai"). Asking for
# 1400/3000/4000 made nearly every download a rate-limit wait.
THUMB_STEPS = (120, 250, 330, 500, 960, 1280, 1920, 3840)


def snap_width(width):
    return next((s for s in THUMB_STEPS if s >= width), THUMB_STEPS[-1])


def thumb_url(file_title, width=1280, orig_w=None):
    """A thumbnail URL at a standard width, or the original when it is not
    wider than that: asking to upscale is refused with a 429 as well."""
    width = snap_width(width)
    name = file_title.split(":", 1)[1].replace(" ", "_")
    url = "https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(name)
    if orig_w and orig_w <= width:
        return url
    return url + f"?width={width}"


def fetch(url, dest):
    """Throttled download shared with the rest of the harvester; raises
    commons.RateLimited rather than pretending the file does not exist."""
    import commons
    return commons.download(url, dest)


import threading

_tls = threading.local()


def detector(size):
    """One detector per thread: setInputSize mutates state, so a shared
    instance would corrupt results when people are built in parallel."""
    d = getattr(_tls, "det", None)
    if d is None:
        d = cv2.FaceDetectorYN.create(MODEL, "", size, 0.6, 0.3, 5000)
        _tls.det = d
    d.setInputSize(size)
    return d


def _patch_mean(img, cx, cy, r):
    h, w = img.shape[:2]
    x0, y0 = max(0, int(cx - r)), max(0, int(cy - r))
    x1, y1 = min(w, int(cx + r)), min(h, int(cy + r))
    if x1 <= x0 or y1 <= y0:
        return None
    p = img[y0:y1, x0:x1]
    return float(cv2.cvtColor(p, cv2.COLOR_BGR2GRAY).mean())


def eye_visibility(img, reye, leye, nose, interocular):
    """1.0 = eyes as bright as the mid-face, ~0 = eyes hidden behind dark lenses.

    A face in sunglasses passes detection, landmarks and sharpness happily, yet
    is useless when the requirement is that the face be clearly visible.
    """
    r = max(3.0, interocular * 0.22)
    e1 = _patch_mean(img, reye[0], reye[1], r)
    e2 = _patch_mean(img, leye[0], leye[1], r)
    ref = _patch_mean(img, nose[0], nose[1], r)
    if e1 is None or e2 is None or ref is None or ref < 1:
        return 1.0
    ratio = ((e1 + e2) / 2.0) / ref
    # lenses typically drop the eye patch below ~55% of mid-face brightness
    return float(min(1.0, max(0.0, (ratio - 0.30) / 0.35)))


def url_for(c, width=1280):
    """Download URL for a candidate row from any source."""
    if c.get("dl_url"):
        return c["big_url"] if width > 1280 and c.get("big_url") else c["dl_url"]
    return thumb_url(c["title"], width, orig_w=c.get("w"))


def analyse(path, ref_emb=None, identity_min=None, min_interocular=None):
    identity_min = IDENTITY_MIN if identity_min is None else identity_min
    img = cv2.imread(path)
    if img is None:
        return None
    h, w = img.shape[:2]
    det = detector((w, h))
    _, faces = det.detect(img)
    if faces is None or len(faces) == 0:
        return {"n_faces": 0, "score": 0.0, "img_w": w, "img_h": h,
                "identity": None, "reason": "no_face"}

    sims = [None] * len(faces)
    if ref_emb is not None:
        from identity import embed_faces, cosine
        embs = embed_faces(img, faces)
        sims = [cosine(e, ref_emb) for e in embs]

    scored = []
    for idx, f in enumerate(faces):
        x, y, fw, fh = f[:4]
        conf = float(f[-1])
        # YuNet landmarks: right eye, left eye, nose, right mouth, left mouth
        pts = f[4:14].reshape(5, 2)
        reye, leye, nose = pts[0], pts[1], pts[2]
        interocular = float(np.linalg.norm(leye - reye)) or 1.0
        dl = float(np.linalg.norm(nose - leye))
        dr = float(np.linalg.norm(nose - reye))
        yaw_asym = abs(dl - dr) / interocular          # 0 = dead frontal
        eye_tilt = abs(math.degrees(math.atan2(leye[1] - reye[1], leye[0] - reye[0])))

        x0, y0 = max(0, int(x)), max(0, int(y))
        x1, y1 = min(w, int(x + fw)), min(h, int(y + fh))
        crop = img[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        eye_vis = eye_visibility(img, reye, leye, nose, interocular)
        scored.append({
            "box": [x0, y0, x1 - x0, y1 - y0],
            "conf": conf,
            "face_w": int(fw),
            "face_ratio": float(fw) / w,
            "yaw_asym": yaw_asym,
            "eye_tilt": eye_tilt,
            "sharpness": sharp,
            "interocular": interocular,
            "eye_visibility": eye_vis,
            "identity": sims[idx],
        })
    if not scored:
        return {"n_faces": 0, "score": 0.0, "img_w": w, "img_h": h,
                "identity": None, "reason": "no_usable_face"}

    n = len(scored)
    if ref_emb is not None:
        # the subject's face, not the biggest one
        scored.sort(key=lambda s: -(s["identity"] or -1))
        main = scored[0]
        if (main["identity"] or -1) < identity_min:
            return {"n_faces": n, "score": 0.0, "img_w": w, "img_h": h,
                    "identity": main["identity"], "reason": "identity_below_threshold"}
        others = [s for s in scored[1:]]
    else:
        # Without a reference we cannot say which face is the subject. In a
        # group shot "biggest face" is a guess -- it once returned a man for
        # Liv Tyler. Only a solitary face is defensible here.
        scored.sort(key=lambda s: -s["face_w"])
        main = scored[0]
        others = scored[1:]
        if n > 1:
            return {"n_faces": n, "score": 0.0, "img_w": w, "img_h": h,
                    "identity": None, "reason": "no_reference_and_multiple_faces"}

    eye_min = (min_interocular if min_interocular is not None
               else MIN_INTEROCULAR * (w / 1400.0))
    if main["interocular"] < eye_min:
        return {"n_faces": n, "score": 0.0, "img_w": w, "img_h": h,
                "identity": main.get("identity"), "interocular": main["interocular"],
                "reason": "face_too_small"}

    if main["eye_visibility"] < 0.35:
        return {"n_faces": n, "score": 0.0, "img_w": w, "img_h": h,
                "identity": main.get("identity"),
                "eye_visibility": round(main["eye_visibility"], 3),
                "reason": "eyes_occluded"}

    size_s = min(main["interocular"] / 60.0, 1.0)        # >=60px between eyes is plenty
    front_s = max(0.0, 1.0 - main["yaw_asym"] / 0.45)    # 0.45 asym ~ strong profile
    sharp_s = min(main["sharpness"] / 250.0, 1.0)
    tilt_s = max(0.0, 1.0 - main["eye_tilt"] / 35.0)
    # confident identity matters as much as geometry: a gorgeous face we cannot
    # confirm is the subject is worthless for this dataset
    if main["identity"] is None:
        id_s, margin = 0.5, None
    else:
        id_s = min(max((main["identity"] - identity_min) / 0.22, 0.0), 1.0)
        margin = None if n == 1 else round(main["identity"] - (others[0]["identity"] or -1), 3)

    score = (0.28 * size_s + 0.23 * front_s + 0.13 * sharp_s
             + 0.05 * tilt_s + 0.23 * id_s
             + 0.08 * main["eye_visibility"]) * min(main["conf"] / 0.9, 1.0)

    return {"n_faces": n, "img_w": w, "img_h": h, "score": round(float(score), 4),
            "id_margin": margin,
            "parts": {"size": round(size_s, 3), "frontal": round(front_s, 3),
                      "sharp": round(sharp_s, 3), "tilt": round(tilt_s, 3),
                      "identity": round(id_s, 3),
                      "eyes": round(main["eye_visibility"], 3)},
            **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in main.items()}}


# A face that is "too small" in the 1280px working copy is often perfectly
# usable in the original: event photos are 4000-6000px wide. Before rejecting,
# look again at up to HIRES_W, judged by an absolute eye distance.
HIRES_W = 3840
HIRES_MIN_EYE = 40.0
HIRES_BUDGET = 15       # per slot; each rescue is a multi-MB download


def run(cands, cache_dir, top=40, ref_emb=None, identity_min=None):
    os.makedirs(cache_dir, exist_ok=True)
    out = []
    budget = HIRES_BUDGET
    for c in cands[:top]:
        # key the cache on the title, not the position, so re-ranking the
        # candidate list does not force a re-download of everything
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in c["title"][5:])[:100]
        dest = os.path.join(cache_dir, safe)
        if not dest.lower().endswith((".jpg", ".jpeg", ".png")):
            dest += ".jpg"
        if not os.path.exists(dest):
            if not fetch(url_for(c), dest):
                continue
        a = analyse(dest, ref_emb=ref_emb, identity_min=identity_min)
        if not a:
            continue
        if (a.get("reason") == "face_too_small" and budget > 0
                and min(c.get("w", 0), c.get("h", 0)) > 1400):
            width = min(c.get("w", HIRES_W), HIRES_W)
            big = os.path.join(cache_dir, "big_" + os.path.basename(dest))
            if os.path.exists(big) or (budget and fetch(url_for(c, width), big)):
                budget -= 1
                a2 = analyse(big, ref_emb=ref_emb, identity_min=identity_min,
                             min_interocular=HIRES_MIN_EYE)
                if a2 and a2.get("score", 0) > 0:
                    a2["from_hires"] = True
                    a, dest = a2, big
        out.append({**c, "local": dest, "face": a})
    out.sort(key=lambda r: -r["face"]["score"])
    return out


if __name__ == "__main__":
    src, cache, top = sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 40
    cands = json.load(open(src))
    res = run(cands, cache, top)
    json.dump(res, open(src.replace(".json", "_scored.json"), "w"),
              ensure_ascii=False, indent=1)
    for r in res[:15]:
        f = r["face"]
        print(f"{f['score']:.3f} faces={f['n_faces']} eye={f.get('interocular',0):.0f}px "
              f"yaw={f.get('yaw_asym',9):.2f} age={r['age']} {r['date']} | {r['title'][5:65]}")
