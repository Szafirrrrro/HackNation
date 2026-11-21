#!/usr/bin/env bash
# Buduje obraz bazowy i obrazy use case'ów (wagi modeli wbudowane w obraz).
#   ./build.sh                 # wszystkie
#   ./build.sh face ocr        # wybrane
set -euo pipefail
source "$(dirname "$0")/scripts/common.sh"
cd "$ROOT"
docker build -t tm-base:latest -f base/Dockerfile .
for uc in $(uc_list "$@"); do
  echo "=== build tm-$uc"
  docker build -t "tm-$uc:latest" -f "containers/$uc/Dockerfile" .
done
