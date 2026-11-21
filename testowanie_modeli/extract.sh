#!/usr/bin/env bash
# EKSTRAKCJA CECH (realne użycie). Wynik: out/features/<dataset_id>/ w formacie kontraktu
# (docs/DATA_CONTRACT.md: Feature(ad_id, family, field, value, origin_id, method_version)).
#
#   ./extract.sh                       # wszystkie modele na korpusie NASK
#   ./extract.sh face ocr              # wybrane kontenery
#   DATA=./data/sample ./extract.sh    # inny korpus (v0 z ads.jsonl albo luźny katalog plików)
#   MODELS=tesseract,bge-m3 ./extract.sh ocr text
#
# Zmienne: DATA (domyślnie ../data/nask-hacknation-2026), OUT (out/features),
#          THREADS (domyślnie wszystkie rdzenie VM), MODELS (filtr nazw), NEIGHBORS=0 wyłącza raport.
set -euo pipefail
source "$(dirname "$0")/scripts/common.sh"
cd "$ROOT"

DATA=${DATA:-../data/nask-hacknation-2026}
OUT=${OUT:-./out/features}
mkdir -p "$OUT"
data_abs=$(abs_dir "$DATA"); out_abs=$(abs_dir "$OUT")

for uc in $(uc_list "$@"); do
  echo "=== extract tm-$uc  ($DATA -> $OUT)"
  # shellcheck disable=SC2046
  docker run $(docker_flags "$uc") \
    -e CORPUS_HOST_PATH="$data_abs" -e MODELS="${MODELS:-}" -e THREADS="${THREADS:-}" \
    -v "$data_abs:/data:ro" -v "$out_abs:/out" \
    "tm-$uc:latest" python /app/common/main.py extract
done

if [ "${NEIGHBORS:-1}" = 1 ]; then
  for ds in "$out_abs"/*/; do
    [ -d "$ds/features" ] || continue
    docker run --rm --network none -v "$ROOT/common:/app/common:ro" -v "$ROOT/scripts:/scripts:ro" \
      -v "$ds:/ds" tm-base:latest python /scripts/neighbors.py /ds
  done
fi
