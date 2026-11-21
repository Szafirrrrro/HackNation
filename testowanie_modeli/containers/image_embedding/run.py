"""Embeddingi wizualne: podobieństwo kreacji / szablonu produkcyjnego,
near-duplicate detection. CLIP daje też zero-shot tagi (tematyka obrazu)."""
import torch
from PIL import Image

from bench import IMG_EXT, ModelSpec, files, run_suite, short_label

TAGS = ["a screenshot of a news article", "a social media ad", "a photo of a celebrity",
        "a cryptocurrency trading chart", "medicine or supplement product",
        "a TV studio interview", "a bank or government logo"]


def inputs():
    return files("images", IMG_EXT)


def load_clip(threads):
    from transformers import CLIPModel, CLIPProcessor
    mid = "laion/CLIP-ViT-B-32-laion2B-s34B-b79K"
    m = CLIPModel.from_pretrained(mid).eval()
    p = CLIPProcessor.from_pretrained(mid)
    with torch.inference_mode():
        t = m.get_text_features(**p(text=TAGS, return_tensors="pt", padding=True))
    return m, p, torch.nn.functional.normalize(t, dim=-1)


def infer_clip(mm, path):
    m, p, tfeat = mm
    with torch.inference_mode():
        f = m.get_image_features(**p(images=Image.open(path).convert("RGB"), return_tensors="pt"))
        f = torch.nn.functional.normalize(f, dim=-1)
        sims = (f @ tfeat.T)[0]
    return {"dim": f.shape[-1], "top_tag": TAGS[int(sims.argmax())]}


def load_dino(threads):
    from transformers import AutoImageProcessor, AutoModel
    mid = "facebook/dinov2-small"
    return AutoModel.from_pretrained(mid).eval(), AutoImageProcessor.from_pretrained(mid)


def infer_dino(mm, path):
    m, p = mm
    with torch.inference_mode():
        out = m(**p(images=Image.open(path).convert("RGB"), return_tensors="pt"))
    return {"dim": out.pooler_output.shape[-1]}


def load_hash(threads):
    import imagehash
    return imagehash


def infer_hash(ih, path):
    im = Image.open(path).convert("RGB")
    return {"phash": str(ih.phash(im)), "dhash": str(ih.dhash(im))}


run_suite("image_embedding", [
    ModelSpec("laion/CLIP-ViT-B-32-laion2B", "image_embedding", "MIT", load_clip, infer_clip,
              inputs, notes="512d, semantyka + zero-shot tagi", item_label=short_label),
    ModelSpec("facebook/dinov2-small", "image_embedding", "Apache-2.0", load_dino, infer_dino,
              inputs, notes="384d, wierny wyglądowi/szablonowi (bez tekstu)", item_label=short_label),
    ModelSpec("imagehash/phash+dhash (baseline)", "image_embedding", "BSD-2-Clause",
              load_hash, infer_hash, inputs, notes="nie-ML: dokładne/bliskie duplikaty",
              item_label=short_label),
])
