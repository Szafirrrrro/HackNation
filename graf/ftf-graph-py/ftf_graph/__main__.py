"""ftf-graph — silnik łączenia reklam w kampanie (Follow the Fake, HackNation).

    python -m ftf_graph data/sample_cards.jsonl --query B03
    python -m ftf_graph data/sample_cards.jsonl --neo4j bolt://localhost:7687 --neo4j-password hackathon123

Wejście:  jedna karta reklamy (JSON) na linię.
Wyjście:  OUT/edges.json, OUT/campaigns.json, raport na stdout, opcjonalnie zapis do Neo4j.
"""
from __future__ import annotations

import argparse
import os
import sys

from .card import load_cards
from .cluster import cluster
from .report import summarize, write_json
from .scoring import Config, Scorer


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ftf_graph", description="Łączenie reklam w kampanie")
    p.add_argument("cards", help="plik JSONL z kartami reklam")
    p.add_argument("--out", default="out", help="katalog na wyniki JSON (domyślnie: out)")
    p.add_argument("--min-cluster", type=int, default=3, help="min. liczba reklam w kampanii (3)")
    p.add_argument("--min-samples", type=int, default=2, help="HDBSCAN min_samples (2)")
    p.add_argument("--min-edge", type=float, default=0.25, help="min. score krawędzi zapisywanej do grafu (0.25)")
    p.add_argument("--query", help="ID reklamy do wyjaśnienia: do której kampanii pasuje i dlaczego")
    p.add_argument("--neo4j", metavar="URI", help="np. bolt://localhost:7687 — zapisz graf do Neo4j")
    p.add_argument("--neo4j-user", default=os.getenv("NEO4J_USER", "neo4j"))
    p.add_argument("--neo4j-password", default=os.getenv("NEO4J_PASSWORD", ""))
    p.add_argument("--wipe", action="store_true", help="wyczyść bazę Neo4j przed zapisem (demo)")
    a = p.parse_args(argv)

    cards = list(load_cards(a.cards))
    print(f"Wczytano {len(cards)} kart reklam")
    if not cards:
        return 1

    sc = Scorer(cards, Config(min_edge=a.min_edge))
    scores, edges = sc.score_all()
    res = cluster(scores, a.min_cluster, a.min_samples)
    camps, label_to_id = summarize(cards, scores, res, sc)
    write_json(a.out, cards, edges, res, camps)

    print(f"Krawędzie SIMILAR (score >= {a.min_edge}): {len(edges)}")
    print(f"Kampanie: {len(camps)}   [klastrowanie: {res.backend}]\n")
    for c in camps:
        print(f"== {c.id}  ({len(c.members)} reklam, {c.alive} aktywnych / {c.dead} martwych, "
              f"{len(c.final_domains)} domen docelowych)")
        print(f"   okres: {c.first_seen} -> {c.last_seen}   śr. siła powiązań: {c.mean_edge:.2f}")
        print("   reklamy:", " ".join(cards[i].id for i in c.members))
        if c.persons:
            print("   wizerunek:", " ".join(c.persons))
        print("   wspólne ślady:", " ".join(f"[{k} ×{v}]" for k, v in c.shared[:5]), "\n")
    print("Bez kampanii:", " ".join(cards[i].id for i, lab in enumerate(res.labels) if lab < 0))

    if a.query:
        idx = {c.id: i for i, c in enumerate(cards)}
        if a.query not in idx:
            print(f"brak reklamy {a.query}", file=sys.stderr)
            return 1
        qi = idx[a.query]
        lab = int(res.labels[qi])
        print(f"\n### {a.query} -> {label_to_id.get(lab, 'brak kampanii')}")
        for e in [e for e in edges if qi in (e.a, e.b)][:5]:
            other = cards[e.b if e.a == qi else e.a].id
            print(f"  ~ {other}  score {e.score:.2f}")
            for r in e.reasons:
                print(f"      {'[TWARDY]' if r.hard else '[MIĘKKI]'} +{r.strength:.2f}  {r.detail}")

    if a.neo4j:
        from .neo4j_store import Neo4jStore

        with Neo4jStore(a.neo4j, a.neo4j_user, a.neo4j_password) as store:
            if a.wipe:
                store.wipe()
            store.write(cards, edges, res, camps, label_to_id, sc)
        print(f"\nZapisano graf do Neo4j: {a.neo4j}")
    print(f"\nZapisano: {a.out}/edges.json, {a.out}/campaigns.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
