#!/usr/bin/env bash
# POCHODZENIE OBRAZU: reverse-SynthID, a obrazy przez niego nieoznaczone trafiają do Effort (.pth).
#
#   ./provenance.sh <katalog z obrazami>
#   EFFORT_WEIGHTS=inny.pth ./provenance.sh <katalog>     # plik z models/weights/effort/
#
# Podkatalogi ai/ i real/ (na dowolnej głębokości) są traktowane jako etykiety: skrypt podaje wtedy
# wykryte obrazy AI i fałszywe alarmy dla każdego modelu i dla całości. Bez nich wypisuje same wyniki.
#
# Zmienne: EFFORT_WEIGHTS (domyślnie effort_clip_L14_trainOn_sdv14.pth), EFFORT_THRESHOLD (próg
#          fake_prob, domyślnie 0.5), OUT (domyślnie out/provenance), THREADS.
# Wynik:   <OUT>/<nazwa katalogu>/provenance.csv i provenance.json, obok cech w formacie kontraktu.
# Kontenery działają bez sieci, obrazy są montowane tylko do odczytu.
set -uo pipefail
source "$(dirname "$0")/scripts/common.sh"

[ $# -eq 1 ] && [ -d "$1" ] || { echo "użycie: ./provenance.sh <katalog z obrazami>" >&2; exit 2; }
data=$(abs_dir "$1") || exit 1
cd "$ROOT"
weights=${EFFORT_WEIGHTS:-effort_clip_L14_trainOn_sdv14.pth}
[ -f "$ROOT/weights/effort/$weights" ] || {
  echo "brak wag: $ROOT/weights/effort/$weights (wrzuć tam plik .pth)" >&2; exit 1; }
for uc in ai_generated aigi_effort; do
  docker image inspect "tm-$uc:latest" >/dev/null 2>&1 || { echo "brak obrazu tm-$uc: ./build.sh $uc" >&2; exit 1; }
done

OUT=${OUT:-./out/provenance}
mkdir -p "$OUT"
ds="$(abs_dir "$OUT")/$(basename "$data")"
rm -rf "$ds"   # wynik zawsze z bieżącego przebiegu, bez cech po wcześniejszej zawartości katalogu
py="$ROOT/scripts/provenance_report.py"

echo "--- krok 1: reverse-SynthID"
OUT="$OUT" DATA="$data" MODELS=reverse-synthid-v4 NEIGHBORS=0 ./extract.sh ai_generated || exit 1

rest=$(python3 "$py" unflagged "$ds") || exit 1
if [ -n "$rest" ]; then
  echo "--- krok 2: Effort ($weights) na obrazach nieoznaczonych przez SynthID"
  OUT="$OUT" DATA="$data" MODELS=effort-clip-l14 NEIGHBORS=0 ONLY_ADS="$rest" EFFORT_WEIGHTS="$weights" \
    ./extract.sh aigi_effort || exit 1
else
  echo "--- krok 2 pominięty: SynthID oznaczył wszystkie obrazy"
fi

python3 "$py" report "$ds" "${EFFORT_THRESHOLD:-0.5}"
