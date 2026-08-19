"""Optional capture-time face check: is there (roughly) one centered face in
this photo? Off by default (ENABLE_FACE_CHECK=false, see .env.example) -
uploaders just get whatever they captured, no server-side validation.

When turned on, uses OpenCV's bundled Haar cascade - no model download, no
GPU, cheap enough for occasional use, but importing cv2 at all (~50-100ms
and a chunk of memory per worker) is exactly the kind of load a small
server may not want, so the import is lazy: this module - and the
opencv-python-headless dependency itself - is untouched unless the check is
actually enabled.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from web import config

logger = logging.getLogger(__name__)

_cascade = None


@dataclass
class FaceCheckResult:
    enabled: bool
    passed: bool
    detail: str
    face_count: int = 0


def _get_cascade():
    global _cascade
    if _cascade is None:
        import cv2

        _cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
    return _cascade


def check(image_bytes: bytes) -> FaceCheckResult:
    if not config.ENABLE_FACE_CHECK:
        return FaceCheckResult(enabled=False, passed=True, detail="face check disabled")

    try:
        import cv2
        import numpy as np
    except ImportError:
        logger.warning(
            "ENABLE_FACE_CHECK=true but opencv-python-headless isn't installed - "
            "skipping the check for this upload. Run: .venv/bin/pip install opencv-python-headless"
        )
        return FaceCheckResult(enabled=False, passed=True, detail="opencv not installed")

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return FaceCheckResult(enabled=True, passed=False, detail="could not decode image")

    cascade = _get_cascade()
    faces = cascade.detectMultiScale(
        img, scaleFactor=1.1, minNeighbors=5, minSize=(max(img.shape) // 8,) * 2
    )

    if len(faces) == 0:
        return FaceCheckResult(enabled=True, passed=False, detail="no face detected", face_count=0)
    if len(faces) > 1:
        return FaceCheckResult(
            enabled=True, passed=False, detail="more than one face detected", face_count=len(faces)
        )
    return FaceCheckResult(enabled=True, passed=True, detail="one face detected", face_count=1)
