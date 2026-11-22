"""Operator control of the scheduler clock: pause/resume and intervals, without editing discovery.json.

The clock (``python -m scamgraph.discovery timer`` or ``serve``) re-reads ``<state_dir>/timer-control.json``
on every tick, so a change from the CLI or a Streamlit panel applies within a second:

* ``paused`` stops new source runs and new landing-page visits; runs already in progress finish normally.
  Publication of the graph feed (JSONL, campaigns, PostgreSQL when DATABASE_URL is set) keeps its own
  interval, so material collected before the pause still reaches the database.
* ``interval_seconds`` replaces the scrape interval of every source (also per-source values from the config).
* ``graph_interval_seconds`` sets how often the clock rebuilds the graph feed and the campaign report.
* ``graph_requested`` asks the clock for one immediate graph rebuild.

The clock writes ``<state_dir>/timer-status.json`` with its heartbeat and the last graph rebuild.
"""
from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

CONTROL = "timer-control.json"
STATUS = "timer-status.json"
DEFAULT_GRAPH_INTERVAL = 3.0  # earlier fixed value of the clock
ALIVE_SECONDS = 12


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "-" + uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _seconds(value, name, low, high):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError(f"{name} musi wynosić od {low:g} do {high:g} sekund.")
    return float(value)


def read_control(state_dir) -> dict:
    """Current operator settings; an unreadable or invalid file falls back to defaults."""
    raw = _read(Path(state_dir) / CONTROL)
    out = {"paused": raw.get("paused") is True, "interval_seconds": None, "graph_interval_seconds": None,
           "graph_requested": None, "updated_at": raw.get("updated_at")}
    for key, low, high in (("interval_seconds", 1, 604800), ("graph_interval_seconds", 1, 86400)):
        try:
            out[key] = _seconds(raw.get(key), key, low, high)
        except ValueError:
            pass
    if isinstance(raw.get("graph_requested"), (int, float)) and not isinstance(raw.get("graph_requested"), bool):
        out["graph_requested"] = float(raw["graph_requested"])
    return out


_UNSET = object()


def update_control(state_dir, *, paused=_UNSET, interval_seconds=_UNSET, graph_interval_seconds=_UNSET,
                   request_graph=False) -> dict:
    """Change selected settings. ``None`` for an interval restores the value from the configuration."""
    current = read_control(state_dir)
    if paused is not _UNSET:
        current["paused"] = bool(paused)
    if interval_seconds is not _UNSET:
        current["interval_seconds"] = _seconds(interval_seconds, "Interwał scrapowania", 1, 604800)
    if graph_interval_seconds is not _UNSET:
        current["graph_interval_seconds"] = _seconds(graph_interval_seconds, "Interwał grafu", 1, 86400)
    if request_graph:
        current["graph_requested"] = time.time()
    current["updated_at"] = time.time()
    _write(Path(state_dir) / CONTROL, current)
    return current


def apply_control(config: dict) -> dict:
    """Used by load_config: the operator interval overrides the configured scrape intervals."""
    control = read_control(config["state_dir"])
    config["_control"] = control
    if control["interval_seconds"] is not None:
        config["interval_seconds"] = control["interval_seconds"]
        for options in config["sources"].values():
            options.pop("interval_seconds", None)
    return config


def graph_interval(config: dict) -> float:
    control = config.get("_control") or read_control(config["state_dir"])
    if control["graph_interval_seconds"] is not None:
        return control["graph_interval_seconds"]
    value = config.get("graph_interval_seconds", DEFAULT_GRAPH_INTERVAL)
    return float(_seconds(value, "graph_interval_seconds", 1, 86400))


def write_status(state_dir, **values) -> None:
    path = Path(state_dir) / STATUS
    _write(path, {**_read(path), **values, "heartbeat": time.time()})


def status(config: dict) -> dict:
    """Snapshot for panels: settings, clock liveness, last graph rebuild and per-source schedule."""
    state = Path(config["state_dir"])
    control = read_control(state)
    clock = _read(state / STATUS)
    heartbeat = clock.get("heartbeat")
    if not isinstance(heartbeat, (int, float)):
        try:
            heartbeat = float((state / "clock").read_text(encoding="ascii"))
        except (OSError, ValueError):
            heartbeat = None
    sources = []
    db_path = state / "discovery.sqlite3"
    if db_path.is_file():
        try:
            with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)) as db:
                db.row_factory = sqlite3.Row
                for row in db.execute("""SELECT s.source_id, s.interval, s.next_run, s.last_success, r.status,
                                                r.started, r.finished, r.new_count, r.read_count, r.error
                                         FROM schedules s LEFT JOIN runs r ON r.run_id = s.last_run
                                         ORDER BY s.source_id"""):
                    if row["source_id"] in config["sources"]:
                        sources.append(dict(row))
        except sqlite3.Error:
            pass
    return {"control": control, "alive": heartbeat is not None and time.time() - heartbeat < ALIVE_SECONDS,
            "heartbeat": heartbeat, "scrape_interval": float(config.get("interval_seconds", 1800)),
            "graph_interval": graph_interval({**config, "_control": control}),
            "last_graph": clock.get("last_graph"), "next_graph": clock.get("next_graph"),
            "graph_error": clock.get("graph_error"), "sources": sources}
