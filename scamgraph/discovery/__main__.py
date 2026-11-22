"""Windows/Linux CLI, scheduler clock and loopback control panel."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from .service import DEFAULT_CONFIG, engine_for, load_config
from .page_queue import drain, process_one, run_landing_totals
from .graph_feed import export_graph, refresh_graph, update_campaigns
from .control import graph_interval, status as clock_status, update_control, write_status


def timer(config_file, *, stop=lambda: False):
    """Scheduler clock. Pause and intervals come from <state_dir>/timer-control.json (see control.py)."""
    previous = None
    tasks = {}
    page_task = None
    graph_task = None
    graph_started = None  # monotonic start of the last graph rebuild
    graph_request = None
    graph_full = False
    export_pending = False  # a source run finished since the last export
    last_graph = None
    last_heartbeat = 0.0
    with ThreadPoolExecutor(thread_name_prefix="timer") as workers:
        while not stop():
            config = load_config(config_file)
            if config != previous:
                engine = engine_for(config)
                previous = config
            control = config["_control"]
            root = Path(config["state_dir"])
            for source, future in list(tasks.items()):
                if future.done():
                    future.result()
                    del tasks[source]
                    export_pending = True  # new cards reach the feed and PostgreSQL without waiting for the graph
            if page_task is not None and page_task.done():
                if page_task.result():  # a landing visit changed a packet
                    export_pending = True
                page_task = None
            if not control["paused"]:
                for source in engine.due():
                    if source not in tasks:
                        tasks[source] = workers.submit(engine.run, [source], "timer")
                if page_task is None:
                    page_task = workers.submit(process_one, config)
            if graph_task is not None and graph_task.done():
                graph_task.result()
                graph_task = None
                if graph_full:
                    last_graph = time.time()
            if graph_request is None:
                graph_request = control["graph_requested"] or 0.
            interval = graph_interval(config)
            requested = (control["graph_requested"] or 0.) > graph_request
            if graph_task is None and (graph_started is None or requested
                                       or time.monotonic() >= graph_started + interval):
                graph_request = max(graph_request, control["graph_requested"] or 0.)
                graph_task, graph_full = workers.submit(refresh_graph, config), True
                graph_started = time.monotonic()
                export_pending = False
            elif graph_task is None and export_pending:
                graph_task, graph_full = workers.submit(refresh_graph, config, campaigns=False), False
                export_pending = False
            if time.monotonic() - last_heartbeat >= 3 or not last_heartbeat:
                stamp = root / ("clock-" + uuid4().hex + ".tmp")
                stamp.write_text(str(time.time()), encoding="ascii")
                os.replace(stamp, root / "clock")
                errors = sorted(p.stem for p in (root / "graph").glob("*.error")) if (root / "graph").is_dir() else []
                wait = None if graph_started is None else max(0., graph_started + interval - time.monotonic())
                write_status(root, paused=control["paused"], last_graph=last_graph,
                             graph_running=graph_task is not None and graph_full,
                             next_graph=None if wait is None else time.time() + wait,
                             graph_error=", ".join(errors) or None)
                last_heartbeat = time.monotonic()
            time.sleep(.35)


def main():
    parser = argparse.ArgumentParser(description="ScamGraph · wyszukiwanie reklam")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Uruchom wybrane źródło lub wszystkie")
    run.add_argument("--source", action="append", help="Identyfikator źródła, np. meta lub nask")
    run.add_argument("--phrase", help="Fraza dla pojedynczego przebiegu wybranego źródła")
    commands.add_parser("status", help="Bieżący stan i kandydaci jako JSON")
    domains = commands.add_parser("trusted-domains", help="Zaufane domeny pomijane podczas wizyt")
    actions = domains.add_subparsers(dest="action", required=True)
    actions.add_parser("list")
    for action in ("add", "remove"):
        actions.add_parser(action).add_argument("domains", nargs="+", metavar="DOMENA")
    graph = commands.add_parser("graph", help="Opublikuj aktualny JSONL dla ftf_graph")
    graph.add_argument("--mode", choices=("live", "replay", "import"), default="live")
    offline = commands.add_parser("reanalyze", help="Przelicz zapisane strony wybranego przebiegu offline")
    offline.add_argument("--run-id", required=True)
    offline.add_argument("--phrase", required=True)
    commands.add_parser("timer", help="Uruchom sam proces zegara")
    control = commands.add_parser("control", help="Pauza, wznowienie i interwały działającego zegara")
    switch = control.add_mutually_exclusive_group()
    switch.add_argument("--pause", action="store_true", help="Wstrzymaj nowe przebiegi źródeł i wizyty stron")
    switch.add_argument("--resume", action="store_true", help="Wznów przebiegi")
    control.add_argument("--scrape-minutes", type=float, help="Interwał scrapowania wszystkich źródeł; 0 = z konfiguracji")
    control.add_argument("--graph-minutes", type=float, help="Interwał przebudowy grafu i zapisu do bazy; 0 = z konfiguracji")
    control.add_argument("--graph-now", action="store_true", help="Poproś zegar o natychmiastową przebudowę grafu")
    serve = commands.add_parser("serve", help="Uruchom panel i zegar")
    serve.add_argument("--port", type=int, default=8527)
    args = parser.parse_args()
    file = args.config.resolve()
    try:
        config = load_config(file)
        if args.command == "reanalyze":
            from .reanalyze import reanalyze_run
            print(json.dumps(reanalyze_run(config, args.run_id, args.phrase), indent=2))
            return 0
        if args.command == "control":
            changes = {}
            if args.pause or args.resume:
                changes["paused"] = args.pause
            for name, key in (("scrape_minutes", "interval_seconds"), ("graph_minutes", "graph_interval_seconds")):
                value = getattr(args, name)
                if value is not None:
                    changes[key] = value * 60 if value else None
            if changes or args.graph_now:
                update_control(config["state_dir"], request_graph=args.graph_now, **changes)
            print(json.dumps(clock_status(load_config(file)), ensure_ascii=False, indent=2, default=str))
            return 0
        if args.command == "run" and args.phrase is not None:
            if len(args.source or []) != 1 or args.source[0] not in config["sources"]:
                parser.error("--phrase wymaga jednego poprawnego --source.")
            phrase = args.phrase.strip()
            if not 1 <= len(phrase) <= 200:
                parser.error("Fraza musi zawierać od 1 do 200 znaków.")
            config["sources"][args.source[0]]["phrases"] = [phrase]
        engine = engine_for(config)
        if args.command == "trusted-domains":
            from .engine import connection
            from .trusted_domains import canonical_domain
            values = [(canonical_domain(value),) for value in getattr(args, "domains", [])]
            with connection(engine.db_path, write=args.action != "list") as db:
                if args.action == "add":
                    db.executemany("INSERT OR IGNORE INTO trusted_domains(domain) VALUES (?)", values)
                elif args.action == "remove":
                    db.executemany("DELETE FROM trusted_domains WHERE domain=?", values)
                print(json.dumps([r[0] for r in db.execute("SELECT domain FROM trusted_domains ORDER BY domain")]))
            return 0
        if args.command == "run":
            claims = engine.run(args.source)
            drain(config, claims.values())
            refresh_graph(config)
            if args.phrase is not None and not claims:
                parser.exit(1, "Źródło zajęte lub właśnie obsłużone przez zegar. Nie uruchomiono podanej frazy.\n")
            states = [s for s in engine.snapshot()["sources"] if not args.source or s["source_id"] in args.source]
            print(json.dumps({"started": claims, "sources": states,
                              "landing": run_landing_totals(Path(config["state_dir"]), claims.values())},
                             ensure_ascii=False, indent=2))
            return int(any(s["status"] == "error" for s in states))
        if args.command == "graph":
            feed = export_graph(config["state_dir"], args.mode)
            update_campaigns(feed)
            print(feed)
        elif args.command == "status":
            print(json.dumps(engine.snapshot(), ensure_ascii=False, indent=2))
        elif args.command == "timer":
            timer(file)
        else:
            panel = Path(__file__).resolve().parents[2] / "scheduler_panel.py"
            process = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(panel),
                                        "--server.address", "127.0.0.1", "--server.port", str(args.port),
                                        "--server.headless", "true", "--browser.gatherUsageStats", "false",
                                        "--server.fileWatcherType", "none", "--", "--discovery", str(file)])
            try:
                timer(file, stop=lambda: process.poll() is not None)
            finally:
                if process.poll() is None:
                    process.terminate()
                process.wait()
            return process.returncode
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, f"ScamGraph · {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
