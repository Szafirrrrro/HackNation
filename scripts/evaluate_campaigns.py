"""Evaluate the analyst's frozen reference and a text-only baseline on held-out cards."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
from itertools import combinations
import json
from pathlib import Path
import platform
import sys
from time import perf_counter

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from graph.ftf_graph.card import parse_card
from graph.ftf_graph.cluster import cluster
from graph.ftf_graph.matching import build_reference
from graph.ftf_graph.scoring import Config


@dataclass
class Prediction:
    status: str
    members: list[int]
    ranked_neighbors: list[int]


def raw_text(card):
    return card.ad_text or card.image_text


class TextBaseline:
    """Character TF-IDF fit on reference only. Thresholds fixed before scoring queries."""

    def __init__(self, cards, cfg):
        self.cfg = cfg
        self.cards = cards
        self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5))
        try:
            self.matrix = self.vectorizer.fit_transform([raw_text(card) for card in cards])
        except ValueError as exc:
            if "empty vocabulary" not in str(exc):
                raise
            self.matrix = None
        scores = (self.matrix @ self.matrix.T).toarray() if self.matrix is not None else np.eye(len(cards))
        self.labels = cluster(scores, min_cluster_size=3, min_link=cfg.min_campaign).labels.tolist()
        self.groups = defaultdict(list)
        for i, label in enumerate(self.labels):
            if label >= 0:
                self.groups[label].append(i)

    def match(self, card):
        if not raw_text(card).strip() or self.matrix is None:
            return Prediction("insufficient_evidence", [], [])
        scores = (self.matrix @ self.vectorizer.transform([raw_text(card)]).T).toarray().ravel()
        ranked = [int(i) for i in np.argsort(-scores, kind="stable") if scores[i] >= self.cfg.min_edge]
        qualified = [members for members in self.groups.values()
                     if min(scores[i] for i in members) >= self.cfg.min_campaign]
        if len(qualified) == 1:
            return Prediction("probable_match", qualified[0], ranked)
        return Prediction("review_needed" if ranked else "no_match", [], ranked)


class AnalystEngine:
    def __init__(self, cards, cfg):
        self.ref = build_reference(cards, cfg)
        self.labels = self.ref.clusters.labels.tolist()
        self.members = {c.id: c.members for c in self.ref.campaigns}

    def match(self, card):
        result = self.ref.match(card)
        return Prediction(result.status, self.members.get(result.campaign_id, []),
                          [edge.b for edge in result.edges])


def pair_metrics(predicted, truth):
    tp = fp = fn = 0
    for i, j in combinations(range(len(truth)), 2):
        joined = predicted[i] >= 0 and predicted[i] == predicted[j]
        related = truth[i] == truth[j]
        tp += int(joined and related)
        fp += int(joined and not related)
        fn += int(not joined and related)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None}


def measure(method, cards, queries, truth, answers):
    start = perf_counter()
    model = method(cards, Config())
    build_ms = (perf_counter() - start) * 1000
    decisions, latency = [], []
    counts = defaultdict(Counter)
    correct_status = hits = known = decided = 0
    for query in queries:
        start = perf_counter()
        pred = model.match(query)
        latency.append((perf_counter() - start) * 1000)
        answer = answers[query.id]
        group = answer["group"]
        bucket = "control" if group is None else ("known" if group in truth else "novel")
        # Mixed predicted campaigns cannot receive credit through a majority vote.
        groups = {truth[i] for i in pred.members}
        if pred.status == "probable_match":
            outcome = "correct_assignment" if group is not None and groups == {group} else "wrong_assignment"
        elif pred.status == "no_match":
            outcome = "correct_rejection" if bucket == "novel" else "no_match"
        else:
            outcome = pred.status
        counts[bucket][outcome] += 1
        decided += int(pred.status in {"probable_match", "no_match"})
        correct_status += int(pred.status == answer["expected"] and
                              (pred.status != "probable_match" or outcome == "correct_assignment"))
        if bucket == "known":
            known += 1
            hits += int(any(truth[i] == group for i in pred.ranked_neighbors[:3]))
        decisions.append({"id": query.id, "expected": answer["expected"], "status": pred.status,
                          "outcome": outcome, "members": [cards[i].id for i in pred.members],
                          "top3": [cards[i].id for i in pred.ranked_neighbors[:3]]})
    metadata = ({"reference_fingerprint": model.ref.fingerprint, "configuration": model.ref.config}
                if isinstance(model, AnalystEngine) else {"representation": "char_wb TF-IDF 3-5"})
    return {**metadata, "reference_campaigns": len(set(model.labels) - {-1}),
            "reference_pairs": pair_metrics(model.labels, truth),
            "by_query_type": counts, "correct_decisions": [correct_status, len(queries)],
            "assignment_or_rejection": [decided, len(queries)],
            "hit_at_3_known": [hits, known], "decisions": decisions,
            "build_ms": round(build_ms, 2), "query_p95_ms": round(float(np.percentile(latency, 95)), 2)}


def run(folder):
    files = {name: (folder / name).read_bytes() for name in ("reference.jsonl", "queries.jsonl", "labels.json")}
    def read_cards(name):
        return [parse_card(json.loads(line)) for line in files[name].splitlines() if line.strip()]
    cards = read_cards("reference.jsonl")
    queries = read_cards("queries.jsonl")
    labels = json.loads(files["labels.json"])
    for split, items in (("reference", cards), ("queries", queries)):
        ids = [c.id for c in items]
        if not ids or len(set(ids)) != len(ids) or "" in ids or set(ids) != set(labels[split]):
            raise ValueError(f"IDs or labels inconsistent in {split}")
    if labels["reference"].keys() & labels["queries"].keys():
        raise ValueError("Reference and query IDs overlap")
    truth = [labels["reference"][c.id] for c in cards]
    cfg = Config()
    return {"data": labels["source"], "reference_size": len(cards), "query_size": len(queries),
            "sha256": {name: hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest() for name, data in files.items()},
            "python": platform.python_version(), "platform": platform.platform(), "cpu": platform.machine(),
            "thresholds": {"review": cfg.min_edge, "campaign": cfg.min_campaign, "min_group_size": 3},
            "methods": {name: measure(method, cards, queries, truth, labels["queries"])
                        for name, method in (("tfidf", TextBaseline), ("analyst", AnalystEngine))}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "graph/eval")
    parser.add_argument("--out", type=Path, help="Optional local JSON report")
    args = parser.parse_args()
    report = json.dumps(run(args.data), ensure_ascii=False, indent=2, allow_nan=False)
    if args.out:
        args.out.write_text(report + "\n", encoding="utf8")
    print(report)
