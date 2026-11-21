# Wspólne ustawienia skryptów (source).
# Kolejność ma znaczenie dla extract: ocr i asr przed text (text czyta ocr.text / asr.text).
ALL_UC=(face ocr asr image_embedding object_detection ai_generated aigi_effort text)
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Wybrane kontenery zawsze w kolejności ALL_UC; nieznana nazwa = błąd.
uc_list() {
  if [ $# -eq 0 ]; then echo "${ALL_UC[@]}"; return; fi
  local uc want out=()
  for want in "$@"; do
    case " ${ALL_UC[*]} " in *" $want "*) ;; *) echo "nieznany kontener: $want" >&2; return 1 ;; esac
  done
  for uc in "${ALL_UC[@]}"; do
    for want in "$@"; do [ "$uc" = "$want" ] && out+=("$uc") && break; done
  done
  echo "${out[@]}"
}

# Wersja kodu do metadanych przebiegu (z oznaczeniem niezacommitowanych zmian).
git_rev() {
  local rev; rev=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null) || { echo unknown; return; }
  if [ -n "$(git -C "$ROOT" status --porcelain -- . 2>/dev/null)" ]; then rev="$rev-dirty"; fi
  echo "$rev"
}

# Wspólne flagi docker run: bez sieci (modele są w obrazie), aktualny kod z repo zamontowany
# read-only (obraz z ./build.sh zawiera ten sam kod, mount tylko omija przebudowę).
docker_flags() {
  local uc=$1
  echo --rm --network none \
    -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 -e NO_ALBUMENTATIONS_UPDATE=1 \
    -e IMAGE_ID="$(docker image inspect -f '{{.Id}}' "tm-$uc:latest" 2>/dev/null | cut -c8-19)" \
    -e GIT_REV="$(git_rev)" \
    -v "$ROOT/common:/app/common:ro" -v "$ROOT/containers/$uc:/app/uc:ro" \
    $( [ "$uc" = aigi_effort ] && [ -d "$ROOT/weights/effort" ] && \
       echo -v "$ROOT/weights/effort:/opt/effort/DeepfakeBench/training/weights:ro" )
}

abs_dir() { (cd "$1" && pwd); }
