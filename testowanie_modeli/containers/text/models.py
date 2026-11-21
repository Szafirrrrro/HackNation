"""Tekst reklam (pole `text` + ocr.text/asr.text z wcześniejszych ekstrakcji):
(1) embeddingi narracji -> podobieństwo/klastrowanie, (2) zero-shot tematyka (NLI, PL)."""
from extractor import Extractor, Out, l2

LABELS = [
    "inwestycje i kryptowaluty", "zdrowie, leki i suplementy", "wygrana, loteria lub nagroda",
    "dopłaty i pomoc od rządu lub banku", "polityka", "zakupy i promocje", "randki i związki",
]
TEMPLATE = "Ten tekst dotyczy: {}."


class Embed(Extractor):
    use_case = "text_embedding"
    family = "text"
    modality = "text"
    primary_field = "text.embedding"
    license = "MIT"
    consumes_derived_text = True

    def __init__(self, hf_id, prefix, notes):
        self.hf_id, self.prefix, self.notes = hf_id, prefix, notes
        self.name = hf_id.split("/")[-1]
        self.version = f"hf:{hf_id}"

    def load(self, threads):
        from sentence_transformers import SentenceTransformer
        self.m = SentenceTransformer(self.hf_id, device="cpu")

    def extract(self, item):
        v = self.m.encode([self.prefix + item.text], normalize_embeddings=True)[0]
        return [Out("text.embedding", l2(v))]


class ZeroShot(Extractor):
    use_case = "text_topic"
    family = "text"
    modality = "text"
    primary_field = "text.topic"
    license = "MIT"
    consumes_derived_text = True

    def __init__(self, hf_id, notes):
        self.hf_id, self.notes = hf_id, notes
        self.name = hf_id.split("/")[-1]
        self.version = f"hf:{hf_id}"

    def load(self, threads):
        from transformers import pipeline
        self.p = pipeline("zero-shot-classification", model=self.hf_id, device=-1)

    def extract(self, item):
        r = self.p(item.text, LABELS, hypothesis_template=TEMPLATE, multi_label=False)
        scores = {l: round(s, 4) for l, s in zip(r["labels"], r["scores"])}
        return [Out("text.topic", {"label": r["labels"][0], "score": round(r["scores"][0], 4),
                                   "scores": scores})]


EXTRACTORS = [
    Embed("intfloat/multilingual-e5-small", "query: ", "118M param, 384d, lekki"),
    Embed("BAAI/bge-m3", "", "568M param, 1024d, najmocniejszy wielojęzyczny"),
    ZeroShot("MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli", "107M param, szybki"),
    ZeroShot("MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7", "278M param, dokładniejszy"),
]
