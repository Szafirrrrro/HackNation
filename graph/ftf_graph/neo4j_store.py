"""Zapis grafu do Neo4j przez oficjalny sterownik `neo4j` (paczki UNWIND, idempotentne MERGE).

Model:
  (:Ad)-[:USES {kind}]->(:TrackingID|:Favicon|:IP|:Certificate|:AudioFingerprint|:Transcript|...)
                                                                       ślady twarde = wspólne węzły
  (:Ad)-[:STARTS_AT]->(:Domain)-[:REDIRECTS_TO]->(:Domain)<-[:LANDS_ON]-(:Ad)
  (:Certificate)-[:COVERS]->(:Domain)
  (:Ad)-[:SIMILAR {score, reasons, has_hard_evidence}]-(:Ad)          krawędzie z uzasadnieniem
  (:Ad)-[:IN_CAMPAIGN {strength}]->(:Campaign)

Martwych reklam i domen NIE usuwamy — nowe domeny łączą się ze starymi kampaniami
przez wspólne piksele, favicony, szablony i twarze.
"""
from __future__ import annotations

from collections import defaultdict

from neo4j import GraphDatabase

from .card import SIGNAL_KINDS, Card
from .cluster import ClusterResult
from .report import Campaign
from .scoring import Edge, Scorer

NODE_LABEL = {
    "registrar": "Registrar", "nameserver": "Nameserver", "ip": "IP", "asn": "ASN",
    "cert": "Certificate", "favicon": "Favicon", "tracking_id": "TrackingID", "script": "Script",
    "form_endpoint": "FormEndpoint", "phone": "Phone", "telegram": "Telegram", "crypto": "CryptoAddress",
    "template": "Template", "hidden_text": "HiddenText", "keyword": "Keyword", "person": "Person",
    "audio_fp": "AudioFingerprint", "transcript": "Transcript",
}
DOMAIN_KINDS = {"domain_hop", "domain_final"}  # domeny zapisujemy osobno, jako ścieżkę przekierowań


def _batches(rows: list, size: int = 1000):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


class Neo4jStore:
    def __init__(self, uri: str, user: str, password: str, database: str | None = None):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.database = database

    def close(self) -> None:
        self.driver.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def run(self, query: str, **params) -> None:
        self.driver.execute_query(query, params, database_=self.database)

    def unwind(self, query: str, rows: list) -> None:
        for chunk in _batches(rows):
            self.run(query, rows=chunk)

    # ---------- schemat ----------
    def ensure_schema(self) -> None:
        self.run("CREATE CONSTRAINT ad_id IF NOT EXISTS FOR (n:Ad) REQUIRE n.id IS UNIQUE")
        self.run("CREATE CONSTRAINT campaign_id IF NOT EXISTS FOR (n:Campaign) REQUIRE n.id IS UNIQUE")
        for label in {"Domain", *NODE_LABEL.values()}:
            self.run(f"CREATE CONSTRAINT {label.lower()}_value IF NOT EXISTS "
                     f"FOR (n:{label}) REQUIRE n.value IS UNIQUE")

    def wipe(self) -> None:
        """Czyści CAŁĄ bazę — tylko do powtarzalnych demo."""
        # CALL ... IN TRANSACTIONS działa tylko w transakcji automatycznej (session.run)
        with self.driver.session(database=self.database) as s:
            s.run("MATCH (n) CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS").consume()

    # ---------- zapis ----------
    def write(self, cards: list[Card], edges: list[Edge], res: ClusterResult,
              camps: list[Campaign], label_to_id: dict[int, str], sc: Scorer) -> None:
        self.ensure_schema()

        self.unwind("""
            UNWIND $rows AS r
            MERGE (a:Ad {id: r.id})
            SET a.source = r.source, a.url = r.url, a.fetched_at = r.fetched_at,
                a.first_seen = r.first_seen, a.last_seen = r.last_seen, a.status = r.status,
                a.text = r.text, a.transcript = r.transcript, a.audio_duration_s = r.audio_duration,
                a.trusted_domains = r.trusted, a.signals = r.signals, a.signals_present = r.n_signals""",
            [{"id": c.id, "source": c.source, "url": c.url, "fetched_at": c.fetched_at,
              "first_seen": c.first_seen, "last_seen": c.last_seen, "status": c.status, "text": c.ad_text,
              "transcript": c.audio_transcript, "audio_duration": c.audio_duration,
              "trusted": c.trusted_hits, "signals": c.signals(), "n_signals": f"{len(c.signals())}/{SIGNAL_KINDS}"}
             for c in cards])

        # artefakty: etykiety nie mogą być parametrem Cypher, więc jedna paczka na etykietę (z białej listy)
        per_label: dict[str, list[dict]] = defaultdict(list)
        for c in cards:
            for a in c.artifacts:
                if a.kind in DOMAIN_KINDS or a.kind not in NODE_LABEL:
                    continue
                df = sc.df(a.key)
                per_label[NODE_LABEL[a.kind]].append(
                    {"ad": c.id, "value": a.value, "kind": a.kind, "ads": df, "rarity": round(sc.rarity_of(a.key), 3)})
        for label, rows in per_label.items():
            self.unwind(f"""
                UNWIND $rows AS r
                MATCH (a:Ad {{id: r.ad}})
                MERGE (x:{label} {{value: r.value}})
                SET x.ads = r.ads, x.rarity = r.rarity
                MERGE (a)-[:USES {{kind: r.kind}}]->(x)""", rows)

        # łańcuch przekierowań jako ścieżka domen
        starts, hops, lands, covers = [], [], [], []
        for c in cards:
            # zaufane domeny (youtube.com...) wycinamy ze ścieżki — nie tworzą węzłów Domain
            ch = [d for d in c.redirect_chain if d not in c.trusted_hits]
            if ch:
                starts.append({"ad": c.id, "d": ch[0]})
                hops += [{"a": ch[k], "b": ch[k + 1], "hop": k + 1} for k in range(len(ch) - 1)]
            if c.final_domain and c.final_domain not in c.trusted_hits:
                lands.append({"ad": c.id, "d": c.final_domain})
            if c.cert_id:
                covers += [{"cert": c.cert_id, "d": d} for d in c.cert_san if d not in c.trusted_hits]
        self.unwind("UNWIND $rows AS r MATCH (a:Ad {id: r.ad}) MERGE (d:Domain {value: r.d}) "
                    "MERGE (a)-[:STARTS_AT]->(d)", starts)
        self.unwind("UNWIND $rows AS r MERGE (x:Domain {value: r.a}) MERGE (y:Domain {value: r.b}) "
                    "MERGE (x)-[t:REDIRECTS_TO]->(y) SET t.hop = r.hop", hops)
        self.unwind("UNWIND $rows AS r MATCH (a:Ad {id: r.ad}) MERGE (d:Domain {value: r.d}) "
                    "MERGE (a)-[:LANDS_ON]->(d)", lands)
        self.unwind("UNWIND $rows AS r MERGE (x:Certificate {value: r.cert}) MERGE (d:Domain {value: r.d}) "
                    "MERGE (x)-[:COVERS]->(d)", covers)

        # krawędzie podobieństwa z uzasadnieniem (lista tekstów — czytelna w Neo4j Browser)
        self.unwind("""
            UNWIND $rows AS r
            MATCH (a:Ad {id: r.a}), (b:Ad {id: r.b})
            MERGE (a)-[s:SIMILAR]-(b)
            SET s.score = r.score, s.has_hard_evidence = r.hard, s.reasons = r.reasons""",
            [{"a": cards[e.a].id, "b": cards[e.b].id, "score": round(e.score, 3), "hard": e.has_hard,
              "reasons": [f"{'[TWARDY]' if r.hard else '[MIĘKKI]'} +{r.strength:.2f} {r.detail}" for r in e.reasons]}
             for e in edges])

        # kampanie (stare przypisania zastępujemy, bo numeracja to wynik bieżącego klastrowania)
        self.run("MATCH (:Ad)-[r:IN_CAMPAIGN]->() DELETE r")
        self.unwind("""
            UNWIND $rows AS r
            MERGE (k:Campaign {id: r.id})
            SET k.size = r.size, k.mean_edge = r.mean_edge, k.first_seen = r.first_seen, k.last_seen = r.last_seen""",
            [{"id": c.id, "size": len(c.members), "mean_edge": round(c.mean_edge, 3),
              "first_seen": c.first_seen, "last_seen": c.last_seen} for c in camps])
        self.unwind("""
            UNWIND $rows AS r
            MATCH (a:Ad {id: r.ad}), (k:Campaign {id: r.cmp})
            MERGE (a)-[m:IN_CAMPAIGN]->(k) SET m.strength = r.strength""",
            [{"ad": cards[i].id, "cmp": label_to_id[int(lab)], "strength": round(float(res.strength[i]), 2)}
             for i, lab in enumerate(res.labels) if lab >= 0])
        # kampanie bez reklam po przeliczeniu to wyniki poprzedniego klastrowania — usuwamy tylko je
        self.run("MATCH (k:Campaign) WHERE NOT (k)<-[:IN_CAMPAIGN]-() DETACH DELETE k")
