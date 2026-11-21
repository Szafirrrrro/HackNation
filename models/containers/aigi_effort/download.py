"""CLIP ViT-L/14 jako katalog HF w miejscu, którego oczekuje effort_detector.py."""
import sys
from pathlib import Path

from dl import fetch

DST = Path("/opt/effort/models--openai--clip-vit-large-patch14")
fetch("openai/clip-vit-large-patch14", local_dir=str(DST),
      allow_patterns=["*.json", "*.txt", "model.safetensors"])
w = DST / "model.safetensors"
if not w.exists() or w.stat().st_size < 1_000_000_000:  # ~1.7 GB; przerwanie pobierania = błąd budowy
    sys.exit(f"brak lub niekompletne wagi CLIP-L/14: {w}")
(DST / "REVISION").write_text("openai/clip-vit-large-patch14\n")
