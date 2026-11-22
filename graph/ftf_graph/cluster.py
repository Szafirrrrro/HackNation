"""Klastrowanie reklam w kampanie: HDBSCAN na macierzy odległości d = 1 - score.

Używa pakietu `hdbscan` (scikit-learn-contrib), jeśli jest zainstalowany, w przeciwnym
razie `sklearn.cluster.HDBSCAN` (ta sama metoda, w scikit-learn od wersji 1.3).

Zabezpieczenie "kampania musi mieć dowody": reklamy bez żadnego wspólnego śladu mają odległość 1
do wszystkich. Kilka takich reklam jest od siebie RÓWNO odległych, a HDBSCAN (szczególnie wersja
sklearn) potrafi uznać je za skupisko. Dlatego po klastrowaniu każda reklama musi mieć w swojej
kampanii co najmniej jedną krawędź o score >= min_link; inaczej trafia do szumu. Kampania, która
po tym ma mniej niż min_cluster_size reklam, jest rozwiązywana.

Intuicja HDBSCAN: szukamy "wysp" reklam gęsto połączonych mocnymi krawędziami. Pojedyncza
przypadkowa krawędź (np. tylko wspólna celebrytka) nie skleja dwóch wysp, bo gęstość
między nimi jest dużo mniejsza niż wewnątrz.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class ClusterResult:
    labels: np.ndarray        # -1 = szum, inaczej numer klastra
    strength: np.ndarray      # 0..1 jak "rdzeniowa" jest reklama w klastrze
    backend: str


def cluster(scores: np.ndarray, min_cluster_size: int = 3, min_samples: int = 2,
            min_link: float = 0.25) -> ClusterResult:
    dist = np.clip(1.0 - scores, 0.0, 1.0).astype(np.float64)
    np.fill_diagonal(dist, 0.0)
    if len(dist) < max(2, min_cluster_size):
        return ClusterResult(np.full(len(dist), -1), np.zeros(len(dist)), "none")
    try:
        import hdbscan  # type: ignore

        model = hdbscan.HDBSCAN(metric="precomputed", min_cluster_size=min_cluster_size,
                                min_samples=min_samples)
        backend = f"hdbscan {getattr(hdbscan, '__version__', '')}".strip()
    except ImportError:
        from sklearn.cluster import HDBSCAN

        kw = dict(metric="precomputed", min_cluster_size=min_cluster_size, min_samples=min_samples)
        try:
            model = HDBSCAN(copy=True, **kw)  # nowsze sklearn ostrzegają bez jawnego copy
        except TypeError:
            model = HDBSCAN(**kw)
        backend = "sklearn.cluster.HDBSCAN"
    model.fit(dist)
    labels = model.labels_.astype(int).copy()
    strength = np.asarray(model.probabilities_, dtype=float).copy()

    # kampania musi mieć dowody: każda reklama potrzebuje krawędzi >= min_link do innej reklamy kampanii
    changed = True
    while changed:
        changed = False
        for lab in set(labels[labels >= 0].tolist()):
            mem = np.flatnonzero(labels == lab)
            sub = scores[np.ix_(mem, mem)].copy()
            np.fill_diagonal(sub, 0.0)
            weak = mem[sub.max(axis=1) < min_link] if len(mem) > 1 else mem
            if len(weak):
                labels[weak] = -1
                changed = True
            if (labels == lab).sum() < min_cluster_size:
                labels[labels == lab] = -1
                changed = True
    strength[labels < 0] = 0.0
    return ClusterResult(labels, strength, backend)
