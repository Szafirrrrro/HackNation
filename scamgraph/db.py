"""Opcjonalny zapis kart i przebiegów silnika do PostgreSQL (docs/BAZA_DANYCH.md).

Włącza go zmienna DATABASE_URL, np. postgresql://scamgraph:haslo@localhost:5432/scamgraph.
Bez niej pipeline działa wyłącznie na plikach, jak dotąd. Pliki JSONL i .campaigns.json
pozostają źródłem dla ewaluacji; baza dostaje dokładnie te same treści.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "db" / "schema.sql"
SCHEMA_VERSION = 4
ADAPTER_VERSION = "graph-feed/5"
_schema_ready: set[str] = set()


class Stale(Exception):
    """Nowszy eksport lub raport wyprzedził ten zapis; pomijamy go bez błędu."""


def enabled() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256(text: str | bytes) -> str:
    return hashlib.sha256(text.encode() if isinstance(text, str) else text).hexdigest()


def connect():
    """Połączenie z limitami czasu, żeby niedziałająca baza nie zawiesiła wątku grafu.
    Wartości z DATABASE_URL (connect_timeout, options) mają pierwszeństwo."""
    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    url = os.environ["DATABASE_URL"]
    params = conninfo_to_dict(url)
    params.setdefault("connect_timeout", "3")
    # Zerwana sieć kończy połączenie po ok. 30 s; zamrożonego serwera to nie obejmuje (BAZA_DANYCH.md).
    params.setdefault("keepalives", "1")
    params.setdefault("keepalives_idle", "10")
    params.setdefault("keepalives_interval", "5")
    params.setdefault("keepalives_count", "3")
    params.setdefault("tcp_user_timeout", "30000")
    options = params.get("options") or ""
    if "statement_timeout" not in options:
        options += " -c statement_timeout=30000"
    if "lock_timeout" not in options:
        options += " -c lock_timeout=5000"
    params["options"] = options.strip()
    conn = psycopg.connect(**params, autocommit=True)  # transakcje jawnie przez conn.transaction()
    try:
        if url not in _schema_ready:
            ensure_schema(conn)
            _schema_ready.add(url)
    except BaseException:
        conn.close()
        raise
    return conn


def ensure_schema(conn) -> None:
    # Schemat wykonujemy tylko przy zmianie wersji: CREATE OR REPLACE VIEW bierze blokadę wyłączną.
    def current():
        if conn.execute("SELECT to_regclass('schema_version')").fetchone()[0]:
            return conn.execute("SELECT max(version) FROM schema_version").fetchone()[0] or 0
        return 0

    if current() >= SCHEMA_VERSION:
        return
    with conn.transaction():
        # Jeden proces naraz tworzy schemat; CREATE ... IF NOT EXISTS nie jest odporne na wyścig.
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('scamgraph-schema'))")
        if current() >= SCHEMA_VERSION:
            return
        conn.execute(SCHEMA.read_text(encoding="utf-8"))
        conn.execute("DELETE FROM schema_version")
        conn.execute("INSERT INTO schema_version VALUES (%s)", (SCHEMA_VERSION,))


def code_version() -> str:
    try:
        out = subprocess.run(["git", "describe", "--always", "--dirty"], cwd=ROOT, capture_output=True,
                             text=True, timeout=10, check=True).stdout.strip()
        return out or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def store_feed(conn, dataset_id: str, revision: str, written_ns: int, build) -> bool:
    """Zapisuje jeden eksport graph_feed: surowe obserwacje, emisje i karty.

    revision i written_ns pochodzą z export_graph. Gdy baza ma już ten albo nowszy eksport
    zbioru, kończy po jednym zapytaniu. build() zwraca wpisy dopiero wtedy, gdy trzeba pisać:
    record (linia JSONL), provider, ad_ref, run_id, seq, card (karta obserwacji ze scrapera),
    observed_at (ISO albo None), found_at (ISO), source_kind. Zwraca True, gdy zapisał.
    """
    from psycopg.types.json import Jsonb

    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('scamgraph-feed:' || %s))", (dataset_id,))
        known = conn.execute("SELECT revision, written_ns FROM feed_export WHERE dataset_id = %s",
                             (dataset_id,)).fetchone()
        if known and (known[1] > written_ns or (known[1] == written_ns and known[0] == revision)):
            return False
        for e in build():
            record = e["record"]
            raw = {"provider": e["provider"], "ad_ref": e["ad_ref"], "observation_seq": e["seq"],
                   "card": e["card"]}
            raw_sha = sha256(canonical(raw))
            row = conn.execute(
                """INSERT INTO raw_record (import_batch, kind, payload, payload_sha256)
                   VALUES (%s, 'ad', %s, %s) ON CONFLICT (payload_sha256) DO NOTHING RETURNING id""",
                (e["run_id"], Jsonb(raw), raw_sha)).fetchone()
            raw_id = row[0] if row else conn.execute(
                "SELECT id FROM raw_record WHERE payload_sha256 = %s", (raw_sha,)).fetchone()[0]
            built_from = None if "unavailable" in record else sha256(canonical(record))
            origin = (record.get("text") or {}).get("origin_id")
            text = (e["card"] or {}).get("text")
            conn.execute(
                """INSERT INTO ad (dataset_id, ad_id, provider, ad_ref, source_kind, collected_at, text,
                                   origins, unavailable, card_built_from, raw_record_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (dataset_id, ad_id) DO UPDATE SET
                       source_kind = EXCLUDED.source_kind, collected_at = EXCLUDED.collected_at,
                       text = EXCLUDED.text, origins = EXCLUDED.origins, unavailable = EXCLUDED.unavailable,
                       card_built_from = EXCLUDED.card_built_from, raw_record_id = EXCLUDED.raw_record_id""",
                (dataset_id, record["ad_id"], e["provider"], e["ad_ref"], e["source_kind"],
                 e["observed_at"] or e["found_at"], text if isinstance(text, str) else None,
                 Jsonb({"text_origin": origin} if origin else {}), record.get("unavailable"), built_from, raw_id))
            if built_from:
                conn.execute(
                    """INSERT INTO card (dataset_id, ad_id, adapter_version, card, built_from)
                       VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                    (dataset_id, record["ad_id"], ADAPTER_VERSION, Jsonb(record), built_from))
        conn.execute(
            """INSERT INTO feed_export (dataset_id, revision, written_ns) VALUES (%s, %s, %s)
               ON CONFLICT (dataset_id) DO UPDATE SET revision = EXCLUDED.revision,
                   written_ns = EXCLUDED.written_ns, stored_at = now()""",
            (dataset_id, revision, written_ns))
    return True


def store_run(conn, dataset_id: str, report: dict, default_config: dict) -> str | None:
    """Zapisuje raport i zachowuje poprzednie przebiegi tego zbioru."""
    from datetime import datetime
    from psycopg.types.json import Jsonb

    config = report.get("engine_config") or default_config
    version = report.get("code_version") or "unknown"
    fingerprint = report.get("engine_fingerprint")
    computed_at = datetime.fromisoformat(report["computed_at"])
    campaigns = report.get("campaigns", [])
    card_count = sum(len(c.get("members", [])) for c in campaigns) + len(report.get("unassigned", []))
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('scamgraph-run:' || %s))", (dataset_id,))
        last = conn.execute(
            """SELECT run_id, cards_sha256, engine_fingerprint, computed_at, config, code_version FROM engine_run
               WHERE dataset_id = %s ORDER BY computed_at DESC, seq DESC LIMIT 1""", (dataset_id,)).fetchone()
        if last and last[3] > computed_at:
            return None  # starszy raport dotarł po nowszym
        if last and last[1] == report["feed_sha256"] and last[2] == fingerprint:
            if fingerprint is not None or (last[4], last[5]) == (config, version):
                return str(last[0])
        run_id = uuid.uuid4()
        conn.execute(
            """INSERT INTO engine_run (run_id, dataset_id, computed_at, code_version, config, backend,
                                       cards_sha256, card_count, engine_fingerprint)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (run_id, dataset_id, computed_at, version, Jsonb(config), report.get("clustering_backend", "none"),
             report["feed_sha256"], card_count, fingerprint))
        rows = []
        for edge in report.get("edges", []):
            rows.append(("edge", f'{edge["a"]}|{edge["b"]}', edge))
        for camp in campaigns:
            rows.append(("campaign", camp["campaign"], camp))
            for m in camp.get("members", []):
                rows.append(("member", m["ad_id"], {"ad_id": m["ad_id"], "campaign": camp["campaign"],
                                                    "strength": m["strength"]}))
        for ad_id in report.get("unassigned", []):
            rows.append(("member", ad_id, {"ad_id": ad_id, "campaign": None, "strength": 0.0}))
        for item in report.get("unavailable", []):
            rows.append(("unavailable", item["ad_id"], item))
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO run_result (run_id, kind, key, payload) VALUES (%s, %s, %s, %s)",
                            [(run_id, kind, key, Jsonb(payload)) for kind, key, payload in rows])
    return str(run_id)


def load_cards(conn, dataset_id: str) -> list[dict]:
    """Karty z ostatniego eksportu w kolejności pliku JSONL (provider, ad_ref bajtowo)."""
    rows = conn.execute('SELECT card FROM card_current WHERE dataset_id = %s '
                        'ORDER BY provider COLLATE "C", ad_ref COLLATE "C"', (dataset_id,))
    return [card for (card,) in rows]


def latest_run(conn, dataset_id: str) -> dict | None:
    """Najnowszy przebieg zbioru z wynikami pogrupowanymi wg rodzaju."""
    fields = ("run_id", "computed_at", "code_version", "config", "backend", "cards_sha256", "card_count",
              "engine_fingerprint")
    run = conn.execute(
        f"""SELECT {", ".join(fields)} FROM engine_run WHERE dataset_id = %s
            ORDER BY computed_at DESC, seq DESC LIMIT 1""", (dataset_id,)).fetchone()
    if not run:
        return None
    out = dict(zip(fields, run))
    out["run_id"] = str(out["run_id"])
    results: dict[str, list] = {"edge": [], "member": [], "campaign": [], "query": [], "unavailable": []}
    for kind, payload in conn.execute(
            "SELECT kind, payload FROM run_result WHERE run_id = %s ORDER BY kind, key", (run[0],)):
        results[kind].append(payload)
    out["results"] = results
    return out
