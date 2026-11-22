#!/usr/bin/env bash
# Syntetyczne dane do smoke-testu/benchmarku -> data/sample (luźny katalog plików).
# Wymaga obrazu tm-face (render).
set -euo pipefail
source "$(dirname "$0")/common.sh"
cd "$ROOT"
out=./data/sample
mkdir -p "$out/audio"
docker run --rm --network none -v "$ROOT/scripts:/scripts:ro" -v "$ROOT/$out:/out" \
  tm-face:latest python /scripts/render_samples.py /out
if command -v say >/dev/null && say -v '?' | grep -q Zosia; then
  for f in "$out"/texts/*.txt; do
    say -v Zosia -f "$f" -o "$out/audio/$(basename "$f" .txt).wav" --data-format=LEI16@16000
  done
else
  echo "brak macOS 'say' z głosem PL - pomijam audio"
fi
find "$out" -type f | sort
