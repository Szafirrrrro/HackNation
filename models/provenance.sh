#!/usr/bin/env bash
# POCHODZENIE OBRAZU: każdy obraz z katalogu ocenia Effort (checkpoint .pth).
#
#   ./provenance.sh <katalog z obrazami>
#   EFFORT_WEIGHTS=inny.pth ./provenance.sh <katalog>     # plik z models/weights/effort/
#
# Katalog to luźne pliki obrazów (bez ads.jsonl); identyczne pliki są liczone raz.
# Podkatalogi ai/ i real/ (na dowolnej głębokości) są traktowane jako etykiety: skrypt podaje wtedy
# wykryte obrazy AI i fałszywe alarmy. Bez nich wypisuje same wyniki.
#
# Zmienne: EFFORT_WEIGHTS (domyślnie effort_clip_L14_trainOn_sdv14.pth), EFFORT_THRESHOLD (próg
#          fake_prob, domyślnie 0.5), OUT (domyślnie out/provenance), THREADS.
# Wynik:   <OUT>/<nazwa katalogu>/provenance.csv i provenance.json, obok cech w formacie kontraktu.
# Kontener działa bez sieci, obrazy są montowane tylko do odczytu.
set -uo pipefail
source "$(dirname "$0")/scripts/common.sh"

[ $# -eq 1 ] && [ -d "$1" ] || { echo "użycie: ./provenance.sh <katalog z obrazami>" >&2; exit 2; }
data=$(abs_dir "$1") || exit 1
threshold=${EFFORT_THRESHOLD:-0.5}
python3 -c 'import sys; float(sys.argv[1])' "$threshold" 2>/dev/null || {
  echo "EFFORT_THRESHOLD musi być liczbą: $threshold" >&2; exit 2; }
cd "$ROOT"
weights=${EFFORT_WEIGHTS:-effort_clip_L14_trainOn_sdv14.pth}
[ -f "$ROOT/weights/effort/$weights" ] || {
  echo "brak wag: $ROOT/weights/effort/$weights (wrzuć tam plik .pth)" >&2; exit 1; }
docker image inspect tm-aigi_effort:latest >/dev/null 2>&1 || {
  echo "brak obrazu tm-aigi_effort: ./build.sh aigi_effort" >&2; exit 1; }

OUT=${OUT:-./out/provenance}
mkdir -p "$OUT"
ds="$(abs_dir "$OUT")/$(basename "$data")"
rm -rf "$ds"   # wynik zawsze z bieżącego przebiegu, bez cech po wcześniejszej zawartości katalogu

echo "--- Effort ($weights)"
# ustawienia z otoczenia nie mogą po cichu zawęzić przebiegu
OUT="$OUT" DATA="$data" MODELS=effort-clip-l14 NEIGHBORS=0 EFFORT_WEIGHTS="$weights" \
  ONLY_ADS= RESUME= PROFILE=all \
  ./extract.sh aigi_effort || exit 1

python3 "$ROOT/scripts/provenance_report.py" "$ds" "$threshold" "$weights"
