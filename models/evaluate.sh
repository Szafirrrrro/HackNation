#!/usr/bin/env bash
# EWALUACJA DECYZJI z tabeli laboratorium (README). Wynik: out/eval/decisions.json + decisions.md.
#
#   ./evaluate.sh            # pełny przebieg: korpus wariantów, ekstrakcja, pomiar p95 OCR, metryki
#   SKIP_EXTRACT=1 ./evaluate.sh   # tylko przeliczenie metryk na istniejących cechach
#
# Wejście: DATA (korpus v0, domyślnie ../data/nask-hacknation-2026), etykiety tymczasowe
# eval/labels_nask_provisional.jsonl, opcjonalnie eval/ocr_reference.jsonl (pełne transkrypcje),
# syntetyczne parafrazy z data/sample/texts (scripts/make_samples.sh).
set -uo pipefail
source "$(dirname "$0")/scripts/common.sh"
cd "$ROOT"

[ -f eval/labels_nask_provisional.jsonl ] || {
  echo "brak eval/labels_nask_provisional.jsonl (lokalne etykiety z ID reklam NASK, poza Gitem);" \
       "format: {\"ad_id\": ..., \"group\": ..., \"confidence\": \"provisional\", \"rationale\": ...}" >&2
  exit 1
}
DATA=${DATA:-../data/nask-hacknation-2026}
data_abs=$(abs_dir "$DATA") || exit 1
ds=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['dataset_id'])" "$data_abs/manifest.json")
EVAL=./out/eval
VAR="$EVAL/corpus-$ds-variants"
mkdir -p "$EVAL"
fail=0

if [ "${SKIP_EXTRACT:-0}" != 1 ]; then
  # 1) korpus wariantów obrazów (oryginały + kadr/róg/zmniejszenie)
  docker run --rm --network none -v "$ROOT/scripts:/scripts:ro" -v "$data_abs:/src:ro" \
    -v "$(abs_dir "$EVAL"):/eval" tm-base:latest \
    python /scripts/make_eval_corpus.py /src "/eval/corpus-$ds-variants" || exit 1
  # 2) cechy: oryginalny korpus (modele domyślne i embedding tekstu do porównania z TF-IDF), warianty, parafrazy
  NEIGHBORS=0 DATA="$DATA" ./extract.sh ocr image_embedding || fail=1
  MODELS=multilingual-e5-small NEIGHBORS=1 DATA="$DATA" ./extract.sh text || fail=1
  NEIGHBORS=0 DATA="$VAR" ./extract.sh image_embedding || fail=1
  if [ -d data/sample/texts ]; then
    MODELS=multilingual-e5-small NEIGHBORS=0 DATA=./data/sample/texts ./extract.sh text || fail=1
  fi
  # 3) p95 OCR na tym samym korpusie (1 wątek i wszystkie z limitu CPUS)
  RUN="eval-ocr-$(date +%Y%m%d_%H%M%S)" DATA="$DATA" MODELS=tesseract REPEATS=1 \
    MAX_ITEMS=13 ./bench.sh run ocr || fail=1
fi

bench=$(ls -td out/benchmark/eval-ocr-*/ 2>/dev/null | head -1)
syn=(); [ -d out/features/texts ] && syn=(--synthetic-ds /out/features/texts)
ref=(); [ -f eval/ocr_reference.jsonl ] && ref=(--ocr-ref /lab/eval/ocr_reference.jsonl)
bench_arg=(); [ -n "$bench" ] && bench_arg=(--bench "/lab/${bench%/}")
docker run --rm --network none -v "$ROOT:/lab:ro" -v "$(abs_dir out):/out" -v "$(abs_dir "$EVAL"):/eval" \
  -v "$ROOT/common:/app/common:ro" tm-text:latest python /lab/scripts/evaluate.py \
  --image-ds "/out/features/$ds-eval-variants" --variants "/eval/corpus-$ds-variants/variants.jsonl" \
  --labels /lab/eval/labels_nask_provisional.jsonl --text-ds "/out/features/$ds" \
  "${syn[@]}" "${ref[@]}" "${bench_arg[@]}" --out /eval || fail=1
python3 scripts/decisions_md.py out/eval/decisions.json > out/eval/decisions.md || fail=1
echo "raport: out/eval/decisions.md"
exit $fail
