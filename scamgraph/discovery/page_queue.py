"""Complete published observations without holding the discovery database open during HTTP."""
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import time

from ..capture import capture, read_json, staging, verified, write_json
from ..landing_quality import content_status
from .engine import connection, error_message
from .service import collect_landing, load_config
from .types import Finding


def enrich(state, job, options):
    base = state / "captures" / job["base_capture"]
    manifest = read_json(base / "manifest.json")
    verified(base, manifest)
    original = next(a for a in manifest["artifacts"] if a["role"] == "source_record")
    source = base / original["path"]
    card = read_json(base / "ad/card.json")
    saved_card = json.loads(job["card"])
    confirmed = saved_card.get("cta_basis") == "analyst"
    if confirmed:
        card.update({key: saved_card[key] for key in ("cta", "cta_element", "cta_attribute", "cta_basis")})
    finding = Finding(job["ad_ref"], card, "", False, source, original["locator"],
                      source_kind=job["source_kind"], source_sha256=original["sha256"])
    with staging(state) as stage:
        for item in manifest["artifacts"]:
            if item["path"].startswith("ad/") and item["role"] != "source_record":
                dest = stage / item["path"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(base / item["path"], dest)
        if confirmed:
            write_json(stage / "ad/card.json", card)
        visit = collect_landing(stage, options, finding)
        result = capture(stage, state / "captures", manifest["provider"], manifest["source_observed_at"],
                         landing_visit=visit, source_kind=finding.source_kind, acquisition_method="live",
                         upstream=(source, finding.locator, finding.source_sha256),
                         parent_observation=manifest["observation_id"])
    return result.name, visit.get("status", "failed"), visit.get("reason")


def next_job(db, run_ids):
    sql = """SELECT j.*,o.capture_id,o.provider,o.source_id,o.ad_ref,o.card FROM page_jobs j
             JOIN observations o USING(seq) WHERE j.status IN ('queued','running')"""
    params = tuple(run_ids or ())
    if params:
        sql += " AND o.run_id IN (" + ",".join("?" for _ in params) + ")"
    return db.execute(sql + " ORDER BY j.seq LIMIT 1", params).fetchone()


def confirm_target(root, seq, candidate):
    with connection(root / "discovery.sqlite3", write=True) as db:
        row = db.execute("""SELECT o.card,o.capture_id FROM observations o LEFT JOIN page_jobs j USING(seq)
                            WHERE o.seq=? AND o.mode='live' AND o.provider='meta-ad-library' AND j.seq IS NULL""",
                         (seq,)).fetchone()
        if row is None:
            raise ValueError("Obserwacja ma już zlecenie albo nie pochodzi z Meta live.")
        card = json.loads(row["card"])
        if card.get("cta_element") is not None or candidate not in card.get("landing_candidates", []):
            raise ValueError("Wybrany odnośnik nie oczekuje na potwierdzenie.")
        card.update(cta="Cel potwierdzony przez analityka", cta_element=candidate["element"],
                    cta_attribute=candidate["attribute"], cta_basis="analyst")
        db.execute("UPDATE observations SET card=? WHERE seq=?", (json.dumps(card, ensure_ascii=False), seq))
        db.execute("INSERT INTO page_jobs(seq,base_capture,source_kind,updated) VALUES(?,?,?,?)",
                   (seq, row["capture_id"], "library", time.time()))


def run_landing_totals(root, run_ids):
    totals = {}
    with connection(root / "discovery.sqlite3") as db:
        for run_id in run_ids:
            rows = db.execute("""SELECT o.capture_id,j.status FROM observations o LEFT JOIN page_jobs j USING(seq)
                                 WHERE o.run_id=? AND o.mode='live'""", (run_id,)).fetchall()
            counts, by_type = Counter(), {}
            for row in rows:
                try:
                    summary = read_json(root / "captures" / row["capture_id"] / "manifest.json").get("landing_summary", {})
                    status = content_status(summary, row["status"])
                except (OSError, ValueError):
                    summary, status = {}, "unreadable"
                counts[status] += 1
                by_type.setdefault(summary.get("target_kind") or "unknown", Counter())[status] += 1
            if rows:
                totals[run_id] = {"total": len(rows), "content": counts, "by_type": by_type}
    return totals


def process_one(config, run_ids=None):
    state = Path(config["state_dir"])
    path = state / "discovery.sqlite3"
    with connection(path) as db:
        if next_job(db, run_ids) is None:
            return False
    # A dedicated SQLite file supplies an OS-released, cross-process writer lock.
    # Search, the UI and other producers use discovery.sqlite3 throughout the visit.
    with closing(sqlite3.connect(state / "page-worker.sqlite3", timeout=0)) as lock:
        try:
            lock.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            if exc.sqlite_errorcode == sqlite3.SQLITE_BUSY:
                return False
            raise
        current = load_config(config["_config_file"]) if "_config_file" in config else config
        with connection(path, write=True) as db:
            job = next_job(db, run_ids)
            if job is None:
                return False
            options = (current["sources"].get(job["source_id"], {})
                       if Path(current["state_dir"]) == state else {})
            status, reason = None, None
            if (options.get("mode") != "live" or options.get("provider") != job["provider"]
                    or not str(options.get("permission") or "").strip()):
                status, reason = "skipped", "Źródło nie ma aktywnego uprawnienia live."
            elif job["capture_id"] != job["base_capture"]:
                status, reason = "superseded", "Obserwacja ma już inną wersję analizy."
            elif job["attempts"] >= 3:
                status, reason = "failed", "Trzy próby przerwano przed zatwierdzeniem wyniku."
            if status:
                db.execute("UPDATE page_jobs SET status=?,error=?,updated=? WHERE seq=?",
                           (status, reason, time.time(), job["seq"]))
                return True
            db.execute("UPDATE page_jobs SET status='running',attempts=attempts+1,updated=? WHERE seq=?",
                       (time.time(), job["seq"]))
        result = None
        try:
            result, status, reason = enrich(state, job, {**options, "domain_db": str(path)})
        except Exception as exc:
            status, reason = "failed", error_message(exc)
        with connection(path, write=True) as db:
            if result:
                changed = db.execute("UPDATE observations SET capture_id=? WHERE seq=? AND capture_id=?",
                                     (result, job["seq"], job["base_capture"]))
                if not changed.rowcount:
                    status, reason = "superseded", "W czasie pobrania opublikowano inną wersję obserwacji."
            db.execute("UPDATE page_jobs SET status=?,result_capture=?,error=?,updated=? WHERE seq=?",
                       (status, result, reason, time.time(), job["seq"]))
        return True


def drain(config, run_ids):
    """Wait for these runs, including a job already taken by the service process."""
    if not run_ids:
        return
    while True:
        if process_one(config, run_ids):
            continue
        with connection(Path(config["state_dir"]) / "discovery.sqlite3") as db:
            if next_job(db, run_ids) is None:
                return
        time.sleep(.2)
