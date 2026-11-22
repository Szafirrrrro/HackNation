"""Publish the latest observed deliveries in the input format of ftf_graph."""
from contextlib import closing
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import traceback
from uuid import uuid4

from .. import db as pgdb
from ..capture import read_json, staging, write_json
from ..catalog import artifact_path
from ..sources import address
from .engine import connection, iso

TEXT_METHOD = "char-wb-3-5-hash1024-l2/v1"
# Parametry silnika przekazywane jawnie, żeby zapis przebiegu w bazie odpowiadał wywołaniu.
ENGINE_CONFIG = {"min_cluster": 3, "min_samples": 2, "min_edge": 0.25}


def mirror(folder, name, action):
    """Powiela wynik w PostgreSQL, gdy ustawiono DATABASE_URL. Wywoływać poza blokadami SQLite.
    Pliki pozostają podstawowym wynikiem: błąd bazy trafia z tracebackiem do
    <tryb>.<feed|run>.db-error i na stderr, ale nie zatrzymuje pipeline'u."""
    if not pgdb.enabled():
        return
    marker = folder / (name + ".db-error")
    try:
        with closing(pgdb.connect()) as conn:
            action(conn)
    except pgdb.Stale:
        return  # nowszy eksport lub raport zapisze się sam
    except Exception:  # baza jest opcjonalnym odbiorcą, nie może zatrzymać zegara
        text = traceback.format_exc()
        print(f"[scamgraph.db] {name}: {text}", file=sys.stderr)
        marker.write_text(text[-4000:], encoding="utf8")
        return
    marker.unlink(missing_ok=True)


def projection(folder):
    meta = read_json(folder / "manifest.json")
    if meta["capture_id"] != folder.name:
        raise ValueError("Niezgodny identyfikator pakietu grafu.")
    result = read_json(artifact_path(folder, meta["result"]))
    ad = result.get("ad") or {}
    card = {"text": {"ad_text": ad.get("text", "")}, "infra": {}, "page": {}}
    body = card["text"]["ad_text"]
    if ad.get("text_origin") and len(body.split()) >= 4 and len(body.strip()) >= 24:
        from sklearn.feature_extraction.text import HashingVectorizer
        vector = HashingVectorizer(analyzer="char_wb", ngram_range=(3, 5), n_features=1024)
        card["text"].update(embedding=vector.transform([body]).toarray()[0].round(6).tolist(),
                            method=TEXT_METHOD, origin_id=ad["text_origin"])
    visit = result.get("landing_visit", {})
    if "content_status" in visit and (visit["content_status"] != "usable" or visit.get("target_kind") != "web"):
        return card
    for link in result.get("ad_page_links", []):
        if link["capture_id"] != folder.name or link["ad_id"] != ad.get("ad_id"):
            continue
        nav = link["navigation_evidence"]
        network = next((n for n in result["networks"] if n["evidence"]["file"] == nav["file"]
                        and n["evidence"]["origin_id"] == nav["origin_id"]), None)
        if not network:
            continue
        document = next((r for r in network["entries"] if r["evidence"] == nav), None)
        if not document or not 200 <= (document["status"] or 0) < 300:
            continue
        target = address(link["final_url"])
        if not target or document.get("address") != target:
            continue
        card["infra"]["final_domain"] = target["host"]
        pixels = [*network["pixels"], *result["pixels"]]
        for page in result["pages"]:
            pixels.extend(page["pixels"])
        ids = sorted({p["value"]["id"] for p in pixels if p["value"]["provider"] == "meta"})
        card["page"]["tracking_ids"] = {"meta_pixel": ids[0]} if len(ids) == 1 else {}
        card["page"]["script_hashes"] = sorted({a["sha256"] for a in meta["artifacts"]
            if a["role"] == "asset" and a["type"] in {"text/javascript", "application/javascript"}})
        # Same conditions as the fields above; several different page fingerprints stay unresolved.
        templates = {json.dumps(p["dom_template_minhash"], sort_keys=True) for p in result["pages"]
                     if p.get("dom_template_minhash")}
        if len(templates) == 1:
            card["page"]["dom_template_minhash"] = json.loads(templates.pop())
        break
    return card


def package_stamp(folder):
    stamp = []
    for name in ("manifest.json", "extracted.json"):
        try:
            entry = (folder / name).stat()
            stamp.append((entry.st_mtime_ns, entry.st_size))
        except FileNotFoundError:
            stamp.append(None)
    return tuple(stamp)


@lru_cache(maxsize=256)
def projected_version(folder, stamp):
    if None in stamp:
        return {"unavailable": "Brakuje plików pakietu"}
    try:
        return projection(folder)
    except (FileNotFoundError, ValueError, KeyError, TypeError, IndexError):
        return {"unavailable": "Nie udało się zweryfikować pakietu"}


def export_graph(state, mode="live"):
    if mode not in {"live", "replay", "import"}:
        raise ValueError("Nieznany tryb źródła grafu.")
    state = Path(state)
    folder = state / "graph"
    folder.mkdir(exist_ok=True)
    output = folder / (mode + ".jsonl")
    # Serialise exporters only. An older concurrent snapshot cannot replace a newer one.
    with closing(sqlite3.connect(folder / "export.sqlite3", timeout=10)) as index, index:
        index.execute("BEGIN IMMEDIATE")
        index.execute("CREATE TABLE IF NOT EXISTS exports(mode TEXT PRIMARY KEY, revision TEXT NOT NULL)")
        # Czas zapisu pliku porządkuje eksporty w bazie, która jest zapisywana już poza tą blokadą.
        index.execute("CREATE TABLE IF NOT EXISTS export_times(mode TEXT PRIMARY KEY, written_ns INTEGER NOT NULL)")
        with connection(state / "discovery.sqlite3") as db:
            rows = db.execute("""SELECT o.seq,o.capture_id,o.provider,o.ad_ref,o.observed_at,o.found_at,s.first_at
                FROM observations o JOIN (SELECT provider,ad_ref,MAX(seq) AS latest,MIN(found_at) AS first_at
                FROM observations WHERE mode=? GROUP BY provider,ad_ref) s ON o.seq=s.latest
                ORDER BY o.provider,o.ad_ref""", (mode,)).fetchall()
        versions = []
        for row in rows:
            cid = row["capture_id"]
            if not cid.isalnum():
                raise ValueError("Niepoprawny identyfikator pakietu grafu.")
            versions.append(package_stamp(state / "captures" / cid))
        revision = hashlib.sha256(json.dumps(["graph-feed/4", [tuple(r) for r in rows], versions]).encode()).hexdigest()
        last = index.execute("SELECT revision FROM exports WHERE mode=?", (mode,)).fetchone()
        unchanged = bool(last and last[0] == revision and output.is_file())
        if unchanged and not pgdb.enabled():
            return output
        if not unchanged:
            temp = folder / (uuid4().hex + ".tmp")
            try:
                with temp.open("w", encoding="utf8") as stream:
                    for row, stamp in zip(rows, versions):
                        cid = row["capture_id"]
                        payload = {**projected_version(state / "captures" / cid, stamp),
                                   "ad_id": row["provider"] + "/" + row["ad_ref"],
                                   "first_seen": iso(row["first_at"]), "last_seen": iso(row["found_at"]),
                                   "provenance": {"source": row["provider"], "mode": mode, "capture_id": cid,
                                                  "fetched_at": row["observed_at"], "observation_seq": row["seq"]}}
                        stream.write(json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n")
                os.replace(temp, output)
                index.execute("INSERT OR REPLACE INTO exports VALUES (?,?)", (mode, revision))
                # Monotonicznie także przy cofnięciu zegara, żeby baza nie pominęła nowszego eksportu.
                before = index.execute("SELECT written_ns FROM export_times WHERE mode=?", (mode,)).fetchone()
                index.execute("INSERT OR REPLACE INTO export_times VALUES (?,?)",
                              (mode, max(time.time_ns(), before[0] + 1 if before else 0)))
            finally:
                temp.unlink(missing_ok=True)
        written = index.execute("SELECT written_ns FROM export_times WHERE mode=?", (mode,)).fetchone()
        if written is None:  # plik powstał, zanim włączono bazę
            written = (time.time_ns(),)
            index.execute("INSERT INTO export_times VALUES (?,?)", (mode, written[0]))
    # Baza poza blokadą SQLite; store_feed najpierw sprawdza, czy ma już ten eksport.
    mirror(folder, mode + ".feed", lambda conn: pgdb.store_feed(
        conn, mode, revision, written[0], lambda: feed_entries(state, mode, output, rows)))
    return output


def feed_entries(state, mode, output, rows):
    """Linie opublikowanego JSONL z surową kartą obserwacji, do zapisu w bazie. Czyta plik,
    a nie przelicza projekcji, więc baza dostaje dokładnie to, co plik."""
    records = [json.loads(line) for line in output.read_text(encoding="utf8").splitlines() if line.strip()]
    if len(records) != len(rows) or any(rec["provenance"]["observation_seq"] != row["seq"]
                                        for rec, row in zip(records, rows)):
        raise pgdb.Stale("Plik grafu zmienił się w trakcie zapisu do bazy.")
    seqs = [row["seq"] for row in rows]
    extra = {}
    with connection(state / "discovery.sqlite3") as source:
        for i in range(0, len(seqs), 500):
            chunk = seqs[i:i + 500]
            extra.update({seq: (run_id, card) for seq, run_id, card in source.execute(
                f"SELECT seq, run_id, card FROM observations WHERE seq IN ({','.join('?' * len(chunk))})", chunk)})
    return [{"record": rec, "provider": row["provider"], "ad_ref": row["ad_ref"],
             "seq": row["seq"], "run_id": extra[row["seq"]][0], "card": json.loads(extra[row["seq"]][1]),
             "observed_at": row["observed_at"], "found_at": iso(row["found_at"]),
             "source_kind": "library" if mode == "live" else "upload"}
            for row, rec in zip(rows, records)]


def update_campaigns(feed):
    """Compute from an immutable input; atomically publish both edges and groups."""
    mode = feed.stem
    output = feed.with_suffix(".campaigns.json")
    with closing(sqlite3.connect(feed.parent / "analysis.sqlite3", timeout=1)) as lock, lock:
        lock.execute("BEGIN IMMEDIATE")
        lock.execute("CREATE TABLE IF NOT EXISTS reports(mode TEXT PRIMARY KEY, revision TEXT)")
        data = feed.read_bytes()
        revision = hashlib.sha256(data).hexdigest()
        last = lock.execute("SELECT revision FROM reports WHERE mode=?", (mode,)).fetchone()
        if not (last and last[0] == revision and output.is_file()):
            compute_report(feed, mode, data, revision, output)
            lock.execute("INSERT OR REPLACE INTO reports VALUES (?,?)", (mode, revision))
    # Do bazy trafia ten sam plik raportu (z opisami TEXT_METHOD), poza blokadą SQLite.
    # Raport policzony przed włączeniem bazy dochodzi przy następnym przebiegu zegara.
    if pgdb.enabled():
        mirror(feed.parent, mode + ".run", lambda conn: pgdb.store_run(conn, mode, read_json(output), ENGINE_CONFIG))


def compute_report(feed, mode, data, revision, output):
    with staging(feed.parent) as stage:
        records = [json.loads(line) for line in data.splitlines()]
        unavailable = [{"ad_id": r["ad_id"], "capture_id": r.get("provenance", {}).get("capture_id"),
                        "reason": r["unavailable"]} for r in records if "unavailable" in r]
        available = [r for r in records if "unavailable" not in r]
        if available:
            source = stage / "cards.jsonl"
            with source.open("w", encoding="utf8") as stream:
                for row in available:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            graph = Path(__file__).resolve().parents[2] / "graph"
            subprocess.run([sys.executable, "-m", "ftf_graph", str(source), "--out", str(stage),
                            "--min-cluster", str(ENGINE_CONFIG["min_cluster"]),
                            "--min-samples", str(ENGINE_CONFIG["min_samples"]),
                            "--min-edge", str(ENGINE_CONFIG["min_edge"])],
                           cwd=graph, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=True, timeout=180)
            groups, edges = read_json(stage / "campaigns.json"), read_json(stage / "edges.json")
            methods = {r["ad_id"]: r.get("text", {}).get("method") for r in available}
            for edge in edges:
                if methods[edge["a"]] == methods[edge["b"]] == TEXT_METHOD:
                    for reason in edge["reasons"]:
                        if reason["kind"] == "text":
                            reason["method"] = TEXT_METHOD
                            reason["detail"] = reason["detail"].replace("podobna narracja tekstu",
                                                                       "podobne fragmenty tekstu")
        else:
            groups, edges = {"campaigns": [], "unassigned": [], "clustering_backend": "none"}, []
        # engine_config i code_version opisują ten przebieg w chwili liczenia, nie zapisu do bazy.
        write_json(stage / "report.json", {**groups, "edges": edges, "mode": mode, "unavailable": unavailable,
                   "feed_sha256": revision, "computed_at": iso(time.time()),
                   "engine_config": ENGINE_CONFIG, "code_version": pgdb.code_version()})
        os.replace(stage / "report.json", output)


def refresh_graph(config):
    state = Path(config["state_dir"])
    for mode in sorted({s["mode"] for s in config["sources"].values()}):
        error = state / "graph" / (mode + ".error")
        try:
            feed = export_graph(state, mode)
            update_campaigns(feed)
            error.unlink(missing_ok=True)
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, subprocess.SubprocessError) as exc:
            # The last complete JSONL remains usable while the input is being repaired.
            error.parent.mkdir(exist_ok=True)
            error.write_text(type(exc).__name__, encoding="ascii")
