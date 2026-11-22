"""Odczyt cech z out/features/<dataset_id>/ (tylko json + numpy).

    from features_lib import FeatureStore
    fs = FeatureStore("out/features/nask-hacknation-2026")
    fs.methods()                                   # co jest dostępne
    fs.stale_runs()                                # przebiegi policzone na innej wersji korpusu
    fs.rows(field="ocr.text")                      # wiersze Feature (tylko reklamy z ads.jsonl)
    X, meta = fs.vectors(method_version, "face.embedding")
    ids, S, best = fs.ad_similarity(method_version, "image.embedding")   # cosine ad x ad
    hamming_hex(a, b)                              # odległość pHash/dHash
    fingerprint_match(fs, ad_a, ad_b)              # Chromaprint: (similarity, offset, overlap)
"""
from __future__ import annotations

import json
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np


def hamming_hex(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


class FeatureStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.ads = {}
        if (self.root / "ads.jsonl").exists():
            for line in (self.root / "ads.jsonl").read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                self.ads[r["ad_id"]] = r
        cj = self.root / "corpus.json"
        self.corpus = json.loads(cj.read_text(encoding="utf-8")) if cj.exists() else {}
        self.fingerprint = self.corpus.get("fingerprint")
        self._rows, self.dropped_rows = [], 0
        for f in sorted((self.root / "features").glob("*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                if self.ads and r["ad_id"] not in self.ads:  # reklama spoza bieżącego korpusu
                    self.dropped_rows += 1
                    continue
                self._rows.append(r)
        stale = self.stale_runs()
        if stale:
            warnings.warn(f"przebiegi z innej wersji korpusu: {[r['slug'] for r in stale]}")
        self._vec_cache: dict[str, np.ndarray] = {}

    def runs(self) -> list[dict]:
        return [json.loads(p.read_text(encoding="utf-8"))
                for p in sorted((self.root / "runs").glob("*.json"))]

    def stale_runs(self) -> list[dict]:
        return [r for r in self.runs()
                if self.fingerprint and r.get("corpus_fingerprint") not in (None, self.fingerprint)]

    def rows(self, field=None, method=None, status="ok", ad_id=None, use_case=None):
        return [r for r in self._rows
                if (field is None or r["field"] == field)
                and (method is None or r["method_version"] == method)
                and (status is None or r["status"] == status)
                and (ad_id is None or r["ad_id"] == ad_id)
                and (use_case is None or r["use_case"] == use_case)]

    def methods(self) -> list[dict]:
        agg = defaultdict(lambda: {"ok": 0, "unavailable": 0, "vector": False})
        for r in self._rows:
            k = (r["method_version"], r["field"], r["family"], r["use_case"])
            agg[k][r["status"]] += 1
            if isinstance(r["value"], dict) and "vector" in r["value"]:
                agg[k]["vector"] = True
        return [{"method_version": m, "field": f, "family": fam, "use_case": uc, **v}
                for (m, f, fam, uc), v in sorted(agg.items())]

    def vectors(self, method_version: str, field: str):
        """Macierz [n, d] (wiersze L2-znormalizowane) + wiersze Feature w tej samej kolejności."""
        rows = [r for r in self.rows(field=field, method=method_version)
                if isinstance(r["value"], dict) and "vector" in r["value"]]
        if not rows:
            return np.zeros((0, 0), np.float32), []
        path = rows[0]["value"]["vector"]
        if path not in self._vec_cache:
            self._vec_cache[path] = np.load(self.root / path)
        M = self._vec_cache[path]
        X = M[[r["value"]["row"] for r in rows]].astype(np.float32)
        X /= np.maximum(np.linalg.norm(X, axis=1, keepdims=True), 1e-12)
        return X, rows

    def ad_similarity(self, method_version: str, field: str):
        """Podobieństwo reklam = max cosine po wszystkich parach wektorów dwóch reklam
        (np. wiele twarzy, tekst + OCR). Zwraca (ad_ids, S[n,n], best) gdzie
        best[(i,j)] = (wiersz_lewy, wiersz_prawy) - do wyjaśnienia, co się dopasowało."""
        X, rows = self.vectors(method_version, field)
        ad_ids = sorted({r["ad_id"] for r in rows})
        n = len(ad_ids)
        if not n:
            return [], np.zeros((0, 0)), {}
        idx = {a: i for i, a in enumerate(ad_ids)}
        owner = np.array([idx[r["ad_id"]] for r in rows])
        groups = [np.flatnonzero(owner == i) for i in range(n)]
        C = X @ X.T
        S = np.eye(n, dtype=np.float32)
        best = {}
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                block = C[np.ix_(groups[i], groups[j])]
                p, q = np.unravel_index(int(block.argmax()), block.shape)
                S[i, j] = block[p, q]
                best[(i, j)] = (rows[groups[i][p]], rows[groups[j][q]])
        return ad_ids, S, best


# ------------------------------------------------------ porównania bez modelu --
TFIDF_METHOD = "text/tfidf-char_wb-3-5@sklearn"


def tfidf_similarity(texts: dict[str, str], ngram_range=(3, 5)):
    """Domyślne podobieństwo tekstu (decyzja 2026-11-21): TF-IDF znakowy char_wb 3-5, cosine.
    `texts`: klucz (np. ad_id lub (ad_id, source_field)) -> tekst. Słownik i IDF dopasowujemy do
    podanego zbioru referencyjnego - zapytanie porównuj transformacją tego samego wektoryzatora
    (zwracany `vec`), żeby nie zmieniało statystyk referencji (kontrakt: „Zapytanie nie zmienia
    słownika tekstu”). Wymaga scikit-learn."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    keys = [k for k, t in texts.items() if (t or "").strip()]
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=ngram_range, lowercase=True)
    T = vec.fit_transform([texts[k] for k in keys])
    return keys, (T @ T.T).toarray(), vec


# ok. 8 subodcisków/s: min_overlap 40 ~ 5 s. Wspólny fragment musi też obejmować min_fraction
# krótszego nagrania - inaczej maksimum po przesunięciach wygrywają krótkie fragmenty na brzegach.
CHROMAPRINT_MATCH = {"min_overlap": 40, "min_fraction": 0.5}


def _as_uint32(x) -> np.ndarray:
    """Odcisk jako uint32: przyjmuje int32 z arrays/ albo liczby bez znaku z JSON fpcalc."""
    return (np.asarray(x, dtype=np.int64).reshape(-1) & 0xFFFFFFFF).astype(np.uint32)


def chromaprint_similarity(a, b, min_overlap: int = CHROMAPRINT_MATCH["min_overlap"],
                           min_fraction: float = CHROMAPRINT_MATCH["min_fraction"]):
    """Zgodność dwóch odcisków Chromaprint (audio.fingerprint).

    Szuka przesunięcia czasowego o największym odsetku zgodnych bitów (wykrywa też fragment
    zawarty w dłuższym nagraniu). Wspólny fragment musi mieć co najmniej
    max(min_overlap, min_fraction * krótszy) subodcisków (nie więcej niż krótszy odcisk).
    Zwraca (similarity 0..1, offset w subodciskach, overlap) albo None, gdy któryś odcisk jest
    pusty. Losowe bity dają ~0,5; niepowiązane prawdziwe nagrania mają zwykle wyższe tło
    (syntetyczna kontrola: 0,6-0,72). Progi decyzji ustala silnik grafu, nie ta funkcja.
    """
    a, b = _as_uint32(a), _as_uint32(b)
    if a.size == 0 or b.size == 0:
        return None
    short = min(a.size, b.size)
    need = min(short, max(min_overlap, int(np.ceil(min_fraction * short))))
    best = (-1.0, 0, 0)
    for off in range(-(b.size - need), a.size - need + 1):   # a[i] ~ b[i - off]
        i0, i1 = max(0, off), min(a.size, b.size + off)
        x = np.bitwise_xor(a[i0:i1], b[i0 - off:i1 - off])
        sim = 1.0 - np.unpackbits(x.view(np.uint8)).sum() / (32.0 * x.size)
        if sim > best[0]:
            best = (float(sim), off, int(x.size))
    return best


def fingerprint_match(fs: "FeatureStore", ad_a: str, ad_b: str, method: str | None = None):
    """chromaprint_similarity między reklamami (pole audio.fingerprint). None, gdy brak odcisku."""
    fps = audio_fingerprints(fs, method, ads=(ad_a, ad_b))
    if len(fps) < 2:
        return None
    return chromaprint_similarity(fps[ad_a], fps[ad_b])


def audio_fingerprints(fs: "FeatureStore", method: str | None = None, ads=None) -> dict:
    """{ad_id: odcisk int32} dla wierszy audio.fingerprint (jedno otwarcie każdego pliku npz)."""
    rows = [r for r in fs.rows(field="audio.fingerprint", method=method) if ads is None or r["ad_id"] in ads]
    files = {p: np.load(fs.root / p) for p in {r["value"]["array"] for r in rows}}
    return {r["ad_id"]: files[r["value"]["array"]][r["value"]["key"]] for r in rows}
