"""ftf-graph — silnik łączenia reklam w kampanie (Follow the Fake, HackNation).

    python -m ftf_graph data/sample_cards.jsonl --query B03
    python -m ftf_graph data/sample_cards.jsonl --neo4j bolt://localhost:7687

Wejście:  jedna karta reklamy (JSON) na linię.
Wyjście:  OUT/edges.json, OUT/campaigns.json, raport na stdout, opcjonalnie zapis do Neo4j.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from .card import parse_card, read_cards
from .matching import build_reference
from .report import edge_json, write_json
from .scoring import Config


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ftf_graph", description="Łączenie reklam w kampanie")
    p.add_argument("cards", help="plik JSONL z kartami reklam")
    p.add_argument("--out", default="out", help="katalog na wyniki JSON (domyślnie: out)")
    p.add_argument("--min-cluster", type=int, default=3, help="min. liczba reklam w kampanii (3)")
    p.add_argument("--min-samples", type=int, default=2, help="dawna opcja klastrowania, bez wpływu na wynik")
    p.add_argument("--min-edge", type=float, default=0.25, help="min. score krawędzi zapisywanej do grafu (0.25)")
    p.add_argument("--min-campaign", type=float, default=0.65, help="min. score każdej pary w kampanii (0.65)")
    query_arg = p.add_mutually_exclusive_group()
    query_arg.add_argument("--query", help="ID karty wyłączonej z referencji i użytej jako zapytanie")
    query_arg.add_argument("--query-file", type=Path, help="osobny plik JSON z kartą zapytania")
    p.add_argument("--neo4j", metavar="URI", help="np. bolt://localhost:7687 — zapisz graf do Neo4j")
    p.add_argument("--neo4j-user", default=os.getenv("NEO4J_USER", "neo4j"))
    p.add_argument("--neo4j-password", default=os.getenv("NEO4J_PASSWORD", ""))
    p.add_argument("--wipe", action="store_true", help="wyczyść bazę Neo4j przed zapisem (demo)")
    a = p.parse_args(argv)

    cards, errors, duplicates = read_cards(a.cards)
    for record in errors + duplicates:
        first = f"; pierwszy zapis w linii {record['first_line']}" if "first_line" in record else ""
        print(f"Pomijam linię {record['line']} ({record.get('error') or record.get('reason')}{first})", file=sys.stderr)
    print(f"Wczytano {len(cards)} kart reklam")
    if not cards:
        return 1

    query = None
    if a.query:
        query = next((c for c in cards if c.id == a.query), None)
        if query is None:
            print(f"Brak reklamy {a.query}", file=sys.stderr)
            return 1
        cards = [c for c in cards if c.id != a.query]
    if a.query_file:
        try:
            row = json.loads(a.query_file.read_text(encoding="utf-8-sig"))
            query = parse_card(row) if isinstance(row, dict) else None
            if query is None or not query.id.strip():
                raise ValueError("brak pola ad_id karty zapytania")
        except (OSError, ValueError) as exc:
            p.error(f"Nie można wczytać karty zapytania ({exc})")

    cfg = Config(min_edge=a.min_edge, min_campaign=a.min_campaign)
    try:
        reference = build_reference(cards, cfg, min_cluster_size=a.min_cluster, min_samples=a.min_samples)
    except ValueError as exc:
        p.error(str(exc))
    sc, res, camps = reference.scorer, reference.clusters, reference.campaigns
    edges, label_to_id = reference.edges, reference.label_to_id
    write_json(a.out, cards, edges, res, camps, config=reference.config, fingerprint=reference.fingerprint,
               data_fingerprint=reference.data_fingerprint,
               warnings=sc.warnings + [f"{c.id}: {message}" for c in cards for message in c.warnings])

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

    if query is not None:
        result = reference.match(query)
        assignment = f" ({result.campaign_id}, siła {result.strength:.2f})" if result.campaign_id else ""
        print(f"\n### {query.id} -> {result.status}{assignment}")
        if result.exact_copies:
            print("Identyczne pliki obrazu:", ", ".join(cards[i].id for i in result.exact_copies))
        if result.similar_materials:
            print("Podobne materiały:", ", ".join(cards[i].id for i in result.similar_materials))
        for e in result.edges[:5]:
            print(f"  ~ {cards[e.b].id}  podobieństwo {e.score:.2f}, siła kampanii {e.campaign_score:.2f}")
            for r in e.reasons:
                print(f"      {'[TWARDY]' if r.hard else '[MIĘKKI]'} +{r.strength:.2f}  {r.detail}")
        if result.missing:
            print("Braki:", ", ".join(result.missing))
        for warning in result.warnings:
            print(warning)
        query_payload = asdict(result)
        for key in ("edges", "supporting_edges"):
            query_payload[key] = [edge_json(edge, cards + [query]) for edge in getattr(result, key)]
        for key in ("exact_copies", "similar_materials"):
            query_payload[key] = [cards[i].id for i in getattr(result, key)]
        (Path(a.out) / "query.json").write_text(json.dumps(query_payload, ensure_ascii=False, indent=2), encoding="utf-8")

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
