"""OCR zrzutów ekranu reklam (PL + EN): tekst, URL-e, nazwy produktów."""
import os

from bench import IMG_EXT, ModelSpec, files, run_suite, short_label


def inputs():
    return files("screenshots", IMG_EXT) or files("images", IMG_EXT)


def load_tess(threads):
    import pytesseract
    os.environ["OMP_THREAD_LIMIT"] = str(threads)
    return pytesseract


def infer_tess(pt, path):
    txt = pt.image_to_string(path, lang="pol+eng")
    return " ".join(txt.split())


def load_easy(threads):
    import easyocr
    import torch
    torch.set_num_threads(threads)
    return easyocr.Reader(["pl", "en"], gpu=False, model_storage_directory="/models/easyocr",
                          download_enabled=False, verbose=False)


def infer_easy(r, path):
    res = r.readtext(path, detail=0, paragraph=True)
    return " ".join(res)


run_suite("ocr", [
    ModelSpec("tesseract-5/pol+eng", "ocr", "Apache-2.0", load_tess, infer_tess, inputs,
              notes="LSTM, klasyczny, bardzo lekki; słabszy na tekście na tle zdjęć",
              item_label=short_label),
    ModelSpec("easyocr/craft+latin_g2 (pl,en)", "ocr", "Apache-2.0", load_easy, infer_easy, inputs,
              notes="CRAFT detektor + CRNN; lepszy na tekście w grafikach",
              item_label=short_label),
])
