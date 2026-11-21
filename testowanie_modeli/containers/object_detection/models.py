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
    name = "owlv2-base-patch16-ensemble"
    use_case = "object_detection"
    family = "visual"
    modality = "image"
    primary_field = "objects.labels"
    version = "hf:google/owlv2-base-patch16-ensemble/thr0.2"
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
        r = self.p.post_process_object_detection(out, threshold=0.2,
                                                 target_sizes=torch.tensor([[s, s]]))[0]
        return _outs([QUERIES[int(l)] for l in r["labels"]], r["scores"].tolist(), r["boxes"].tolist())


class GroundingDino(Extractor):
    name = "grounding-dino-tiny"
    use_case = "object_detection"
    family = "visual"
    modality = "image"
    primary_field = "objects.labels"
    version = "hf:IDEA-Research/grounding-dino-tiny/box0.3-text0.25"
    license = "Apache-2.0"
    notes = "open-vocab, Swin-T"

    def load(self, threads):
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
        mid = "IDEA-Research/grounding-dino-tiny"
        self.m = AutoModelForZeroShotObjectDetection.from_pretrained(mid).eval()
        self.p = AutoProcessor.from_pretrained(mid)

    def extract(self, item):
        im = load_rgb(item.path)
        with torch.inference_mode():
            inp = self.p(images=im, text=". ".join(QUERIES) + ".", return_tensors="pt")
            out = self.m(**inp)
        r = self.p.post_process_grounded_object_detection(
            out, inp.input_ids, box_threshold=0.3, text_threshold=0.25,
            target_sizes=[im.size[::-1]])[0]
        return _outs(list(r["labels"]), r["scores"].tolist(), r["boxes"].tolist())


EXTRACTORS = [OwlV2(), GroundingDino()]
