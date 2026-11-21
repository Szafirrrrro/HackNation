"""Odczyt cech z out/features/<dataset_id>/ (tylko json + numpy).

    from features_lib import FeatureStore
    fs = FeatureStore("out/features/nask-hacknation-2026")
    fs.methods()                                   # co jest dostępne
    fs.rows(field="ocr.text")                      # wiersze Feature
    X, meta = fs.vectors("face/insightface-buffalo_l@...", "face.embedding")
    ids, S, best = fs.ad_similarity(method_version, "image.embedding")   # cosine ad x ad
    hamming_hex(a, b)                              # odległość pHash/dHash
"""
from __future__ import annotations

import json
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
        self._rows = []
        for f in sorted((self.root / "features").glob("*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                self._rows.append(json.loads(line))
        self._vec_cache: dict[str, np.ndarray] = {}

    def runs(self) -> list[dict]:
        return [json.loads(p.read_text(encoding="utf-8"))
                for p in sorted((self.root / "runs").glob("*.json"))]

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
        if not ad_ids:
            return [], np.zeros((0, 0)), {}
        idx = {a: i for i, a in enumerate(ad_ids)}
        C = X @ X.T
        n = len(ad_ids)
        S = np.full((n, n), -1.0, dtype=np.float32)
        best = {}
        owner = np.array([idx[r["ad_id"]] for r in rows])
        for p in range(len(rows)):
            for q in range(len(rows)):
                i, j = owner[p], owner[q]
                if i != j and C[p, q] > S[i, j]:
                    S[i, j] = C[p, q]
                    best[(i, j)] = (rows[p], rows[q])
        np.fill_diagonal(S, 1.0)
        return ad_ids, S, best
