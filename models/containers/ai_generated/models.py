"""Czy kreacja pochodzi z generatora AI.

reverse-SynthID (aloshdenny, Research License - tylko detekcja, bez bypassu):
  cross-color consensus codebook (spectral_codebook_v4), FFT w natywnej rozdzielczości.
  UWAGA: niezależne testy raportują brak mocy dyskryminacyjnej na obrazach z treścią
  (AUC ~0.2) - wynik traktować najwyżej jako cechę pomocniczą.
SigLIP "AI vs human" - ogólny klasyfikator, niezależny od SynthID.
"""
import sys

import numpy as np

from extractor import Extractor, Out, load_rgb

sys.path.insert(0, "/opt/rsid/src/extraction")
RSID = "/opt/rsid/artifacts"
RSID_VER = "reverse-SynthID@b110836"
RSID_LIC = ("reverse-SynthID Research License: niekomercyjnie, atrybucja "
            "'reverse-SynthID by Alosh Denny — github.com/aloshdenny/reverse-SynthID'")


class SynthIDv4(Extractor):
    stage = "excluded"
    decision = "Pominięte w grupowaniu: ten sam generator może służyć niezależnym kampaniom."
    name = "reverse-synthid-v4"
    use_case = "ai_generated"
    family = "visual"
    modality = "image"
    primary_field = "ai.synthid"
    version = f"{RSID_VER}/spectral_codebook_v4.npz"
    license = RSID_LIC
    notes = "FFT w natywnej rozdzielczości, profile per model Gemini i rozdzielczość"

    def load(self, threads):
        from robust_extractor import RobustSynthIDExtractor
        from synthid_bypass_v4 import SpectralCodebookV4
        self.cb = SpectralCodebookV4()
        self.cb.load(f"{RSID}/spectral_codebook_v4.npz")
        self.ext = RobustSynthIDExtractor()

    def extract(self, item):
        r = self.ext.detect_from_v4_codebook(np.asarray(load_rgb(item.path)), self.cb)
        return [Out("ai.synthid", {"watermarked": bool(r.is_watermarked),
                                   "confidence": round(float(r.confidence), 4),
                                   "phase_match": round(float(r.phase_match), 4),
                                   "profile": r.details.get("profile_key"),
                                   "exact_resolution": r.details.get("exact_match")})]


class SigLIPDetector(Extractor):
    stage = "excluded"
    decision = "Pominięte w grupowaniu: jak reverse-SynthID."
    name = "ai-vs-human-siglip"
    use_case = "ai_generated"
    family = "visual"
    modality = "image"
    primary_field = "ai.generated"
    version = "hf:Ateeqq/ai-vs-human-image-detector"
    hf_repo = "Ateeqq/ai-vs-human-image-detector"
    license = "Apache-2.0"
    notes = "SigLIP fine-tune, ogólny AI-vs-real"

    def load(self, threads):
        from transformers import pipeline
        self.p = pipeline("image-classification", model="Ateeqq/ai-vs-human-image-detector",
                          device=-1)

    def extract(self, item):
        r = self.p(load_rgb(item.path), top_k=None)
        probs = {x["label"]: round(float(x["score"]), 4) for x in r}
        return [Out("ai.generated", {"probs": probs, "top": r[0]["label"]})]


EXTRACTORS = [SynthIDv4(), SigLIPDetector()]
