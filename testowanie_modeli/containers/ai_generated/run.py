"""Wykrywanie obrazów generowanych przez AI.

1-2) reverse-SynthID (spektralny detektor watermarku SynthID z Gemini):
     v3 = codebook pickle + phase match przy 512x512,
     v4 = cross-color consensus codebook w natywnej rozdzielczości.
     UWAGA: niezależne testy (froggeric/gemini-watermark-and-synthid-remover)
     raportują brak mocy dyskryminacyjnej na obrazach z treścią (AUC ~0.2) -
     dlatego benchmark daje też etykietowany zbiór do weryfikacji skuteczności.
3)   klasyfikator neuronowy "AI vs human" (SigLIP) jako sygnał niezależny od SynthID.
"""
import sys

import cv2

sys.path.insert(0, "/opt/rsid/src/extraction")
from bench import IMG_EXT, ModelSpec, files, run_suite, short_label

RSID = "/opt/rsid/artifacts"


def inputs():
    return files("ai_generated", IMG_EXT) or files("images", IMG_EXT)


def load_v3(threads):
    from robust_extractor import RobustSynthIDExtractor
    # codebook to pickle z repo upstream (przypięty commit) - ładowany tylko w kontenerze
    return RobustSynthIDExtractor(codebook_path=f"{RSID}/codebook/robust_codebook.pkl")


def infer_v3(ext, path):
    r = ext.detect(path)
    return {"wm": r.is_watermarked, "conf": round(r.confidence, 3),
            "phase_match": round(r.phase_match, 3)}


def load_v4(threads):
    from robust_extractor import RobustSynthIDExtractor
    from synthid_bypass_v4 import SpectralCodebookV4
    cb = SpectralCodebookV4()
    cb.load(f"{RSID}/spectral_codebook_v4.npz")
    ext = RobustSynthIDExtractor()
    return ext, cb


def infer_v4(m, path):
    ext, cb = m
    img = cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2RGB)
    r = ext.detect_from_v4_codebook(img, cb)
    return {"wm": r.is_watermarked, "conf": round(r.confidence, 3),
            "phase_match": round(r.phase_match, 3),
            "profile": r.details.get("profile_key"), "exact": r.details.get("exact_match")}


def load_siglip(threads):
    from transformers import pipeline
    return pipeline("image-classification", model="Ateeqq/ai-vs-human-image-detector", device=-1)


def infer_siglip(p, path):
    r = p(path, top_k=2)
    return {x["label"]: round(x["score"], 3) for x in r}


run_suite("ai_generated", [
    ModelSpec("reverse-SynthID/v3-robust", "ai_generated",
              "reverse-SynthID Research License (niekomercyjna, atrybucja)",
              load_v3, infer_v3, inputs, notes="FFT + wavelet denoise, bez sieci neuronowej",
              item_label=short_label),
    ModelSpec("reverse-SynthID/v4-consensus", "ai_generated",
              "reverse-SynthID Research License (niekomercyjna, atrybucja)",
              load_v4, infer_v4, inputs, notes="FFT w natywnej rozdzielczości, codebook per model/rozdz.",
              item_label=short_label),
    ModelSpec("Ateeqq/ai-vs-human-image-detector", "ai_generated", "Apache-2.0",
              load_siglip, infer_siglip, inputs, notes="SigLIP fine-tune, ogólny AI-vs-real",
              item_label=short_label),
])
