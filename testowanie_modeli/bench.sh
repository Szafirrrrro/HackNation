#!/usr/bin/env bash
# BENCHMARK (tylko pomiar CPU/RAM/latencji, żadnych cech do dalszego użycia).
# Wynik: out/benchmark/<RUN>/summary.md + <use_case>.json + logi.
#
#   ./bench.sh                       # wszystkie kontenery na data/sample
#   ./bench.sh face ocr              # wybrane
#   DATA=../data/nask-hacknation-2026 CPUS=2 THREADS=1,2 RUN=nask ./bench.sh
#   ./bench.sh report [out/benchmark/<RUN>]
#
# Zmienne: DATA (domyślnie ./data/sample), CPUS=4 (limit docker --cpus, puste = brak),
#          MEM=6g, THREADS=1,all, REPEATS=3, WARMUP=1, MAX_ITEMS=20, MODELS, RUN.
set -euo pipefail
source "$(dirname "$0")/scripts/common.sh"
cd "$ROOT"

if [ "${1:-}" = report ]; then
  python3 scripts/report.py "${2:-$(ls -d out/benchmark/*/ | tail -1)}"; exit
fi

DATA=${DATA:-./data/sample}
CPUS=${CPUS:-4}
MEM=${MEM:-6g}
RUN=${RUN:-$(date +%Y%m%d_%H%M%S)}
res="./out/benchmark/$RUN"; mkdir -p "$res"
data_abs=$(abs_dir "$DATA"); res_abs=$(abs_dir "$res")
cpu_flag=(); [ -n "$CPUS" ] && cpu_flag=(--cpus "$CPUS")

<<<<<<< HEAD
uc_list() { if [ $# -gt 0 ]; then echo "$@"; else echo "${ALL_UC[@]}"; fi; }

build() {
  docker build -t tm-base:latest -f base/Dockerfile .
  for uc in $(uc_list "$@"); do
    echo "=== build tm-$uc"
    docker build -t "tm-$uc:latest" -f "containers/$uc/Dockerfile" .
  done
}

samples() {
  local out=./data/sample
  mkdir -p "$out/audio" "$out/ai_generated"
  docker run --rm --network none -v "$PWD/scripts:/scripts:ro" -v "$PWD/$out:/out" \
    tm-face:latest python /scripts/render_samples.py /out
  # obrazy Gemini (z SynthID) + wersje "cleaned" z repo reverse-SynthID (etykiety: katalogi)
  local cid; cid=$(docker create tm-ai_generated:latest)
  rm -rf "$out/ai_generated/gemini" "$out/ai_generated/cleaned"
  docker cp "$cid:/opt/rsid/validation_images/cleaned" "$out/ai_generated/cleaned"
  mkdir -p "$out/ai_generated/gemini"
  docker cp "$cid:/opt/rsid/validation_images/." "$out/ai_generated/gemini/"
  rm -rf "$out/ai_generated/gemini/cleaned"
  docker rm "$cid" >/dev/null
  # niewygenerowane AI: kreacje z images/ jako negatywy
  mkdir -p "$out/ai_generated/non_ai" && cp "$out"/images/*.png "$out/ai_generated/non_ai/"
  # audio: macOS 'say' (głos Zosia, PL); na innych systemach pomijane
  if command -v say >/dev/null && say -v '?' | grep -q Zosia; then
    for f in "$out"/texts/*.txt; do
      n=$(basename "$f" .txt)
      say -v Zosia -f "$f" -o "$out/audio/$n.wav" --data-format=LEI16@16000
    done
  else
    echo "brak 'say' z głosem PL - pomijam audio (wrzuć własne pliki do $out/audio)"
  fi
  find "$out" -type f | sort
}

run() {
  local data_abs; data_abs=$(cd "$DATA" && pwd)
  local res="./results/$RUN"
  mkdir -p ./results
  mkdir "$res" || { echo "Wybierz nową nazwę RUN, aby oddzielić przebiegi." >&2; return 1; }
  for uc in $(uc_list "$@"); do
    case "$uc" in
      text) printf '%s\n' text_embedding text_topic ;;
      *) printf '%s\n' "$uc" ;;
    esac
  done > "$res/expected-suites.txt"
  local cpu_flag=(); [ -n "$CPUS" ] && cpu_flag=(--cpus "$CPUS")
  for uc in $(uc_list "$@"); do
    echo "=== run tm-$uc (cpus=$CPUS threads=$THREADS data=$DATA)"
    docker run --rm --network none "${cpu_flag[@]}" --memory "$MEM" \
      -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
      -e BENCH_THREADS="$THREADS" -e BENCH_REPEATS="${REPEATS:-3}" \
      -e BENCH_WARMUP="${WARMUP:-1}" -e BENCH_MAX_ITEMS="${MAX_ITEMS:-20}" \
      -e BENCH_MODELS="${MODELS:-}" \
      -v "$data_abs:/data:ro" -v "$PWD/$res:/results" \
      "tm-$uc:latest" 2>&1 | tee "$res/$uc.log" || echo "$uc" >> "$res/failed-containers.txt"
  done
  python3 scripts/report.py "$res"
}

report() { python3 scripts/report.py "${1:-$(ls -d results/*/ | tail -1)}"; }

cmd=${1:-help}; shift || true
case "$cmd" in
  build) build "$@" ;;
  samples) samples ;;
  run) run "$@" ;;
  report) report "$@" ;;
  all) build "$@"; samples; run "$@" ;;
  *) sed -n '2,20p' "$0" ;;
esac
=======
for uc in $(uc_list "$@"); do
  echo "=== bench tm-$uc (cpus=$CPUS threads=${THREADS:-1,all} data=$DATA)"
  # shellcheck disable=SC2046
  docker run $(docker_flags "$uc") "${cpu_flag[@]}" --memory "$MEM" \
    -e BENCH_THREADS="${THREADS:-1,all}" -e BENCH_REPEATS="${REPEATS:-3}" \
    -e BENCH_WARMUP="${WARMUP:-1}" -e BENCH_MAX_ITEMS="${MAX_ITEMS:-20}" \
    -e MODELS="${MODELS:-}" \
    -v "$data_abs:/data:ro" -v "$res_abs:/results" \
    "tm-$uc:latest" python /app/common/main.py bench 2>&1 | tee "$res/$uc.log"
done
python3 scripts/report.py "$res"
>>>>>>> 2226231 (dalsza czesc benchmarka)
