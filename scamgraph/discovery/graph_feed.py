"""Publish the latest observed deliveries in the input format of ftf_graph."""
from contextlib import closing
from datetime import datetime, timezone
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from itertools import islice
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import traceback
from uuid import uuid4

from models.common.import_rows import source_identity

from .. import db as pgdb
from ..capture import read_json, staging, write_json
from ..catalog import artifact_path
from ..graph_features import (image_artifact, image_artifacts, image_features, is_verified, page_features,
                              source_artifacts, text_features, verified_sources)
from ..sources import address, digest
from .engine import connection, iso

GRAPH = Path(__file__).resolve().parents[2] / "graph"
# Parametry silnika przekazywane jawnie, żeby zapis przebiegu w bazie odpowiadał wywołaniu.
ENGINE_CONFIG = {"min_cluster": 3, "min_samples": 2, "min_edge": 0.25, "min_campaign": 0.65}


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
    valid = verified_sources(folder, meta)
    visual = image_features(folder, image_artifact(meta, ad.get("image_path")))
    if visual:
        source = visual["source_ref"]
        valid.add((source["file"], source["origin_id"]))
    body = ad.get("text", "")
    text_refs = [f["evidence"] for f in result.get("ad_fields", []) if f["field"] == "text"
                 and f["value"] == body and is_verified(f["evidence"], valid)]
    card = {"text": text_features(body if text_refs else "", ad.get("text_origin"), source_refs=text_refs),
            "infra": {}, "page": {}}
    if visual:
        card["visual"] = visual
    if original := original_emission(folder, result, meta, valid):
        card["provenance"] = {"original_provider": original[0], "original_ad_ref": original[1]}
    visit = result.get("landing_visit", {})
    if "content_status" in visit and (visit["content_status"] != "usable" or visit.get("target_kind") != "web"):
        return card
    for link in result.get("ad_page_links", []):
        if link["capture_id"] != folder.name or link["ad_id"] != ad.get("ad_id"):
            continue
        nav = link["navigation_evidence"]
        if not (is_verified(nav, valid) and is_verified(link.get("evidence", {}), valid)):
            continue
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
        card["page"] = page_features(result, meta, networks=[network], valid=valid)
        card["infra"] = {"final_domain": target["host"], "origin_id": card["page"]["origin_id"],
                         "source_ref": nav}
        break
    return card


def original_emission(folder, result, manifest, valid):
    """Recover the provider identity of a historic organizer JSONL observation."""
    if (result.get("ad") or {}).get("source", {}).get("kind") not in {"organizer", "synthetic"}:
        return None
    ref = result.get("source_record") or {}
    if not is_verified(ref, valid) or not ref["file"].endswith(".jsonl"):
        return None
    locator = ref.get("locator", {}).get("record", "")
    if not locator.startswith("line:"):
        return None
    try:
        line = int(locator.removeprefix("line:"))
        with (folder / ref["file"]).open(encoding="utf-8-sig") as stream:
            row = json.loads(next(islice(stream, line - 1, line)))
        if isinstance(row, dict) and row.get("ad_id") == manifest.get("ad_ref"):
            return source_identity(row)
    except (OSError, ValueError, RecursionError, StopIteration):
        return None
    return None


def file_stamp(path, *, follow_symlinks=True):
    try:
        entry = path.stat(follow_symlinks=follow_symlinks)
        return entry.st_mtime_ns, entry.st_size
    except OSError:
        return None


@lru_cache(maxsize=256)
def source_paths(folder, manifest_stamp):
    try:
        meta = read_json(folder / "manifest.json")
        items = [*source_artifacts(meta), *image_artifacts(meta)]
        paths = [Path(item["path"]) for item in items]
        return tuple(folder / path for path in paths if not path.anchor and ".." not in path.parts)
    except (OSError, ValueError, TypeError, KeyError):
        return ()


def package_stamp(folder):
    manifest = file_stamp(folder / "manifest.json")
    sources = source_paths(folder, manifest) if manifest else ()
    return (manifest, file_stamp(folder / "extracted.json"),
            tuple((file_stamp(path, follow_symlinks=False), file_stamp(path)) for path in sources))


@lru_cache(maxsize=256)
def projected_version(folder, stamp):
    if None in stamp[:2]:
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
        revision = pgdb.sha256(pgdb.canonical([pgdb.ADAPTER_VERSION, [tuple(r) for r in rows], versions]))
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
                        snapshot = state / "captures" / cid
                        projected = projected_version(snapshot, stamp)
                        payload = {**projected,
                                   "ad_id": row["provider"] + "/" + row["ad_ref"],
                                   "first_seen": iso(row["first_at"]), "last_seen": iso(row["found_at"]),
                                   "provenance": {**projected.get("provenance", {}),
                                                  "source": row["provider"], "mode": mode, "capture_id": cid,
                                                  "snapshot": str(snapshot.resolve()),
                                                  "provider": row["provider"], "ad_ref": row["ad_ref"],
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
        feed_sha256 = pgdb.sha256(output.read_bytes()) if pgdb.enabled() else None
    # Baza poza blokadą SQLite; store_feed najpierw sprawdza, czy ma już ten eksport.
    mirror(folder, mode + ".feed", lambda conn: pgdb.store_feed(
        conn, mode, revision, written[0], lambda: feed_entries(state, output, rows, feed_sha256, mode)))
    return output


def feed_entries(state, output, rows, feed_sha256, mode):
    """Linie opublikowanego JSONL z surową kartą obserwacji, do zapisu w bazie. Czyta plik,
    a nie przelicza projekcji, więc baza dostaje dokładnie to, co plik."""
    data = output.read_bytes()
    if pgdb.sha256(data) != feed_sha256:
        raise pgdb.Stale("Plik grafu zmienił się w trakcie zapisu do bazy.")
    records = [json.loads(line) for line in data.splitlines() if line.strip()]
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


def engine_signature(trusted_override):
    """Fingerprint the code and exact policy inputs used by the engine subprocess."""
    from graph.ftf_graph import trusted

    files = sorted(path for path in GRAPH.joinpath("ftf_graph").glob("*.py")
                   if path.name not in {"neo4j_store.py", "presentation.py"})
    files.append(GRAPH.parent / "models" / "common" / "import_rows.py")
    policy = {"cert": trusted.DATA / "cert_domains.txt"}
    if trusted_override:
        policy["trusted_override"] = Path(trusted_override)
    else:
        policy.update(tranco=trusted.DATA / "tranco_46YVX.csv", manual=trusted.DATA / "trusted_manual.txt")
    try:
        policy["psl"] = trusted.default_psl_path()
    except ImportError:
        pass

    def input_digest(path):
        try:
            return digest(path)
        except FileNotFoundError:
            return None

    runtime = {"python": sys.version.split()[0]}
    for package in ("numpy", "scipy", "scikit-learn", "publicsuffixlist", "idna"):
        try:
            runtime[package] = version(package)
        except PackageNotFoundError:
            runtime[package] = None
    components = {"code": {p.relative_to(GRAPH.parent).as_posix(): input_digest(p) for p in files}, "runtime": runtime,
                  "domain_policy": {kind: input_digest(path) for kind, path in policy.items()}}
    return pgdb.sha256(pgdb.canonical(components)), components


def update_campaigns(feed):
    """Compute from an immutable input; atomically publish both edges and groups."""
    feed = Path(feed).resolve()
    mode = feed.stem
    output = feed.with_suffix(".campaigns.json")
    with closing(sqlite3.connect(feed.parent / "analysis.sqlite3", timeout=1)) as lock, lock:
        lock.execute("BEGIN IMMEDIATE")
        lock.execute("CREATE TABLE IF NOT EXISTS reports(mode TEXT PRIMARY KEY, revision TEXT)")
        data = feed.read_bytes()
        feed_sha256 = pgdb.sha256(data)
        config = ENGINE_CONFIG.copy()
        env = os.environ.copy()
        override = env.get("FTF_TRUSTED_DOMAINS")
        if override:
            override = env["FTF_TRUSTED_DOMAINS"] = str(Path(override).resolve())
        signature, components = engine_signature(override)
        engine_fingerprint = pgdb.sha256(pgdb.canonical([signature, config]))
        revision = pgdb.sha256(pgdb.canonical([feed_sha256, engine_fingerprint]))
        last = lock.execute("SELECT revision FROM reports WHERE mode=?", (mode,)).fetchone()
        report = None
        if last and last[0] == revision:
            try:
                candidate = read_json(output)
                if isinstance(candidate, dict) and candidate.get("analysis_revision") == revision:
                    report = candidate
            except (FileNotFoundError, ValueError):
                pass
        if report is None:
            report = compute_report(feed, mode, data, output, env, {
                "feed_sha256": feed_sha256, "analysis_revision": revision,
                "engine_config": config, "engine_fingerprint": engine_fingerprint,
                "domain_policy": components["domain_policy"], "code_version": pgdb.code_version(),
            }, signature)
            lock.execute("INSERT OR REPLACE INTO reports VALUES (?,?)", (mode, revision))
    # Do bazy trafia migawka tego samego raportu, poza blokadą SQLite.
    # Raport policzony przed włączeniem bazy dochodzi przy następnym przebiegu zegara.
    if pgdb.enabled():
        mirror(feed.parent, mode + ".run", lambda conn: pgdb.store_run(conn, mode, report, config))


def compute_report(feed, mode, data, output, env, metadata, signature):
    with staging(feed.parent) as stage:
        records = [json.loads(line) for line in data.splitlines() if line.strip()]
        unavailable = [{"ad_id": r["ad_id"], "capture_id": r.get("provenance", {}).get("capture_id"),
                        "reason": r["unavailable"]} for r in records if "unavailable" in r]
        available = [r for r in records if "unavailable" not in r]
        if available:
            source = stage / "cards.jsonl"
            with source.open("w", encoding="utf8") as stream:
                for row in available:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            args = [sys.executable, "-m", "ftf_graph", str(source), "--out", str(stage)]
            for name, threshold in metadata["engine_config"].items():
                args.extend(("--" + name.replace("_", "-"), str(threshold)))
            subprocess.run(args, cwd=GRAPH, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=True, timeout=180)
            groups, edges = read_json(stage / "campaigns.json"), read_json(stage / "edges.json")
        else:
            groups, edges = {"campaigns": [], "unassigned": [], "clustering_backend": "none"}, []
        report = {**groups, "edges": edges, "mode": mode, "unavailable": unavailable, **metadata,
                  "computed_at": datetime.now(timezone.utc).isoformat(timespec="microseconds")}
        write_json(stage / "report.json", report)
        if engine_signature(env.get("FTF_TRUSTED_DOMAINS"))[0] != signature:
            raise ValueError("Metoda analizy zmieniła się podczas przebiegu.")
        os.replace(stage / "report.json", output)
        return report


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
