#!/usr/bin/env bash
# Syntetyczne dane do smoke-testu/benchmarku -> data/sample (luźny katalog plików).
# Wymaga obrazów tm-face (render) i tm-ai_generated (obrazy walidacyjne reverse-SynthID).
set -euo pipefail
source "$(dirname "$0")/common.sh"
cd "$ROOT"
out=./data/sample
mkdir -p "$out/audio" "$out/ai_generated"
docker run --rm --network none -v "$ROOT/scripts:/scripts:ro" -v "$ROOT/$out:/out" \
  tm-face:latest python /scripts/render_samples.py /out
if docker image inspect tm-ai_generated:latest >/dev/null 2>&1; then
  cid=$(docker create tm-ai_generated:latest)
  rm -rf "$out/ai_generated/gemini" "$out/ai_generated/cleaned"
  docker cp "$cid:/opt/rsid/validation_images/cleaned" "$out/ai_generated/cleaned"
  mkdir -p "$out/ai_generated/gemini"
  docker cp "$cid:/opt/rsid/validation_images/." "$out/ai_generated/gemini/"
  rm -rf "$out/ai_generated/gemini/cleaned"
  docker rm "$cid" >/dev/null
else
  echo "brak tm-ai_generated - pomijam obrazy Gemini/SynthID"
fi
if command -v say >/dev/null && say -v '?' | grep -q Zosia; then
  for f in "$out"/texts/*.txt; do
    say -v Zosia -f "$f" -o "$out/audio/$(basename "$f" .txt).wav" --data-format=LEI16@16000
  done
else
  echo "brak macOS 'say' z głosem PL - pomijam audio"
fi
find "$out" -type f | sort
