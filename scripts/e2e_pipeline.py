"""Test całego pipeline'u ScamGraph jednym poleceniem.

    scraper (scamgraph.discovery) -> pakiety captures/ -> wizyty stron z CTA (pages/)
    -> graph_feed (graph/<tryb>.jsonl) -> ftf_graph (graph/<tryb>.campaigns.json)

Przykłady (z katalogu projektu, w środowisku z requirements-capture.txt i graph/requirements.txt):

    python scripts/e2e_pipeline.py                                   # offline: discovery.demo.json (replay)
    python scripts/e2e_pipeline.py --config .private-discovery/e2e-50.json          # live wg konfiguracji
    python scripts/e2e_pipeline.py --config discovery.live.json --limit 25 \\
        --phrase "oferta inwestycyjna" --phrase "pasywny dochód" --permission "zakres zgody operatora"
    python scripts/e2e_pipeline.py --unit-tests                      # dodatkowo testy z tests/

Każde uruchomienie dostaje świeży katalog stanu w .private-discovery/e2e-<czas>/ (poza Gitem),
więc nie miesza się z panelem ani poprzednimi przebiegami. Kod wyjścia 0 oznacza, że wszystkie
sprawdzenia przeszły; lista sprawdzeń i liczniki trafiają na stdout oraz do <stan>/e2e-summary.json.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("playwright", "sklearn", "numpy", "scipy")


def build_config(base_file: Path, state: Path, args) -> Path:
    """Kopia konfiguracji z absolutnymi ścieżkami, świeżym stanem i opcjonalnymi nadpisaniami."""
    config = json.loads(base_file.read_text(encoding="utf-8-sig"))
    base = base_file.parent
    config["state_dir"] = str(state)
    sources = config["sources"]
    if args.source:
        unknown = set(args.source) - set(sources)
        if unknown:
            sys.exit(f"Nieznane źródła: {', '.join(sorted(unknown))}")
    for sid, opts in sources.items():
        if opts.get("path"):
            opts["path"] = str((base / opts["path"]).resolve())
        opts["imports"] = {p: str((base / f).resolve()) for p, f in opts.get("imports", {}).items()}
        if args.source and sid not in args.source:
            continue
        if args.phrase:
            opts["phrases"] = args.phrase
        if args.limit:
            opts["limit"] = args.limit
        if args.permission:
            opts["permission"] = args.permission
    state.mkdir(parents=True, exist_ok=True)
    out = state / "e2e-config.json"
    out.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)


def main() -> int:
    p = argparse.ArgumentParser(description="ScamGraph · test end-to-end")
    p.add_argument("--config", type=Path, default=ROOT / "discovery.demo.json")
    p.add_argument("--source", action="append", help="tylko wybrane źródło (np. meta); domyślnie wszystkie")
    p.add_argument("--phrase", action="append", help="nadpisz frazy wybranych źródeł")
    p.add_argument("--limit", type=int, help="nadpisz limit kart na frazę (1–100)")
    p.add_argument("--permission", help="zakres uprawnienia operatora dla trybu live")
    p.add_argument("--state", type=Path, help="katalog stanu (domyślnie .private-discovery/e2e-<czas>)")
    p.add_argument("--min-cards", type=int, default=1, help="minimalna liczba kart w grafie (domyślnie 1)")
    p.add_argument("--timeout", type=int, default=3600, help="limit czasu przebiegu w sekundach")
    p.add_argument("--unit-tests", action="store_true", help="uruchom też python -m unittest discover -s tests")
    args = p.parse_args()

    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> bool:
        checks.append((name, bool(ok), detail))
        print(f"[{'OK ' if ok else 'BŁĄD'}] {name}" + (f" — {detail}" if detail else ""), flush=True)
        return bool(ok)

    # 1. Środowisko
    missing = [m for m in REQUIRED if importlib.util.find_spec(m) is None]
    if not check("zależności Pythona", not missing, ", ".join(missing) or sys.executable):
        print("Zainstaluj: pip install -r requirements-capture.txt -r graph/requirements.txt")
        return 2

    if args.unit_tests:
        t0 = time.monotonic()
        res = run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], args.timeout)
        tail = (res.stderr or res.stdout).strip().splitlines()[-1:] or [""]
        check("testy jednostkowe (tests/)", res.returncode == 0, f"{tail[0]} ({time.monotonic() - t0:.0f} s)")

    # 2. Konfiguracja i świeży stan
    base_file = args.config.resolve()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    state = (args.state or ROOT / ".private-discovery" / f"e2e-{stamp}").resolve()
    config_file = build_config(base_file, state, args)
    config = json.loads(config_file.read_text(encoding="utf-8"))
    selected = args.source or list(config["sources"])
    modes = sorted({config["sources"][s]["mode"] for s in selected})
    print(f"konfiguracja: {base_file}\nstan: {state}\ntryby: {', '.join(modes)}", flush=True)

    # 3. Scraper + kolejka wizyt + odświeżenie grafu (jedno polecenie CLI, jak przycisk „Uruchom teraz”)
    cmd = [sys.executable, "-m", "scamgraph.discovery", "--config", str(config_file), "run"]
    for s in args.source or []:
        cmd += ["--source", s]
    t0 = time.monotonic()
    res = run(cmd, args.timeout)
    elapsed = time.monotonic() - t0
    (state / "e2e-run.stdout.json").write_text(res.stdout, encoding="utf-8")
    (state / "e2e-run.stderr.txt").write_text(res.stderr, encoding="utf-8")
    try:
        summary = json.loads(res.stdout)
    except json.JSONDecodeError:
        summary = {}
    check("przebieg scamgraph.discovery run", res.returncode == 0 and summary,
          f"kod {res.returncode}, {elapsed:.0f} s" + (f", stderr: {res.stderr.strip()[-300:]}" if res.stderr.strip() else ""))
    for src in summary.get("sources", []):
        check(f"źródło {src.get('source_id')}", src.get("status") != "error",
              f"status={src.get('status')}, odczytane={src.get('read_count')}, nowe={src.get('new_count')}"
              + (f", błąd: {src.get('error')}" if src.get("error") else ""))

    # 4. Baza discovery: obserwacje i wizyty stron
    db_path = state / "discovery.sqlite3"
    counts: dict = {"elapsed_s": round(elapsed, 1)}
    if check("baza discovery.sqlite3", db_path.is_file()):
        with closing(sqlite3.connect(db_path)) as db:
            counts["observations"] = db.execute("SELECT count(*) FROM observations").fetchone()[0]
            counts["unique_ads"] = dict(db.execute(
                "SELECT mode, count(DISTINCT provider||'/'||ad_ref) FROM observations GROUP BY mode"))
            counts["page_jobs"] = dict(db.execute("SELECT status, count(*) FROM page_jobs GROUP BY status"))
        check("karty reklam zapisane", counts["observations"] > 0, f"{counts['observations']} obserwacji")
        pending = sum(counts["page_jobs"].get(s, 0) for s in ("queued", "running"))
        check("kolejka wizyt opróżniona", pending == 0, f"wizyty: {counts['page_jobs'] or 'brak'}")
    pages = state / "pages"
    counts["page_packages"] = sum(1 for d in pages.iterdir() if d.is_dir()) if pages.is_dir() else 0

    # 5. Graf: JSONL dla silnika i raport kampanii
    for mode in modes:
        feed = state / "graph" / f"{mode}.jsonl"
        report = state / "graph" / f"{mode}.campaigns.json"
        error = state / "graph" / f"{mode}.error"
        expected = counts.get("unique_ads", {}).get(mode, 0)
        if not check(f"[{mode}] wejście grafu {feed.name}", feed.is_file()):
            continue
        rows = [json.loads(line) for line in feed.read_text(encoding="utf-8").splitlines() if line.strip()]
        with_page = sum(1 for r in rows if (r.get("infra") or {}).get("final_domain"))
        unavailable = sum(1 for r in rows if "unavailable" in r)
        counts[f"{mode}_cards"] = len(rows)
        counts[f"{mode}_cards_with_landing"] = with_page
        check(f"[{mode}] jedna karta na emisję", len(rows) == expected, f"{len(rows)} kart / {expected} emisji")
        check(f"[{mode}] minimalna liczba kart", len(rows) >= args.min_cards, f"{len(rows)} >= {args.min_cards}")
        check(f"[{mode}] pakiety zweryfikowane", unavailable == 0, f"niedostępne: {unavailable}")
        check(f"[{mode}] brak błędu workera grafu", not error.exists(),
              error.read_text(encoding="ascii") if error.exists() else "")
        if check(f"[{mode}] raport kampanii {report.name}", report.is_file()):
            rep = json.loads(report.read_text(encoding="utf-8"))
            same = rep.get("feed_sha256") == hashlib.sha256(feed.read_bytes()).hexdigest()
            check(f"[{mode}] raport policzony z bieżącego JSONL", same)
            counts[f"{mode}_campaigns"] = len(rep.get("campaigns", []))
            counts[f"{mode}_edges"] = len(rep.get("edges", []))
            counts[f"{mode}_unassigned"] = len(rep.get("unassigned", []))
            counts[f"{mode}_backend"] = rep.get("clustering_backend")

    ok = all(c[1] for c in checks)
    out = {"ok": ok, "state_dir": str(state), "config": str(base_file), "counts": counts,
           "checks": [{"name": n, "ok": o, "detail": d} for n, o, d in checks]}
    (state / "e2e-summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + json.dumps(counts, ensure_ascii=False, indent=2))
    print(f"\n{'WYNIK: OK' if ok else 'WYNIK: BŁĄD'} — {sum(c[1] for c in checks)}/{len(checks)} sprawdzeń; "
          f"szczegóły: {state / 'e2e-summary.json'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
