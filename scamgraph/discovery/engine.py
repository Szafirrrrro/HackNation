"""Durable per-source scheduling. Only a worker holding the current run ID may commit."""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from itertools import islice
import json
import math
import multiprocessing
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

from ..sources import clean
from .trusted_domains import skip_reason
from .types import Query, SourceError


SCHEMA = """
CREATE TABLE IF NOT EXISTS schedules (
    source_id TEXT PRIMARY KEY, interval REAL NOT NULL, next_run REAL NOT NULL,
    last_run TEXT, last_success REAL
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, trigger TEXT NOT NULL, mode TEXT NOT NULL,
    started REAL NOT NULL, deadline REAL NOT NULL, finished REAL,
    status TEXT NOT NULL, phrase TEXT, error TEXT, read_count INTEGER NOT NULL DEFAULT 0,
    new_count INTEGER NOT NULL DEFAULT 0, known_count INTEGER NOT NULL DEFAULT 0,
    missing_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS candidates (
    provider TEXT NOT NULL, ad_ref TEXT NOT NULL, latest INTEGER NOT NULL,
    PRIMARY KEY (provider, ad_ref)
);
CREATE TABLE IF NOT EXISTS reasons (
    provider TEXT NOT NULL, ad_ref TEXT NOT NULL, phrase TEXT NOT NULL, country TEXT NOT NULL,
    reason TEXT NOT NULL, PRIMARY KEY(provider, ad_ref, phrase, country, reason)
);
CREATE TABLE IF NOT EXISTS observations (
    seq INTEGER PRIMARY KEY, run_id TEXT NOT NULL, source_id TEXT NOT NULL, mode TEXT NOT NULL,
    provider TEXT NOT NULL, ad_ref TEXT NOT NULL, phrase TEXT NOT NULL, country TEXT NOT NULL,
    reason TEXT NOT NULL, card TEXT NOT NULL, capture_id TEXT NOT NULL,
    observed_at TEXT, found_at REAL NOT NULL, locator TEXT NOT NULL, missing INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS observation_identity ON observations(provider, ad_ref, phrase, reason);
CREATE INDEX IF NOT EXISTS running_deadlines ON runs(status, deadline);
CREATE TABLE IF NOT EXISTS page_jobs (
    seq INTEGER PRIMARY KEY REFERENCES observations(seq), base_capture TEXT NOT NULL, source_kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
    updated REAL NOT NULL, result_capture TEXT, error TEXT
);
CREATE INDEX IF NOT EXISTS page_jobs_status ON page_jobs(status, seq);
CREATE TABLE IF NOT EXISTS trusted_domains(domain TEXT PRIMARY KEY NOT NULL COLLATE NOCASE);
"""


@contextmanager
def connection(path, *, write=False):
    with closing(sqlite3.connect(path, timeout=10, isolation_level=None)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise


def iso(timestamp):
    if timestamp is not None:
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="milliseconds")


def duration(value, name):
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(f"{name} wymaga dodatniej, skończonej liczby sekund")
    return seconds


def finish(db, run_id, status, error=None):
    """Finish and reschedule only the current, still-running claim."""
    now = time.time()
    changed = db.execute("""UPDATE runs SET status=?, error=?, finished=?
                            WHERE run_id=? AND status='running'""", (status, error, now, run_id))
    if changed.rowcount:
        db.execute("""UPDATE schedules SET next_run=?+interval,
                         last_success=CASE WHEN ?='success' THEN ? ELSE last_success END
                      WHERE last_run=?""", (now, status, now, run_id))


def expire(db, now):
    # A dead supervisor cannot renew its claim. Old workers are fenced before
    # publication in SQLite, even if the OS did not stop them with their parent.
    for row in db.execute("SELECT run_id FROM runs WHERE status='running' AND deadline<=?", (now,)).fetchall():
        finish(db, row["run_id"], "error", "Przekroczono czas przebiegu lub przerwano proces.")
        db.execute("UPDATE schedules SET next_run=? WHERE last_run=?", (now, row["run_id"]))


class LostClaim(Exception):
    pass


def require_claim(db, run_id):
    current = db.execute("""SELECT 1 FROM runs r JOIN schedules s ON s.last_run=r.run_id
                            WHERE r.run_id=? AND r.status='running' AND r.deadline>?""",
                         (run_id, time.time())).fetchone()
    if not current:
        raise LostClaim()


def store_card(db, run_id, source, options, query, finding, capture_id):
    require_claim(db, run_id)
    provider, ad_ref = options["provider"], str(finding.ad_ref)
    region = query.country if options.get("country_filter", True) else ""
    cursor = db.execute("""INSERT INTO observations
        (run_id,source_id,mode,provider,ad_ref,phrase,country,reason,card,capture_id,
         observed_at,found_at,locator,missing) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (run_id, source, options["mode"], provider, ad_ref, query.phrase,
                         region, str(finding.reason),
                         json.dumps(finding.card, ensure_ascii=False),
                         str(capture_id), finding.observed_at, time.time(), finding.locator, int(finding.missing)))
    seq = cursor.lastrowid
    if queue_landing(options, finding):
        host = finding.skipped_domain
        db.execute("INSERT INTO page_jobs(seq,base_capture,source_kind,status,error,updated) VALUES(?,?,?,?,?,?)",
                   (seq, str(capture_id), finding.source_kind, "trusted_domain" if host else "queued",
                    skip_reason(host) if host else None, time.time()))
    db.execute("INSERT OR IGNORE INTO reasons VALUES(?,?,?,?,?)", (provider, ad_ref, query.phrase, region, finding.reason))
    inserted = db.execute("INSERT OR IGNORE INTO candidates VALUES (?,?,?)", (provider, ad_ref, seq)).rowcount
    if not inserted:
        db.execute("UPDATE candidates SET latest=? WHERE provider=? AND ad_ref=?", (seq, provider, ad_ref))
    db.execute("UPDATE runs SET new_count=new_count+?, known_count=known_count+? WHERE run_id=?",
               (inserted, 1 - inserted, run_id))


def queue_landing(options, finding):
    return (options.get("queue_landing") and options["mode"] == "live"
            and options["provider"] == "meta-ad-library" and finding.card.get("cta_element") is not None)


def error_message(exc):
    if isinstance(exc, SourceError):
        return clean(str(exc))[:600]
    if isinstance(exc, FileNotFoundError):
        return "Brak pliku źródłowego lub wymaganego programu."
    return f"Błąd adaptera lub zapisu ({type(exc).__name__})."


def work(db_path, run_id, source, options, fetch, publish):
    """Top-level spawn target. Adapters and publishers must be importable."""
    try:
        for phrase in options["phrases"]:
            query = Query(phrase, options["country"], int(options["limit"]))
            with connection(db_path, write=True) as db:
                require_claim(db, run_id)
                db.execute("UPDATE runs SET phrase=? WHERE run_id=?", (phrase, run_id))
            for finding in islice(fetch(options, query), query.limit):
                if not str(finding.ad_ref or "").strip():
                    raise SourceError("Adapter zwrócił kartę bez identyfikatora emisji.")
                with connection(db_path, write=True) as db:
                    require_claim(db, run_id)
                    db.execute("""UPDATE runs SET read_count=read_count+1, missing_count=missing_count+?
                                  WHERE run_id=?""", (int(finding.missing), run_id))
                    deadline = db.execute("SELECT deadline FROM runs WHERE run_id=?", (run_id,)).fetchone()[0]
                timeout = min(22, deadline - time.time() - 6)
                capture_id = publish(source, {**options, "query_phrase": phrase, "query_country": query.country,
                                              "landing_timeout": timeout}, finding)
                if not capture_id:
                    raise SourceError("Zapis pakietu nie zwrócił identyfikatora dowodu.")
                with connection(db_path, write=True) as db:
                    store_card(db, run_id, source, options, query, finding, capture_id)
        with connection(db_path, write=True) as db:
            require_claim(db, run_id)
            finish(db, run_id, "success")
    except LostClaim:
        return
    except Exception as exc:
        with connection(db_path, write=True) as db:
            finish(db, run_id, "error", error_message(exc))


class Engine:
    def __init__(self, config, adapters, publish):
        self.config, self.adapters, self.publish = config, adapters, publish
        self.sources = config["sources"]
        root = Path(config["state_dir"]).resolve()
        root.mkdir(parents=True, exist_ok=True)
        self.db_path = root / "discovery.sqlite3"
        with closing(sqlite3.connect(self.db_path, timeout=10)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
        now = time.time()
        with connection(self.db_path, write=True) as db:
            expire(db, now)
            for source, options in self.sources.items():
                interval = duration(options.get("interval_seconds", config.get("interval_seconds", 1800)), "interval_seconds")
                duration(options.get("timeout_seconds", 180), "timeout_seconds")
                db.execute("""INSERT INTO schedules(source_id,interval,next_run) VALUES(?,?,?)
                    ON CONFLICT(source_id) DO UPDATE SET interval=excluded.interval, next_run=excluded.next_run
                    WHERE schedules.interval != excluded.interval""",
                           (source, interval, now if config.get("start_immediately") else now+interval))

    def _claim(self, selected, trigger, requested):
        if not selected <= self.sources.keys():
            raise ValueError("Nieznane źródło")
        claims = {}
        with connection(self.db_path, write=True) as db:
            now = time.time()
            expire(db, now)
            rows = db.execute("""SELECT s.*, r.status, r.trigger, r.finished
                                 FROM schedules s LEFT JOIN runs r ON r.run_id=s.last_run""").fetchall()
            for row in rows:
                source = row["source_id"]
                if source not in selected or row["status"] == "running":
                    continue
                if trigger == "timer" and row["next_run"] > now:
                    continue
                # Also coalesce a click queued while a very fast timer finished.
                if row["trigger"] == "timer" and row["finished"] and trigger != "timer" and row["finished"] >= requested - 1:
                    continue
                options = self.sources[source]
                timeout = float(options.get("timeout_seconds", 180))
                run_id = uuid4().hex
                db.execute("""INSERT INTO runs(run_id,source_id,trigger,mode,started,deadline,status)
                              VALUES(?,?,?,?,?,?,'running')""", (run_id, source, trigger, options["mode"], now, now+timeout))
                db.execute("UPDATE schedules SET last_run=?,next_run=?+interval WHERE source_id=?", (run_id, now, source))
                claims[source] = run_id
        return claims

    def run(self, source_ids=None, trigger="cli", on_claim=None):
        """Run claimed sources concurrently; repeated triggers return no new claim."""
        if isinstance(source_ids, str):
            source_ids = [source_ids]
        selected = set(self.sources if source_ids is None else source_ids)
        requested = time.time()
        claims = self._claim(selected, trigger, requested)
        processes = {}
        try:
            if on_claim:
                on_claim(claims)
            for source, run_id in claims.items():
                options = self.sources[source]
                try:
                    process = multiprocessing.get_context("spawn").Process(
                        target=work, args=(self.db_path, run_id, source, options, self.adapters[source], self.publish),
                        daemon=True)
                    process.start()
                    processes[source] = process
                except Exception as exc:
                    with connection(self.db_path, write=True) as db:
                        finish(db, run_id, "error", f"Nie udało się uruchomić procesu ({type(exc).__name__}).")
            while processes:
                for source, process in list(processes.items()):
                    timeout = float(self.sources[source].get("timeout_seconds", 180))
                    expired = time.time() >= requested + timeout
                    if process.is_alive() and not expired:
                        continue
                    if process.is_alive():
                        process.kill()
                    process.join()
                    with connection(self.db_path, write=True) as db:
                        finish(db, claims[source], "error", "Przekroczono limit czasu przebiegu." if expired
                               else f"Proces adaptera zakończony bez wyniku (kod {process.exitcode}).")
                    process.close()
                    del processes[source]
                if processes:
                    time.sleep(0.04)
        finally:
            for process in processes.values():
                if process.is_alive():
                    process.kill()
                process.join()
                process.close()
            if claims:
                with connection(self.db_path, write=True) as db:
                    for run_id in claims.values():
                        finish(db, run_id, "error", "Przerwano nadzór nad procesem.")
        return claims

    def tick(self):
        return self.run(trigger="timer")

    def due(self):
        now = time.time()
        with connection(self.db_path) as db:
            rows = db.execute("""SELECT s.source_id FROM schedules s LEFT JOIN runs r ON r.run_id=s.last_run
                                 WHERE (s.next_run<=? AND coalesce(r.status,'idle')!='running')
                                    OR (r.status='running' AND r.deadline<=?) ORDER BY s.source_id""", (now, now))
            return [r["source_id"] for r in rows if r["source_id"] in self.sources]

    def snapshot(self):
        with connection(self.db_path) as db:
            rows = db.execute("""SELECT s.source_id,s.last_run AS run_id,s.last_success,s.next_run,
                        r.started,r.finished,r.trigger,r.mode AS run_mode,r.status,r.phrase,r.error,
                        r.read_count,r.new_count,r.known_count,r.missing_count
                        FROM schedules s LEFT JOIN runs r ON r.run_id=s.last_run ORDER BY s.source_id""").fetchall()
            sources = []
            for row in rows:
                if row["source_id"] not in self.sources:
                    continue
                item = dict(row)
                item["mode"] = self.sources[row["source_id"]]["mode"]
                item["status"] = item["status"] or "idle"
                for key in ("last_success", "next_run", "started", "finished"):
                    item[key] = iso(item[key])
                for key in ("read_count", "new_count", "known_count", "missing_count"):
                    item[key] = item[key] or 0
                sources.append(item)

            reasons = {}
            for provider, ref, phrase, reason, country in db.execute(
                    """SELECT provider,ad_ref,phrase,reason,country FROM reasons
                       ORDER BY provider,ad_ref,phrase,reason,country"""):
                region = country or "korpus bez filtra kraju"
                reasons.setdefault((provider, ref), []).append(f"{phrase} · {region} · {reason}")
            candidates = []
            for row in db.execute("""SELECT o.*,j.status AS page_status FROM candidates c JOIN observations o ON o.seq=c.latest
                                      LEFT JOIN page_jobs j ON j.seq=o.seq
                                      ORDER BY o.seq DESC"""):
                item = dict(row)
                item["card"] = json.loads(item["card"])
                item["found_at"] = iso(item["found_at"])
                item["reasons"] = reasons[(item["provider"], item["ad_ref"])]
                candidates.append(item)
            page_counts = {r["status"]: r["n"] for r in db.execute(
                "SELECT status,count(*) AS n FROM page_jobs GROUP BY status")}
        return {"sources": sources, "candidates": candidates, "page_jobs": page_counts}
