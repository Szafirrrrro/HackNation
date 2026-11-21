"""OCR zrzutów reklam (PL+EN). ocr.text trafia potem do kontenera text (embeddingi, temat);
ocr.urls to domeny/URL-e odczytane z obrazu (dziedziczą origin_id obrazu)."""
import os

import numpy as np

from extractor import Extractor, Out, find_urls, load_rgb


def _norm(s: str) -> str:
    return " ".join(s.split())


class Tesseract(Extractor):
    name = "tesseract-pol-eng"
    use_case = "ocr"
    family = "text"
    modality = "image"
    primary_field = "ocr.text"
    license = "Apache-2.0"
    notes = "Tesseract 5 LSTM, bardzo lekki"

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
                Out("ocr.urls", find_urls(text), family="infrastructure")]


class EasyOCR(Extractor):
    name = "easyocr-pl-en"
    use_case = "ocr"
    family = "text"
    modality = "image"
    primary_field = "ocr.text"
    version = "easyocr-1.7.2/craft+latin_g2"
    license = "Apache-2.0"
    notes = "CRAFT + CRNN; quantize=False (na aarch64 kwantyzacja daje puste wyniki)"

    def load(self, threads):
        import easyocr
        import torch
        torch.set_num_threads(threads)
        self.r = easyocr.Reader(["pl", "en"], gpu=False, model_storage_directory="/models/easyocr",
                                download_enabled=False, verbose=False, quantize=False)

    def extract(self, item):
        im = np.asarray(load_rgb(item.path))
        res = self.r.readtext(im)  # [(box, text, conf)]
        text = _norm(" ".join(t for _, t, _ in res))
        conf = round(float(np.mean([c for *_, c in res])), 3) if res else None
        blocks = [{"text": t, "conf": round(float(c), 3),
                   "bbox_xyxy": [int(min(p[0] for p in b)), int(min(p[1] for p in b)),
                                 int(max(p[0] for p in b)), int(max(p[1] for p in b))]}
                  for b, t, c in res]
        return [Out("ocr.text", text),
                Out("ocr.confidence", conf),
                Out("ocr.blocks", blocks),
                Out("ocr.urls", find_urls(text), family="infrastructure")]


EXTRACTORS = [Tesseract(), EasyOCR()]
