#!/usr/bin/env bash
# Pack the project for another machine.
#   ./pack.sh          -> results + code + models, no photo cache (~85 MB)
#   ./pack.sh --cache  -> everything including the download cache (~700 MB)
#
# .venv is never packed: it hardcodes absolute paths to this machine's Python.
# setup.sh recreates it on the other side.
set -euo pipefail
cd "$(dirname "$0")"

OUT="${OUT:-$HOME/faces-dataset-transfer.tgz}"
WITH_CACHE=0
[ "${1:-}" = "--cache" ] && WITH_CACHE=1

ARGS=(
  --exclude='.venv'
  --exclude='__pycache__'
  --exclude='*.pyc'
  --exclude='work/*.err'
)
[ "$WITH_CACHE" -eq 0 ] && ARGS+=(--exclude='work/cache' --exclude='work/ref')

# The skill lives outside the project tree and is easy to leave behind.
SKILL="$HOME/.claude/skills/face-age-dataset"
STAGE=".transfer-stage"
rm -rf "$STAGE"; mkdir -p "$STAGE"
[ -d "$SKILL" ] && cp -R "$SKILL" "$STAGE/skill"

tar czf "$OUT" "${ARGS[@]}" \
  README.md pack.sh setup.sh tools models dataset \
  work/harvest_state.json \
  -C . "$STAGE"

rm -rf "$STAGE"
echo "packed -> $OUT"
du -sh "$OUT"
[ "$WITH_CACHE" -eq 0 ] && echo "note: photo cache excluded; rebuilds re-download. Use --cache to include it."
