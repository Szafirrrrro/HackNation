#!/usr/bin/env bash
# BENCHMARK (tylko pomiar CPU/RAM/latencji; nie produkuje cech - do tego służy ./extract.sh).
# Wynik: out/benchmark/<RUN>/summary.md + <use_case>.json + logi.
#
#   ./bench.sh run    [use_case...]   # pomiar (bez sieci); domyślnie wszystkie kontenery
#   ./bench.sh report [out/benchmark/<RUN>]
#   ./bench.sh build  [use_case...]   # = ./build.sh
#   ./bench.sh samples                # = scripts/make_samples.sh (syntetyczne dane -> data/sample)
#
# Zmienne: DATA (domyślnie ./data/sample; korpus v0 z ads.jsonl albo luźny katalog plików),
#   CPUS=4 (limit docker --cpus, puste = brak), MEM=6g, THREADS=1,all, REPEATS=3, WARMUP=1,
#   MAX_ITEMS=20, MODELS=substr1,substr2 (filtr nazw), RUN=nazwa (nowa; istniejąca = błąd).
set -euo pipefail
source "$(dirname "$0")/scripts/common.sh"
cd "$ROOT"

DATA=${DATA:-./data/sample}
CPUS=${CPUS:-4}
MEM=${MEM:-6g}
THREADS=${THREADS:-1,all}
RUN=${RUN:-$(date +%Y%m%d_%H%M%S)}

# use case'y zapisywane przez dany kontener (kontener text mierzy dwa zestawy)
suites() {
  case "$1" in
    text) printf '%s\n' text_embedding text_topic ;;
    image_embedding) printf '%s\n' image_embedding qr ;;
    *) printf '%s\n' "$1" ;;
  esac
}

run() {
  local data_abs; data_abs=$(abs_dir "$DATA")
  local ucs; ucs=$(uc_list "$@") || return 1
  local res="./out/benchmark/$RUN"
  mkdir -p ./out/benchmark
  mkdir "$res" || { echo "Wybierz nową nazwę RUN, aby oddzielić przebiegi." >&2; return 1; }
  local res_abs; res_abs=$(abs_dir "$res")
  for uc in $ucs; do suites "$uc"; done > "$res/expected-suites.txt"
  local cpu_flag=(); [ -n "$CPUS" ] && cpu_flag=(--cpus "$CPUS")
  for uc in $ucs; do
    echo "=== bench tm-$uc (cpus=$CPUS threads=$THREADS data=$DATA)"
    # shellcheck disable=SC2046
    docker run $(docker_flags "$uc") "${cpu_flag[@]}" --memory "$MEM" \
      -e BENCH_THREADS="$THREADS" -e BENCH_REPEATS="${REPEATS:-3}" \
      -e BENCH_WARMUP="${WARMUP:-1}" -e BENCH_MAX_ITEMS="${MAX_ITEMS:-20}" \
      -e MODELS="${MODELS:-}" -e CORPUS_HOST_PATH="$data_abs" \
      -v "$data_abs:/data:ro" -v "$res_abs:/results" \
      "tm-$uc:latest" python /app/common/main.py bench 2>&1 | tee "$res/$uc.log" \
      || echo "$uc" >> "$res/failed-containers.txt"
  done
  python3 scripts/report.py "$res"
}

# bez argumentu: najnowszy (wg czasu modyfikacji) przebieg
report() { python3 scripts/report.py "${1:-$(ls -td out/benchmark/*/ | head -1)}"; }

cmd=${1:-help}; shift || true
case "$cmd" in
  run) run "$@" ;;
  report) report "$@" ;;
  build) "$ROOT/build.sh" "$@" ;;
  samples) "$ROOT/scripts/make_samples.sh" ;;
  *) sed -n '2,14p' "$0" ;;
esac
