"""Facial expression on a face crop: P(happy) from OpenCV Zoo's FER model.

Mouth width and visible teeth did not separate a smile from a neutral face
on hand-labelled crops (Ben Mulroney beaming scored like Felipe VI), so the
smile check needs a model that has actually seen expressions.
Model: opencv_zoo facial_expression_recognition_mobilefacenet_2022july.onnx
"""

import os
import threading

import cv2
import numpy as np

import face as F

MODEL = os.path.join(os.path.dirname(__file__), "..", "models", "fer.onnx")
LABELS = ["angry", "disgust", "fearful", "happy", "neutral", "sad", "surprised"]
STD = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                [41.5493, 92.3655], [70.7299, 92.2041]], np.float32)
_tls = threading.local()


def _net():
    n = getattr(_tls, "net", None)
    if n is None:
        n = _tls.net = cv2.dnn.readNet(MODEL)
    return n


def expression(img, face):
    """{label: prob} for one YuNet detection row on `img`."""
    pts = np.asarray(face[4:14], np.float32).reshape(5, 2)
    M, _ = cv2.estimateAffinePartial2D(pts, STD)
    if M is None:
        return None
    a = cv2.warpAffine(img, M, (112, 112))
    a = cv2.cvtColor(a, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    a = (a - 0.5) / 0.5
    net = _net()
    net.setInput(cv2.dnn.blobFromImage(a), "data")
    out = net.forward("label")[0].astype(np.float64)
    p = np.exp(out - out.max())
    p /= p.sum()
    return {k: round(float(v), 3) for k, v in zip(LABELS, p)}


def of_crop(path):
    img = cv2.imread(path)
    if img is None:
        return None
    h, w = img.shape[:2]
    _, faces = F.detector((w, h)).detect(img)
    if faces is None or len(faces) == 0:
        return None
    return expression(img, max(faces, key=lambda f: f[2] * float(f[-1])))
