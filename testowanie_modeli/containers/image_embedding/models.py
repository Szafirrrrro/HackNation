"""Cechy wizualne całej kreacji: embeddingi (szablon/podobieństwo), hashe (duplikaty)."""
import hashlib

import torch

from extractor import Extractor, Out, l2, load_rgb

TAGS = ["a screenshot of a news article", "a social media ad", "a photo of a celebrity",
        "a cryptocurrency trading chart", "medicine or supplement product",
        "a TV studio interview", "a bank or government logo", "a landscape photo"]


class Clip(Extractor):
    name = "clip-vit-b-32-laion2b"
    use_case = "image_embedding"
    family = "visual"
    modality = "image"
    primary_field = "image.embedding"
    version = "hf:laion/CLIP-ViT-B-32-laion2B-s34B-b79K"
    license = "MIT"
    notes = "512d, semantyka + zero-shot tagi"

    def load(self, threads):
        from transformers import CLIPModel, CLIPProcessor
        mid = "laion/CLIP-ViT-B-32-laion2B-s34B-b79K"
        self.m = CLIPModel.from_pretrained(mid).eval()
        self.p = CLIPProcessor.from_pretrained(mid)
        with torch.inference_mode():
            t = self.m.get_text_features(**self.p(text=TAGS, return_tensors="pt", padding=True))
        self.t = torch.nn.functional.normalize(t, dim=-1)

    def extract(self, item):
        with torch.inference_mode():
            f = self.m.get_image_features(**self.p(images=load_rgb(item.path), return_tensors="pt"))
            f = torch.nn.functional.normalize(f, dim=-1)
            sims = (100 * f @ self.t.T)[0].softmax(-1)  # CLIP logit scale ~100
        top = sims.argsort(descending=True)[:3]
        return [Out("image.embedding", l2(f[0].numpy())),
                Out("image.clip_tags", [{"tag": TAGS[int(i)], "p": round(float(sims[i]), 4)}
                                        for i in top])]


class Dino(Extractor):
    name = "dinov2-small"
    use_case = "image_embedding"
    family = "visual"
    modality = "image"
    primary_field = "image.embedding"
    version = "hf:facebook/dinov2-small"
    license = "Apache-2.0"
    notes = "384d (CLS), wierny wyglądowi/szablonowi"

    def load(self, threads):
        from transformers import AutoImageProcessor, AutoModel
        mid = "facebook/dinov2-small"
        self.m = AutoModel.from_pretrained(mid).eval()
        self.p = AutoImageProcessor.from_pretrained(mid)

    def extract(self, item):
        with torch.inference_mode():
            out = self.m(**self.p(images=load_rgb(item.path), return_tensors="pt"))
        return [Out("image.embedding", l2(out.pooler_output[0].numpy()))]


class Hashes(Extractor):
    name = "imagehash-phash-dhash"
    use_case = "image_embedding"
    family = "visual"
    modality = "image"
    primary_field = "image.phash"
    version = "imagehash-4.3.1/phash64+dhash64+sha256"
    license = "BSD-2-Clause"
    notes = "nie-ML: identyczne pliki (sha256) i bliskie duplikaty (Hamming na 64 bitach)"

    def load(self, threads):
        import imagehash
        self.ih = imagehash

    def extract(self, item):
        with open(item.path, "rb") as f:
            sha = hashlib.sha256(f.read()).hexdigest()
        im = load_rgb(item.path)
        return [Out("image.sha256", sha),
                Out("image.size", {"width": im.size[0], "height": im.size[1]}),
                Out("image.phash", str(self.ih.phash(im))),
                Out("image.dhash", str(self.ih.dhash(im)))]


EXTRACTORS = [Clip(), Dino(), Hashes()]
