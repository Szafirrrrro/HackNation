#!/usr/bin/env bash
# EKSTRAKCJA CECH (realne użycie). Wynik: out/features/<dataset_id>/ w formacie kontraktu
# (docs/DATA_CONTRACT.md: Feature z ad_id, family, field, value, origin_id, method_version).
#
#   ./extract.sh                       # wszystkie modele na korpusie NASK
#   ./extract.sh face ocr              # wybrane kontenery (zawsze w kolejności: ocr/asr przed text)
#   DATA=./data/sample ./extract.sh    # inny korpus (v0 z ads.jsonl albo luźny katalog plików)
#   MODELS=tesseract,bge-m3 ./extract.sh ocr text
#
# Zmienne: DATA (domyślnie ../data/nask-hacknation-2026), OUT (out/features),
#          THREADS (domyślnie wszystkie rdzenie VM), MODELS (filtr nazw; ma pierwszeństwo przed profilem),
#          PROFILE=default|eval|all (domyślnie default: modele ze statusem default), NEIGHBORS=0 wyłącza raport,
#          ONLY_ADS=id1,id2 (tylko te reklamy; pozostałe dostają status unavailable z powodem not_selected),
#          DERIVED_TEXT=0 (modele tekstu liczą tylko pole text, bez ocr.text/asr.text),
#          RESUME=1 (pomija model z udanym wynikiem dla tej samej wersji metody, korpusu i wejść;
#          nie wykrywa zmiany kodu bez zmiany method_version).
# Błąd kontenera lub modelu nie zatrzymuje pozostałych; skrypt kończy się wtedy kodem 1
# i wypisuje listę nieudanych kontenerów (szczegóły w runs/<slug>.json: status, load_error).
set -uo pipefail
source "$(dirname "$0")/scripts/common.sh"
cd "$ROOT"

DATA=${DATA:-../data/nask-hacknation-2026}
OUT=${OUT:-./out/features}
mkdir -p "$OUT"
data_abs=$(abs_dir "$DATA") || exit 1
out_abs=$(abs_dir "$OUT") || exit 1
ucs=$(uc_list "$@") || exit 1
failed=()

for uc in $ucs; do
  echo "=== extract tm-$uc  ($DATA -> $OUT)"
  # shellcheck disable=SC2046
  if ! docker run $(docker_flags "$uc") \
      -e CORPUS_HOST_PATH="$data_abs" -e MODELS="${MODELS:-}" -e THREADS="${THREADS:-}" -e PROFILE="${PROFILE:-}" \
      -e ONLY_ADS="${ONLY_ADS:-}" -e DERIVED_TEXT="${DERIVED_TEXT:-}" -e RESUME="${RESUME:-}" -e EFFORT_WEIGHTS="${EFFORT_WEIGHTS:-}" \
      -v "$data_abs:/data:ro" -v "$out_abs:/out" \
      "tm-$uc:latest" python /app/common/main.py extract; then
    failed+=("$uc")
  fi
done

if [ "${NEIGHBORS:-1}" = 1 ]; then
  ds="$out_abs/$(basename "$data_abs")"
  for d in "$out_abs"/*/; do
    # katalog tego korpusu: corpus.json z tym samym corpus_root
    grep -q "\"corpus_root\": \"$data_abs\"" "$d/corpus.json" 2>/dev/null && ds="${d%/}"
  done
  docker run --rm --network none -v "$ROOT/common:/app/common:ro" -v "$ROOT/scripts:/scripts:ro" \
    -v "$ds:/ds" tm-base:latest python /scripts/neighbors.py /ds || failed+=("neighbors")
fi

if [ ${#failed[@]} -gt 0 ]; then
  echo "NIEUDANE: ${failed[*]} - sprawdź log powyżej i runs/<slug>.json" >&2
  exit 1
fi
