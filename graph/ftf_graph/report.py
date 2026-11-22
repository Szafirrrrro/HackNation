"""Podsumowanie kampanii i zapis wyników do JSON."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .card import Card
from .cluster import ClusterResult
from .scoring import ENGINE_VERSION, Edge, Reason, Scorer


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
    for members in groups.values():
        members.sort(key=lambda i: cards[i].id)
    ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), [cards[i].id for i in kv[1]]))
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
        cnt = Counter(a.key for i in mem for a in cards[i].artifacts if sc.rarity_of(a.key) > 0)
        c.shared = sorted(((k, v) for k, v in cnt.items() if v >= 2), key=lambda item: (-item[1], item[0]))
        out.append(c)
    return out, label_to_id


def _r(x: float, nd: int = 3) -> float:
    return round(float(x), nd)


def edge_json(e: Edge, cards: list[Card]) -> dict:
    return {"a": cards[e.a].id, "b": cards[e.b].id, "score": _r(e.score),
            "has_hard_evidence": e.has_hard, "campaign_score": _r(e.campaign_score),
            "reasons": [_reason_json(r) for r in e.reasons],
            "campaign_reasons": [_reason_json(r) for r in e.campaign_reasons],
            "observations": [_reason_json(r) for r in e.observations]}


def _reason_json(reason: Reason) -> dict:
    return {**asdict(reason), "strength": _r(reason.strength)}


def write_json(out_dir: str, cards: list[Card], edges: list[Edge], res: ClusterResult,
               camps: list[Campaign], *, config: dict | None = None, fingerprint: str = "",
               data_fingerprint: str = "", warnings: list[str] | None = None) -> None:
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
        "engine_version": ENGINE_VERSION,
        "config": config or {},
        "reference_fingerprint": fingerprint,
        "data_fingerprint": data_fingerprint,
        "warnings": warnings or [],
    }
    (out / "campaigns.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
