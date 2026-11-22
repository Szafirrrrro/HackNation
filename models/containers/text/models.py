"""Tekst reklam (pole `text` + ocr.text/asr.text z wcześniejszych ekstrakcji):
(1) embeddingi narracji -> podobieństwo/klastrowanie, (2) zero-shot tematyka (NLI, PL)."""
from extractor import Extractor, Out, l2

LABELS = [
    "inwestycje i kryptowaluty", "zdrowie, leki i suplementy", "wygrana, loteria lub nagroda",
    "dopłaty i pomoc od rządu lub banku", "polityka", "zakupy i promocje", "randki i związki",
]
TEMPLATE = "Ten tekst dotyczy: {}."


class Embed(Extractor):
    # Tekst porównuje TF-IDF (features_lib); embedding zostaje jako wejście grafu (docs/DATA_CONTRACT.md)
    use_case = "text_embedding"
    family = "text"
    modality = "text"
    primary_field = "text.embedding"
    license = "MIT"
    consumes_derived_text = True

    def __init__(self, hf_id, prefix, notes, stage, decision):
        self.hf_id, self.prefix, self.notes = hf_id, prefix, notes
        self.stage, self.decision = stage, decision
        self.name = hf_id.split("/")[-1]
        self.version = f"hf:{hf_id}"
        self.hf_repo = hf_id
        self.params = {"prefix": prefix, "normalize": True}

    def load(self, threads):
        from sentence_transformers import SentenceTransformer
        self.m = SentenceTransformer(self.hf_id, device="cpu")

    def extract(self, item):
        v = self.m.encode([self.prefix + item.text], normalize_embeddings=True)[0]
        return [Out("text.embedding", l2(v))]


class ZeroShot(Extractor):
    stage = "on_demand"
    decision = ("Poza profilem domyślnym: zestaw zwraca jedną z zadanych kategorii także dla tekstu "
                "spoza listy; dwie różne kampanie mogą reklamować leki.")
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
        self.hf_repo = hf_id
        self.params = {"labels": LABELS, "template": TEMPLATE, "multi_label": False}

    def load(self, threads):
        from transformers import pipeline
        self.p = pipeline("zero-shot-classification", model=self.hf_id, device=-1)

    def extract(self, item):
        # wszystkie kategorie w jednej partii: te same etykiety, ok. 30% krócej niż po jednej (pomiar 2026-11-22)
        r = self.p(item.text, LABELS, hypothesis_template=TEMPLATE, multi_label=False,
                   batch_size=len(LABELS))
        scores = {l: round(s, 4) for l, s in zip(r["labels"], r["scores"])}
        return [Out("text.topic", {"label": r["labels"][0], "score": round(r["scores"][0], 4),
                                   "scores": scores})]


EXTRACTORS = [
    Embed("intfloat/multilingual-e5-small", "query: ", "118M param, 384d, lekki", "on_demand",
          "Poza wyborem benchmarku: tekst porównuje TF-IDF char_wb 3-5 (features_lib). Zostaje, bo "
          "text.embedding jest wejściem grafu (docs/DATA_CONTRACT.md); usunięcie wymaga zgody Pary C."),
    ZeroShot("MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7", "278M param"),
]
