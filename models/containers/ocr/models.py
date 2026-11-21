"""OCR zrzutów reklam (PL+EN). ocr.text trafia potem do kontenera text (embeddingi, temat);
ocr.urls to domeny/URL-e odczytane z obrazu (dziedziczą origin_id obrazu)."""
import os

import numpy as np

from extractor import Extractor, Out, find_urls, load_rgb


def _norm(s: str) -> str:
    return " ".join(s.split())


def _urls(text: str) -> Out:
    """Domeny z OCR; brak domeny to brak śladu (unavailable), nie pusta zgodna wartość."""
    urls = find_urls(text)
    return Out("ocr.urls", urls, family="infrastructure") if urls else \
        Out("ocr.urls", family="infrastructure", reason="no_url_in_ocr_text")


class Tesseract(Extractor):
    stage = "default"
    decision = ("Jedyny OCR w profilu domyślnym (zgoda użytkownika 2026-11-21): p95 ~0,4 s; "
                "wybrany ze względu na koszt, jakość (CER) niezmierzona.")
    name = "tesseract-pol-eng"
    use_case = "ocr"
    family = "text"
    modality = "image"
    primary_field = "ocr.text"
    license = "Apache-2.0"
    notes = "Tesseract 5 LSTM, bardzo lekki"
    params = {"lang": "pol+eng", "min_conf": 0}

    @property
    def version(self):
        import pytesseract
        return f"tesseract-{pytesseract.get_tesseract_version()}/pol+eng"

    def load(self, threads):
        import pytesseract
        os.environ["OMP_THREAD_LIMIT"] = str(threads)
        self.pt = pytesseract

    def extract(self, item):
        im = load_rgb(item.path)
        d = self.pt.image_to_data(im, lang="pol+eng", output_type=self.pt.Output.DICT)
        words = [(w, float(c)) for w, c in zip(d["text"], d["conf"]) if w.strip() and float(c) >= 0]
        text = _norm(" ".join(w for w, _ in words))
        conf = round(float(np.mean([c for _, c in words])) / 100, 3) if words else None
        return [Out("ocr.text", text),
                Out("ocr.confidence", conf),
                _urls(text)]


class EasyOCR(Extractor):
    stage = "deferred"
    decision = ("Odłożone (zgoda użytkownika 2026-11-21): p95 14,5 s na CPU przekracza budżet 5 s; "
                "zostaje Tesseract. CER nie był mierzony (brak referencji).")
    name = "easyocr-pl-en"
    use_case = "ocr"
    family = "text"
    modality = "image"
    primary_field = "ocr.text"
    version = "easyocr-1.7.2/craft+latin_g2"
    license = "Apache-2.0"
    notes = ("CRAFT + CRNN; paragraph=True (kolejność czytania jak w planie porównania CER); "
             "quantize=False (na aarch64 kwantyzacja daje puste wyniki); bez ocr.confidence")
    params = {"langs": ["pl", "en"], "paragraph": True, "quantize": False}

    def load(self, threads):
        import easyocr
        import torch
        torch.set_num_threads(threads)
        self.r = easyocr.Reader(["pl", "en"], gpu=False, model_storage_directory="/models/easyocr",
                                download_enabled=False, verbose=False, quantize=False)

    def extract(self, item):
        im = np.asarray(load_rgb(item.path))
        res = self.r.readtext(im, paragraph=True)  # [(box, text)] - akapity, bez pewności
        text = _norm(" ".join(t for _, t in res))
        blocks = [{"text": t,
                   "bbox_xyxy": [int(min(p[0] for p in b)), int(min(p[1] for p in b)),
                                 int(max(p[0] for p in b)), int(max(p[1] for p in b))]}
                  for b, t in res]
        return [Out("ocr.text", text),
                Out("ocr.blocks", blocks),
                _urls(text)]


EXTRACTORS = [Tesseract(), EasyOCR()]
