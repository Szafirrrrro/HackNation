"""Tekst reklam: (1) embeddingi narracji do podobieństwa/klastrowania,
(2) zero-shot klasyfikacja tematyki (NLI) w języku polskim."""
import sys

sys.path.insert(0, "/app/uc")
from bench import ModelSpec, run_suite, texts

from models import EMBED, LABELS, TEMPLATE, ZEROSHOT


def make_embed(hf_id, prefix):
    def load(threads):
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(hf_id, device="cpu")

    def infer(m, item):
        _, txt = item
        v = m.encode([prefix + txt], normalize_embeddings=True)[0]
        return {"dim": int(v.shape[0]), "embedding": v.tolist()}
    return load, infer


def make_zs(hf_id):
    def load(threads):
        from transformers import pipeline
        return pipeline("zero-shot-classification", model=hf_id, device=-1)

    def infer(p, item):
        _, txt = item
        r = p(txt, LABELS, hypothesis_template=TEMPLATE, multi_label=False)
        return {"top": r["labels"][0], "score": round(r["scores"][0], 3)}
    return load, infer


def item_id(item):
    return item[0]


run_suite("text_embedding", [
    ModelSpec(hf_id, "text_embedding", lic, *make_embed(hf_id, pre), texts, notes=note, item_label=item_id)
    for hf_id, pre, lic, note in EMBED
])
run_suite("text_topic", [
    ModelSpec(hf_id, "text_topic", lic, *make_zs(hf_id), texts, notes=note, item_label=item_id)
    for hf_id, lic, note in ZEROSHOT
])
