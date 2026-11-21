# Wspólne ustawienia skryptów (source).
# Kolejność ma znaczenie dla extract: ocr i asr przed text (text czyta ocr.text / asr.text).
ALL_UC=(face ocr asr image_embedding object_detection ai_generated text)
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

uc_list() { if [ $# -gt 0 ]; then echo "$@"; else echo "${ALL_UC[@]}"; fi; }

# Wspólne flagi docker run: bez sieci (modele są w obrazie), aktualny kod z repo zamontowany
# read-only (obraz z ./build.sh zawiera ten sam kod, mount tylko omija przebudowę).
docker_flags() {
  local uc=$1
  echo --rm --network none \
    -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 -e NO_ALBUMENTATIONS_UPDATE=1 \
    -v "$ROOT/common:/app/common:ro" -v "$ROOT/containers/$uc:/app/uc:ro"
}

abs_dir() { (cd "$1" && pwd); }
