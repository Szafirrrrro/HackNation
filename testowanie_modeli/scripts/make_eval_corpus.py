"""Korpus ewaluacyjny obrazów: oryginały + deterministyczne warianty każdej kreacji.

    python scripts/make_eval_corpus.py <korpus_v0> <wyjście>

Warianty (ad_id = <oryginał>~<typ>, bez tekstu - test samego obrazu):
  crop   - kadr: środkowe 70% szerokości i 75% wysokości (przycięta ramka platformy),
  corner - kadr: lewa górna 80%x80% (inna część ramki),
  small  - zmniejszenie do 50% + JPEG q60 (ponowna kompresja).
Plik variants.jsonl mapuje wariant na oryginał. Wynik zawiera materiał NASK - trzymaj go
w out/ (ignorowane przez Git).
"""
import json
import shutil
import sys
from pathlib import Path

from PIL import Image

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
if dst.exists():
    shutil.rmtree(dst)
(dst / "media").mkdir(parents=True)
manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
ds = f"{manifest['dataset_id']}-eval-variants"
(dst / "manifest.json").write_text(json.dumps({
    "schema_version": "v0", "dataset_id": ds, "collected_at": manifest.get("collected_at"),
    "source_description": f"Warianty obrazów z {manifest['dataset_id']} do ewaluacji (scripts/make_eval_corpus.py)."},
    ensure_ascii=False, indent=2), encoding="utf-8")
if (src / "observations" / "screenshots.jsonl").exists():
    (dst / "observations").mkdir()
    shutil.copy(src / "observations" / "screenshots.jsonl", dst / "observations" / "screenshots.jsonl")

ads, variants = [], []
for line in (src / "ads.jsonl").read_text(encoding="utf-8").splitlines():
    a = json.loads(line)
    if not a.get("image_path"):
        continue
    name = Path(a["image_path"]).stem
    shutil.copy(src / a["image_path"], dst / "media" / Path(a["image_path"]).name)
    ads.append(a)  # oryginał z tekstem i tym samym ad_id
    im = Image.open(src / a["image_path"]).convert("RGB")
    w, h = im.size
    out = {
        "crop": im.crop((int(.15 * w), int(.125 * h), int(.85 * w), int(.875 * h))),
        "corner": im.crop((0, 0, int(.8 * w), int(.8 * h))),
        "small": im.resize((w // 2, h // 2), Image.LANCZOS),
    }
    for kind, v in out.items():
        rel = f"media/{name}~{kind}.{'jpg' if kind == 'small' else 'png'}"
        v.save(dst / rel, **({"quality": 60} if kind == "small" else {}))
        vid = f"{a['ad_id']}~{kind}"
        ads.append({"ad_id": vid, "source": {**a["source"], "kind": "synthetic",
                                             "ad_ref": f"variant:{kind}:{a['ad_id']}"},
                    "image_path": rel, "image_origin": f"{vid}#image_path"})
        variants.append({"ad_id": vid, "variant_of": a["ad_id"], "kind": kind})

(dst / "ads.jsonl").write_text("".join(json.dumps(a, ensure_ascii=False) + "\n" for a in ads),
                               encoding="utf-8")
(dst / "variants.jsonl").write_text("".join(json.dumps(v) + "\n" for v in variants), encoding="utf-8")
print(f"{ds}: {len(ads)} reklam ({len(variants)} wariantów) -> {dst}")
