#!/usr/bin/env bash
# Effort (AIGI detection) - dokładnie komenda z repozytorium Effort, uruchomiona w kontenerze:
#
#   ./effort.sh --detector_config training/config/detector/effort.yaml \
#       --weights ./training/weights/effort_clip_L14_trainOn_sdv14.pth --image ~/MNW/AI_Images/
#
# Bez argumentów używa tej konfiguracji i wag, a obrazy bierze z IMAGE (domyślnie ~/MNW/AI_Images/).
# Katalog roboczy w kontenerze to DeepfakeBench/, więc ścieżki względne działają jak w README Effort.
# Wagi .pth: models/weights/effort/ (montowane jako training/weights/, tylko odczyt).
# Ścieżka --image (np. ~/MNW/AI_Images/ rozwinięta przez powłokę) jest montowana pod tą samą
# ścieżką w kontenerze, tylko do odczytu. Bez sieci.
set -euo pipefail
source "$(dirname "$0")/scripts/common.sh"

if [ $# -eq 0 ]; then
  set -- --detector_config training/config/detector/effort.yaml \
    --weights ./training/weights/effort_clip_L14_trainOn_sdv14.pth --image "${IMAGE:-$HOME/MNW/AI_Images/}"
fi
mounts=()
args=()
for a in "$@"; do  # --opcja=wartość -> --opcja wartość
  case "$a" in --image=*|--weights=*|--detector_config=*) args+=("${a%%=*}" "${a#*=}") ;; *) args+=("$a") ;; esac
done
for ((i = 0; i < ${#args[@]}; i++)); do
  if [ "${args[$i]}" = "--image" ] && [ $((i + 1)) -lt ${#args[@]} ]; then
    p="${args[$((i + 1))]}"
    [ -e "$p" ] || { echo "nie istnieje: $p" >&2; exit 1; }
    d=$(cd "$( [ -d "$p" ] && echo "$p" || dirname "$p")" && pwd)
    mounts+=(-v "$d:$d:ro")
    [ -d "$p" ] && args[$((i + 1))]="$d/" || args[$((i + 1))]="$d/$(basename "$p")"
  fi
done
[ -d "$ROOT/weights/effort" ] || { echo "brak $ROOT/weights/effort/ z plikiem .pth" >&2; exit 1; }
for ((i = 0; i < ${#args[@]}; i++)); do
  if [ "${args[$i]}" = "--weights" ] && [ $((i + 1)) -lt ${#args[@]} ]; then
    w="${args[$((i + 1))]}"
    case "$w" in ./training/weights/*|training/weights/*) ;; *)
      echo "--weights musi wskazywać plik w training/weights/ (= $ROOT/weights/effort/)" >&2; exit 1 ;; esac
    [ -f "$ROOT/weights/effort/${w##*/training/weights/}" ] || {
      echo "brak wag: $ROOT/weights/effort/${w##*/training/weights/}" >&2; exit 1; }
  fi
done
docker run --rm --network none -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  -v "$ROOT/weights/effort:/opt/effort/DeepfakeBench/training/weights:ro" ${mounts[@]+"${mounts[@]}"} \
  -w /opt/effort/DeepfakeBench tm-aigi_effort:latest python3 training/demo.py "${args[@]}"
