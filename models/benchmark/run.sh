#!/usr/bin/env bash
# UWAGA: modele odrzucone w benchmarku usunięto z kontenerów, więc skrypt liczy dziś tylko modele
# pozostawione. Porównanie z benchmark/README.md odtwarza commit 344d525.
# BENCHMARK WARSTWY MODELI: jakość i koszt na jednej próbie. Opis miar: benchmark/README.md.
#
#   benchmark/run.sh ./data/<próba>            # całość: cechy, warianty, koszt, miary
#   STEPS="metrics" benchmark/run.sh ./data/<próba>   # wybrane kroki: smoke full subset variants cost metrics
#   RESUME=1 benchmark/run.sh ./data/<próba>          # po przerwaniu: pomija modele z aktualnym wynikiem
#
# Wejście: korpus <próba> i <próba>-subset z benchmark/make_corpus.py (uruchamiać z katalogu models/).
# Tanie modele liczymy na całej próbie, wszystkie modele na podzbiorze, a warianty obrazów tylko dla
# podzbioru. Wynik: out/benchmark-quality/<próba>/results.json, pairs.jsonl oraz out/benchmark/<RUN>/.
# Błąd pojedynczego kontenera nie przerywa pozostałych kroków; skrypt kończy się wtedy kodem 1.
set -uo pipefail
source "$(dirname "$0")/../scripts/common.sh"
cd "$ROOT"

DATA=${1:?podaj katalog próby, np. ./data/bench-500}
[ -f "$DATA/benchmark_meta.jsonl" ] && [ -d "$DATA-subset" ] || {
  echo "brak $DATA/benchmark_meta.jsonl lub $DATA-subset; najpierw benchmark/make_corpus.py --subset N" >&2; exit 1; }
name=$(basename "$(abs_dir "$DATA")")
STEPS=${STEPS:-smoke full subset variants cost metrics}
VAR="./data/$name-subset-variants"
QUALITY="./out/benchmark-quality/$name"
mkdir -p "$QUALITY" ./out/features
fail=0
step() { case " $STEPS " in *" $1 "*) echo; echo "##### $1 $(date +%H:%M:%S)"; return 0 ;; esac; return 1; }

variant_ads() {  # ID wariantów (bez oryginałów) po przecinku; $1 = tylko N pierwszych reklam podzbioru
  python3 - "$VAR/corpus/variants.jsonl" "${1:-0}" <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
origs = sorted({r["variant_of"] for r in rows})
keep = set(origs[:int(sys.argv[2])] if int(sys.argv[2]) else origs)
print(",".join(r["ad_id"] for r in rows if r["variant_of"] in keep))
PY
}

if step smoke; then   # 2 reklamy przez wszystkie modele: błąd modelu wychodzi przed długim liczeniem
  two=$(python3 -c 'import json,sys; print(",".join(sorted(json.loads(l)["ad_id"] for l in open(sys.argv[1], encoding="utf-8"))[:2]))' "$DATA-subset/ads.jsonl")
  rm -rf ./out/features-smoke
  OUT=./out/features-smoke PROFILE=all NEIGHBORS=0 DERIVED_TEXT=0 ONLY_ADS="$two" DATA="$DATA-subset" ./extract.sh || {
    echo "próba dymna: ekstrakcja zakończona błędem; przerywam przed długimi krokami" >&2; exit 1; }
  python3 - ./out/features-smoke <<'PY' || { echo "próba dymna nieudana; przerywam przed długimi krokami" >&2; exit 1; }
import glob, json, sys
bad = []
for f in sorted(glob.glob(sys.argv[1] + "/*/runs/*.json")):
    r = json.load(open(f, encoding="utf-8"))
    if r.get("n_inputs") and (r.get("status") != "ok" or r.get("errors") or not r.get("rows_ok")):
        bad.append(f"{r.get('extractor')}: status={r.get('status')} errors={r.get('errors')} rows_ok={r.get('rows_ok')}")
print("próba dymna:", "ok" if not bad else "; ".join(bad))
sys.exit(1 if bad else 0)
PY
fi

# Miary czytają embeddingi i temat tylko z pola text, więc modele tekstu nie liczą tu ocr.text
# (DERIVED_TEXT=0). RESUME=1 w środowisku pomija modele z aktualnym wynikiem po przerwanym przebiegu.
if step full; then    # modele tanie na całej próbie
  PROFILE=all NEIGHBORS=0 DATA="$DATA" ./extract.sh face image_embedding || fail=1
  MODELS=tesseract NEIGHBORS=0 DATA="$DATA" ./extract.sh ocr || fail=1
  MODELS=multilingual-e5-small NEIGHBORS=0 DERIVED_TEXT=0 DATA="$DATA" ./extract.sh text || fail=1
fi

if step subset; then  # wszystkie modele na podzbiorze
  PROFILE=all NEIGHBORS=0 DERIVED_TEXT=0 DATA="$DATA-subset" ./extract.sh || fail=1
fi

if step variants; then  # kadr, róg i rekompresja obrazów podzbioru; cechy obrazu i OCR
  mkdir -p "$VAR"
  docker run --rm --network none -v "$ROOT/scripts:/scripts:ro" -v "$(abs_dir "$DATA-subset"):/src:ro" \
    -v "$(abs_dir "$VAR"):/dst" tm-base:latest python /scripts/make_eval_corpus.py /src /dst/corpus || fail=1
  # oryginały są już policzone w kroku subset, więc tu liczymy same warianty (ONLY_ADS)
  all_ids=$(variant_ads) && ocr_ids=$(variant_ads "${OCR_VARIANT_ADS:-0}") && [ -n "$all_ids" ] && [ -n "$ocr_ids" ] || {
    echo "brak listy wariantów ($VAR/corpus/variants.jsonl); przerywam" >&2; exit 1; }
  PROFILE=all NEIGHBORS=0 DATA="$VAR/corpus" ONLY_ADS="$all_ids" ./extract.sh image_embedding || fail=1
  # OCR_VARIANT_ADS=N ogranicza OCR do wariantów N pierwszych reklam podzbioru (wg ad_id)
  MODELS=tesseract NEIGHBORS=0 DATA="$VAR/corpus" ONLY_ADS="$ocr_ids" ./extract.sh ocr || fail=1
fi

if step cost; then    # p50/p95 i pamięć: pierwsze MAX_ITEMS reklam podzbioru, jeden wariant wątków
  RUN="quality-$name-$(date +%Y%m%d_%H%M%S)" DATA="$DATA-subset" CPUS=${CPUS:-4} MEM=${MEM:-6g} \
    THREADS=${THREADS:-4} REPEATS=${REPEATS:-1} MAX_ITEMS=${MAX_ITEMS:-20} \
    ./bench.sh run face ocr image_embedding object_detection aigi_effort text || fail=1
fi

if step metrics; then
  docker run --rm --network none -v "$ROOT/common:/app/common:ro" -v "$ROOT/benchmark:/bench:ro" \
    -v "$(abs_dir "$DATA"):/corpus:ro" -v "$(abs_dir ./out/features):/features:ro" \
    -v "$(abs_dir "$VAR"):/variants:ro" -v "$(abs_dir "$QUALITY"):/quality" tm-text:latest \
    python /bench/metrics.py --corpus /corpus --full "/features/$name" --subset "/features/$name-subset" \
      --variants "/features/$name-subset-eval-variants" --variants-map /variants/corpus/variants.jsonl \
      --out /quality || fail=1
fi
echo; echo "wynik: $QUALITY/results.json"
exit $fail
