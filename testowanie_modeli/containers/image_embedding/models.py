"""Cechy wizualne całej kreacji: embeddingi (szablon/podobieństwo), hashe (duplikaty)."""
import hashlib

import torch

from extractor import Extractor, Out, Unavailable, find_urls, l2, load_bgr, load_rgb

TAGS = ["a screenshot of a news article", "a social media ad", "a photo of a celebrity",
        "a cryptocurrency trading chart", "medicine or supplement product",
        "a TV studio interview", "a bank or government logo", "a landscape photo"]


class Clip(Extractor):
    stage = "deferred"
    decision = "Odłożone do zadania wyszukiwania obrazów o wspólnym znaczeniu."
    name = "clip-vit-b-32-laion2b"
    use_case = "image_embedding"
    family = "visual"
    modality = "image"
    primary_field = "image.embedding"
    version = "hf:laion/CLIP-ViT-B-32-laion2B-s34B-b79K"
    hf_repo = "laion/CLIP-ViT-B-32-laion2B-s34B-b79K"
    params = {"tags": TAGS, "top_k": 3}
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
    stage = "default"
    decision = ("Domyślne obok pHash jako sygnał RANKINGU (out/eval/decisions.md, 2026-11-21): odnajduje "
                "syntetyczne kadry/warianty lepiej niż pHash; próg nie jest punktem pracy - 2/4 "
                "tymczasowe pary rzeczywiste mają cos < 0,77.")
    name = "dinov2-small"
    use_case = "image_embedding"
    family = "visual"
    modality = "image"
    primary_field = "image.embedding"
    version = "hf:facebook/dinov2-small"
    hf_repo = "facebook/dinov2-small"
    params = {"pooling": "pooler_output"}
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
    stage = "default"
    decision = "Domyślne: SHA-256 dla identycznych plików, pHash/dHash dla podobnego kadru."
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
        # SHA-256 z bajtów, niezależnie od dekodowania (identyczny plik = ten sam zasób)
        h = hashlib.sha256()
        with open(item.path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        outs = [Out("image.sha256", h.hexdigest())]
        try:
            im = load_rgb(item.path)
        except Unavailable as e:
            return outs + [Out(k, reason=str(e)) for k in ("image.size", "image.phash", "image.dhash")]
        return outs + [Out("image.size", {"width": im.size[0], "height": im.size[1]}),
                       Out("image.phash", str(self.ih.phash(im))),
                       Out("image.dhash", str(self.ih.dhash(im)))]




class ORB(Extractor):
    name = "opencv-orb"
    use_case = "image_embedding"
    family = "visual"
    modality = "image"
    primary_field = "image.orb"
    stage = "candidate"
    decision = ("Kandydat (przegląd 2026-11-21): na syntetycznych wariantach top-3 39/39, ale niepowiązane "
                "zrzuty z tą samą ramką platformy osiągają 216 dopasowań wobec progu 222 - wynik napędza "
                "wspólny interfejs. Wymaga weryfikacji geometrycznej lub testu na ponownym renderze.")
    license = "Apache-2.0 (OpenCV)"
    notes = "binarne deskryptory 32 B; porównanie: BFMatcher Hamming + test Lowe'a"
    params = {"nfeatures": 1000, "max_side": 1024}

    @property
    def version(self):
        import cv2
        return f"opencv-{cv2.__version__}/orb"

    def load(self, threads):
        import cv2
        cv2.setNumThreads(threads)
        self.cv2 = cv2
        self.orb = cv2.ORB_create(nfeatures=self.params["nfeatures"])

    def extract(self, item):
        cv2 = self.cv2
        gray = cv2.cvtColor(load_bgr(item.path), cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        scale = min(1.0, self.params["max_side"] / max(h, w))
        if scale < 1:
            gray = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        kps, des = self.orb.detectAndCompute(gray, None)
        if des is None:
            return [Out("image.orb", reason="no_keypoints")]
        return [Out("image.orb", {"array": des, "n_keypoints": len(kps), "scale": round(scale, 4)})]


class QR(Extractor):
    name = "opencv-qr"
    use_case = "qr"
    family = "infrastructure"
    modality = "image"
    primary_field = "qr.count"
    stage = "default"
    decision = ("Domyślne (zaakceptowane): zamiast detektora obiektów dekodujemy QR - "
                "dokładną wartość da się porównać między reklamami.")
    license = "Apache-2.0 (OpenCV)"
    notes = "cv2.QRCodeDetector.detectAndDecodeMulti; wartość dziedziczy pochodzenie obrazu"

    @property
    def version(self):
        import cv2
        return f"opencv-{cv2.__version__}/qrcode"

    def load(self, threads):
        import cv2
        self.det = cv2.QRCodeDetector()

    def extract(self, item):
        img = load_bgr(item.path)
        ok, values, points, _ = self.det.detectAndDecodeMulti(img)
        values = [v for v in (values or []) if v] if ok else []
        # brak kodu QR to brak śladu, nie zgodna wartość: qr.values/qr.urls -> unavailable
        outs = [Out("qr.count", len(values))]
        if not values:
            return outs + [Out("qr.values", reason="no_qr_detected"), Out("qr.urls", reason="no_qr_detected")]
        urls = sorted({u for v in values for u in find_urls(v)})
        return outs + [Out("qr.values", values),
                       Out("qr.urls", urls) if urls else Out("qr.urls", reason="no_url_in_qr")]


EXTRACTORS = [Clip(), Dino(), Hashes(), ORB(), QR()]
