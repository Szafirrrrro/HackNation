"""Measure the first document response for a single Meta search in Chrome."""
from datetime import datetime, timezone
from importlib.util import find_spec
import json
from pathlib import Path
import re
import subprocess
import sys

from .meta import search_url
from .engine import connection, iso
from .service import load_config
from .types import Query


def last_live_run(state_dir, source, phrase, country):
    path = Path(state_dir) / "discovery.sqlite3"
    if not path.is_file():
        return None
    with connection(path) as db:
        row = db.execute("""
            SELECT r.run_id, r.started, r.status, r.trigger, r.phrase, r.error,
                   count(o.seq) AS cards, o.country,
                   group_concat(DISTINCT json_extract(o.card, '$.main_document_http_status')) AS http
            FROM runs r LEFT JOIN observations o ON o.run_id = r.run_id AND o.phrase = :phrase
            WHERE r.source_id = :source AND r.mode = 'live'
              AND (o.country = :country OR (o.seq IS NULL AND r.phrase = :phrase))
            GROUP BY r.run_id ORDER BY r.started DESC LIMIT 1
        """, {"source": source, "phrase": phrase, "country": country}).fetchone()
    return {**dict(row), "started": iso(row["started"])} if row else None


def enabled(options):
    permission = options.get("permission")
    return options.get("mode") == "live" and isinstance(permission, str) and bool(permission.strip())


def playwright_api():
    if find_spec("playwright") is None:
        runtime = Path(__file__).resolve().parents[2] / ".private-discovery" / "playwright-runtime"
        if runtime.is_dir() and str(runtime) not in sys.path:
            sys.path.append(str(runtime))
    from playwright import sync_api
    return sync_api


def first_status(page, url):
    # Intercept headers before Chrome follows a redirect or executes the page.
    session = page.context.new_cdp_session(page)
    frame = session.send("Page.getFrameTree")["frameTree"]["frame"]["id"]
    status = None

    def stop_document(event):
        nonlocal status
        if event["frameId"] == frame and event["request"]["url"] == url:
            status = event.get("responseStatusCode")
        session.send("Fetch.failRequest", {"requestId": event["requestId"], "errorReason": "Aborted"})

    session.on("Fetch.requestPaused", stop_document)
    session.send("Fetch.enable", {"patterns": [{"urlPattern": "*", "resourceType": "Document",
                                                "requestStage": "Response"}]})
    from playwright.sync_api import Error
    try:
        page.goto(url, wait_until="commit", timeout=15000)
    except Error:
        if status is None:
            raise
    return status


def measure(config_file, phrase):
    config = load_config(config_file)
    options = next((s for s in config["sources"].values() if s["provider"] == "meta-ad-library"), {})
    phrase = phrase.strip()
    if not 1 <= len(phrase) <= 200:
        raise ValueError("Wpisz frazę od 1 do 200 znaków.")
    if not enabled(options):
        raise ValueError("Pomiar wymaga trybu live i skonfigurowanego uprawnienia Meta.")
    query = Query(phrase, options["country"], 1)
    url = search_url(query)
    result = {"phrase": phrase, "country": query.country, "url": url,
              "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "http_status": None}
    try:
        api = playwright_api()
    except ImportError:
        return {**result, "error": "Brak lokalnej instalacji Playwright."}
    phase = "Uruchamianie Chrome"
    try:
        with api.sync_playwright() as driver:
            with driver.chromium.launch(channel="chrome", headless=False, timeout=12000) as browser:
                page = browser.new_page(java_script_enabled=False, service_workers="block", accept_downloads=False)
                phase = "Odczyt nagłówków dokumentu"
                result["http_status"] = first_status(page, url)
    except api.Error as exc:
        code = re.search(r"net::ERR_[A-Z0-9_]+", str(exc))
        result["error"] = f"{phase} · {code[0] if code else type(exc).__name__}"
    return result


def run_diagnostic(config_file, phrase):
    # Streamlit's Windows event loop cannot launch Playwright subprocesses.
    try:
        process = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", __spec__.name, str(Path(config_file).resolve()), phrase],
            cwd=Path(__file__).resolve().parents[2], capture_output=True, encoding="utf8", timeout=40,
        )
        if process.returncode == 0:
            return json.loads(process.stdout)
    except subprocess.TimeoutExpired:
        return {"error": "Pomiar przekroczył limit 40 s."}
    except (OSError, ValueError):
        pass
    return {"error": "Proces diagnostyczny zakończył się bez czytelnego wyniku."}


if __name__ == "__main__":
    try:
        result = measure(*sys.argv[1:])
    except (OSError, ValueError, KeyError) as exc:
        result = {"error": str(exc) if isinstance(exc, ValueError) else type(exc).__name__}
    print(json.dumps(result))
