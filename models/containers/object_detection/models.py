"""Open-vocabulary detekcja elementów kreacji (opisane tekstem, bez trenowania)."""
import torch

from extractor import Extractor, Out, load_rgb

QUERIES = ["a logo", "a qr code", "a person", "banknotes", "a credit card",
           "a smartphone", "a chart", "a flag"]


def _outs(labels, scores, boxes):
    dets = [{"label": l, "score": round(float(s), 4), "bbox_xyxy": [int(v) for v in b]}
            for l, s, b in zip(labels, scores, boxes)]
    dets.sort(key=lambda d: -d["score"])
    return [Out("objects.detections", dets),
            Out("objects.labels", sorted({d["label"] for d in dets}))]


class OwlV2(Extractor):
    stage = "on_demand"
    decision = ("Poza profilem domyślnym: ok. 10 s na obraz przekracza budżet, a kategorie obiektów "
                "to słaby ślad; dla QR używamy dekodera (qr.values).")
    name = "owlv2-base-patch16-ensemble"
    use_case = "object_detection"
    family = "visual"
    modality = "image"
    primary_field = "objects.labels"
    version = "hf:google/owlv2-base-patch16-ensemble"
    hf_repo = "google/owlv2-base-patch16-ensemble"
    params = {"queries": QUERIES, "threshold": 0.2}
    license = "Apache-2.0"
    notes = "open-vocab, wejście 960x960"

    def load(self, threads):
        from transformers import Owlv2ForObjectDetection, Owlv2Processor
        mid = "google/owlv2-base-patch16-ensemble"
        self.m = Owlv2ForObjectDetection.from_pretrained(mid).eval()
        self.p = Owlv2Processor.from_pretrained(mid)

    def extract(self, item):
        im = load_rgb(item.path)
        with torch.inference_mode():
            out = self.m(**self.p(text=[QUERIES], images=im, return_tensors="pt"))
        s = max(im.size)  # OWLv2 dopełnia obraz do kwadratu
        r = self.p.post_process_object_detection(out, threshold=self.params["threshold"],
                                                 target_sizes=torch.tensor([[s, s]]))[0]
        return _outs([QUERIES[int(l)] for l in r["labels"]], r["scores"].tolist(), r["boxes"].tolist())


EXTRACTORS = [OwlV2()]
