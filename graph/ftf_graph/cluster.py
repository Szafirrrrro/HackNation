"""Deterministic complete-link clustering on the campaign scores."""
from __future__ import annotations

from dataclasses import dataclass
from heapq import heapify, heappop, heappush
from itertools import combinations

import numpy as np

BACKEND = "complete-link/v1"


@dataclass
class ClusterResult:
    labels: np.ndarray    # -1 = bez kampanii
    strength: np.ndarray  # najsłabsze powiązanie z innym członkiem kampanii
    backend: str


def cluster(scores: np.ndarray, min_cluster_size: int = 3, min_samples: int = 2,
            min_link: float = 0.25, *, ids: list[str] | None = None) -> ClusterResult:
    """Merge the strongest eligible groups. min_samples is a legacy argument."""
    if min_cluster_size < 2 or not 0 <= min_link <= 1:
        raise ValueError("Kampania wymaga co najmniej dwóch kart i progu z przedziału 0–1.")
    order = sorted(range(len(scores)), key=ids.__getitem__) if ids is not None else list(range(len(scores)))
    labels = np.full(len(order), -1)
    strength = np.zeros(len(order))
    if len(order) < min_cluster_size:
        return ClusterResult(labels, strength, BACKEND)

    # Keys of merged groups stay equal to the smallest member's rank. A
    # generation counter invalidates a previous heap entry for the same key.
    groups = {i: [member] for i, member in enumerate(order)}
    generation = [0] * len(order)
    links = {i: {} for i in groups}
    queue = []
    for (i, a), (j, b) in combinations(enumerate(order), 2):
        similarity = float(scores[a, b])
        if similarity > 0 and similarity >= min_link:
            links[i][j] = links[j][i] = similarity
            queue.append((-similarity, i, j, 0, 0))
    heapify(queue)

    while queue:
        _, i, j, old_i, old_j = heappop(queue)
        if generation[i] != old_i or generation[j] != old_j:
            continue
        common = links[i].keys() & links[j].keys()
        merged = {k: min(links[i][k], links[j][k]) for k in common}
        for g in (i, j):
            for k in links[g]:
                links[k].pop(g, None)
            generation[g] += 1
        links[i] = merged
        del links[j]
        groups[i].extend(groups.pop(j))
        for k, score in merged.items():
            links[k][i] = score
            a, b = sorted((i, k))
            heappush(queue, (-score, a, b, generation[a], generation[b]))

    number = 0
    for members in groups.values():
        if len(members) >= min_cluster_size:
            labels[members] = number
            sub = scores[np.ix_(members, members)].astype(float)
            np.fill_diagonal(sub, np.inf)
            strength[members] = sub.min(axis=1)
            number += 1
    return ClusterResult(labels, strength, BACKEND)
