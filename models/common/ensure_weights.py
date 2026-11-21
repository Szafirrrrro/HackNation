"""Krok budowania obrazu: każde repo HF w /models/hf musi mieć plik wag.

Przy zrywającym się łączu snapshot_download potrafi zakończyć się bez pliku wag
(tak było z grounding-dino-tiny). Ten krok dociąga brakujące wagi, a gdy się nie uda,
przerywa budowanie zamiast zostawić obraz, w którym model nie da się załadować.
"""
import sys
from pathlib import Path

from dl import fetch

HUB = Path("/models/hf/hub")
WEIGHTS = ("*.safetensors", "*.bin", "*.pt", "*.onnx", "*.ckpt")  # .ckpt: SpeechBrain


def has_weights(repo_dir: Path) -> bool:
    return any(p.exists() for pat in WEIGHTS for p in repo_dir.glob(f"snapshots/*/{pat}"))


missing = []
for d in sorted(HUB.glob("models--*")) if HUB.exists() else []:
    repo = d.name[len("models--"):].replace("--", "/")
    if has_weights(d):
        print(f"ok: {repo}")
        continue
    print(f"brak wag: {repo} - pobieram ponownie", flush=True)
    fetch(repo, allow_patterns=["*.json", "*.txt", "*.model", "model.safetensors", "model.bin",
                 "pytorch_model.bin", "*.ckpt", "*.yaml"])
    if not has_weights(d):
        missing.append(repo)
if missing:
    sys.exit(f"nadal brak wag: {missing}")
