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
from .page_queue import drain, process_one
from .graph_feed import export_graph, refresh_graph, update_campaigns


def timer(config_file, *, stop=lambda: False):
    previous = None
    tasks = {}
    page_task = None
    graph_task = None
    next_graph = 0.
    last_heartbeat = 0.0
    with ThreadPoolExecutor(thread_name_prefix="timer") as workers:
        while not stop():
            config = load_config(config_file)
            if config != previous:
                engine = engine_for(config)
                previous = config
            for source, future in list(tasks.items()):
                if future.done():
                    future.result()
                    del tasks[source]
            for source in engine.due():
                if source not in tasks:
                    tasks[source] = workers.submit(engine.run, [source], "timer")
            if page_task is None or page_task.done():
                if page_task is not None:
                    page_task.result()
                page_task = workers.submit(process_one, config)
            if time.monotonic() >= next_graph and (graph_task is None or graph_task.done()):
                if graph_task is not None:
                    graph_task.result()
                graph_task = workers.submit(refresh_graph, config)
                next_graph = time.monotonic() + 3
            if time.monotonic() - last_heartbeat >= 3 or not last_heartbeat:
                root = Path(config["state_dir"])
                stamp = root / ("clock-" + uuid4().hex + ".tmp")
                stamp.write_text(str(time.time()), encoding="ascii")
                os.replace(stamp, root / "clock")
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
            print(json.dumps({"started": claims, "sources": states}, ensure_ascii=False, indent=2))
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
