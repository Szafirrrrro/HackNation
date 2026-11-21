"""Podsumowanie kampanii i zapis wyników do JSON."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .card import Card
from .cluster import ClusterResult
from .scoring import Edge, Scorer


@dataclass
class Campaign:
    id: str
    members: list[int]
    mean_edge: float = 0.0
    first_seen: str = ""
    last_seen: str = ""
    alive: int = 0
    dead: int = 0
    sources: list[str] = field(default_factory=list)
    final_domains: list[str] = field(default_factory=list)
    persons: list[str] = field(default_factory=list)
    shared: list[tuple[str, int]] = field(default_factory=list)  # artefakt -> w ilu reklamach kampanii


def summarize(cards: list[Card], scores: np.ndarray, res: ClusterResult, sc: Scorer) -> tuple[list[Campaign], dict[int, str]]:
    """Kampanie posortowane malejąco wg liczby reklam, numerowane CMP-1, CMP-2, ..."""
    groups: dict[int, list[int]] = {}
    for i, lab in enumerate(res.labels):
        if lab >= 0:
            groups.setdefault(int(lab), []).append(i)
    ordered = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    label_to_id = {lab: f"CMP-{k + 1}" for k, (lab, _) in enumerate(ordered)}

    out = []
    for lab, mem in ordered:
        c = Campaign(label_to_id[lab], mem)
        sub = scores[np.ix_(mem, mem)]
        c.mean_edge = float(sub[np.triu_indices(len(mem), 1)].mean()) if len(mem) > 1 else 0.0
        seen = [cards[i].first_seen for i in mem if cards[i].first_seen]
        last = [cards[i].last_seen for i in mem if cards[i].last_seen]
        c.first_seen, c.last_seen = (min(seen) if seen else ""), (max(last) if last else "")
        c.alive = sum(cards[i].status == "alive" for i in mem)
        c.dead = sum(cards[i].status == "dead" for i in mem)
        c.sources = sorted({cards[i].source for i in mem if cards[i].source})
        c.final_domains = sorted({cards[i].final_domain for i in mem if cards[i].final_domain})
        c.persons = sorted({f.person for i in mem for f in cards[i].faces if f.person})
        cnt = Counter(a.key for i in mem for a in cards[i].artifacts if sc.rarity(sc.df(a.key)) > 0)
        c.shared = [(k, v) for k, v in cnt.most_common() if v >= 2]
        out.append(c)
    return out, label_to_id


def _r(x: float, nd: int = 3) -> float:
    return round(float(x), nd)


def edge_json(e: Edge, cards: list[Card]) -> dict:
    return {"a": cards[e.a].id, "b": cards[e.b].id, "score": _r(e.score),
            "reasons": [{"kind": r.kind, "hard": r.hard, "strength": _r(r.strength), "detail": r.detail}
                        for r in e.reasons]}


def write_json(out_dir: str, cards: list[Card], edges: list[Edge], res: ClusterResult,
               camps: list[Campaign]) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "edges.json").write_text(
        json.dumps([edge_json(e, cards) for e in edges], ensure_ascii=False, indent=2), encoding="utf-8")
    payload = {
        "campaigns": [{
            "campaign": c.id, "size": len(c.members), "mean_edge_score": _r(c.mean_edge),
            "first_seen": c.first_seen, "last_seen": c.last_seen, "alive": c.alive, "dead": c.dead,
            "sources": c.sources, "final_domains": c.final_domains, "persons": c.persons,
            "shared_artifacts": [{"artifact": k, "ads": v} for k, v in c.shared],
            "members": [{"ad_id": cards[i].id, "strength": _r(res.strength[i], 2)} for i in c.members],
        } for c in camps],
        "unassigned": [cards[i].id for i, lab in enumerate(res.labels) if lab < 0],
        "clustering_backend": res.backend,
    }
    (out / "campaigns.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
