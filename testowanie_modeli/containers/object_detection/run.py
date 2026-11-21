"""Open-vocabulary detekcja elementów reklamy: logotypy, kody QR, twarze/osoby,
banknoty, karty płatnicze, telefony, wykresy - opisane tekstem, bez trenowania."""
import torch
from PIL import Image

from bench import IMG_EXT, ModelSpec, files, run_suite, short_label

QUERIES = ["a logo", "a qr code", "a person", "banknotes", "a credit card",
           "a smartphone", "a chart", "a flag"]


def inputs():
    return files("images", IMG_EXT)


def load_owl(threads):
    from transformers import Owlv2ForObjectDetection, Owlv2Processor
    mid = "google/owlv2-base-patch16-ensemble"
    return Owlv2ForObjectDetection.from_pretrained(mid).eval(), Owlv2Processor.from_pretrained(mid)


def infer_owl(mm, path):
    m, p = mm
    im = Image.open(path).convert("RGB")
    with torch.inference_mode():
        inp = p(text=[QUERIES], images=im, return_tensors="pt")
        out = m(**inp)
    # OWLv2 dopełnia obraz do kwadratu -> target = max(w,h)
    s = max(im.size)
    r = p.post_process_object_detection(out, threshold=0.2, target_sizes=torch.tensor([[s, s]]))[0]
    return sorted({QUERIES[int(l)] for l in r["labels"]})


def load_gdino(threads):
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
    mid = "IDEA-Research/grounding-dino-tiny"
    return AutoModelForZeroShotObjectDetection.from_pretrained(mid).eval(), AutoProcessor.from_pretrained(mid)


def infer_gdino(mm, path):
    m, p = mm
    im = Image.open(path).convert("RGB")
    text = ". ".join(QUERIES) + "."
    with torch.inference_mode():
        inp = p(images=im, text=text, return_tensors="pt")
        out = m(**inp)
    r = p.post_process_grounded_object_detection(
        out, inp.input_ids, box_threshold=0.3, text_threshold=0.25,
        target_sizes=[im.size[::-1]])[0]
    return sorted(set(r["labels"]))


run_suite("object_detection", [
    ModelSpec("google/owlv2-base-patch16-ensemble", "object_detection", "Apache-2.0",
              load_owl, infer_owl, inputs, notes="open-vocab, 960x960 wejście", item_label=short_label),
    ModelSpec("IDEA-Research/grounding-dino-tiny", "object_detection", "Apache-2.0",
              load_gdino, infer_gdino, inputs, notes="open-vocab, Swin-T", item_label=short_label),
])
