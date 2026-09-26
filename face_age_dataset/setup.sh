#!/usr/bin/env bash
# Prepare the project on a fresh machine: venv, models, skill.
# Safe to re-run; it only fills in what is missing.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PY:-python3}"

echo "== venv"
# never copied between machines: a venv bakes in absolute interpreter paths
if [ ! -x .venv/bin/python ]; then
  "$PY" -m venv .venv
fi
./.venv/bin/pip -q install --upgrade pip
./.venv/bin/pip -q install opencv-python-headless pillow numpy
./.venv/bin/python -c "import cv2,numpy;print('   opencv',cv2.__version__)"

echo "== models"
mkdir -p models
# GitHub serves an LFS pointer (~130 B) from raw.githubusercontent; the real
# weights only come from the media host. Size check catches that mistake.
fetch_model() {
  local path="$1" dest="$2" min="$3"
  if [ -f "$dest" ] && [ "$(wc -c < "$dest")" -gt "$min" ]; then
    echo "   $dest ok"; return
  fi
  curl -sL -o "$dest" "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/$path"
  local sz; sz=$(wc -c < "$dest")
  if [ "$sz" -lt "$min" ]; then
    echo "   ERROR: $dest is $sz bytes (looks like an LFS pointer, not the model)" >&2
    exit 1
  fi
  echo "   $dest fetched ($sz bytes)"
}
fetch_model "models/face_detection_yunet/face_detection_yunet_2023mar.onnx" models/yunet.onnx 100000
fetch_model "models/face_recognition_sface/face_recognition_sface_2021dec.onnx" models/sface.onnx 10000000

echo "== skill"
SKILL_SRC=.transfer-stage/skill
[ -d "$SKILL_SRC" ] || SKILL_SRC=skill   # copy kept in the repo
if [ -d "$SKILL_SRC" ]; then
  DEST="$HOME/.claude/skills/face-age-dataset"
  mkdir -p "$HOME/.claude/skills"
  # copy the contents, not the directory: plain `cp -R src dest` nests a second
  # level inside dest when dest already exists
  rm -rf "$DEST"
  mkdir -p "$DEST"
  cp -R "$SKILL_SRC"/. "$DEST"/
  echo "   installed to $DEST"
else
  echo "   no bundled skill (fine if it is already installed)"
fi

echo "== state"
mkdir -p work
./.venv/bin/python - <<'PY'
import json, os, sys
sys.path.insert(0, "tools")
from harvest_all import sync_state_from_dataset, load_state, save_state
st = sync_state_from_dataset(load_state())
save_state(st)
uniq = {r.get("slug") or k: r for k, r in st.items()}
print(f"   {len(uniq)} people already built; those will be skipped")
PY

echo
echo "ready. next:"
echo "  ./.venv/bin/python tools/harvest_all.py -j 4 --top 60   # continue harvesting"
echo "  ./.venv/bin/python tools/sheet.py 7                     # contact sheets"
