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
    decision = ("Jedyny OCR (benchmark 2026-11-22): czyta 61% znanych słów przy p95 ok. 0,4 s; "
                "CER niezmierzony.")
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


EXTRACTORS = [Tesseract()]
