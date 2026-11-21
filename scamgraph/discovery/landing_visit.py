"""One isolated, bounded CTA visit. All browser HTTP is mediated by PageReads."""
import argparse
import base64
from collections import defaultdict, deque
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
from time import monotonic
from urllib.parse import urlsplit
from uuid import uuid4

from tinycss2.bytes import decode_stylesheet_bytes
from urllib3.exceptions import HTTPError

from ..capture import read_json, write_json
from .diagnostic import playwright_api
from .landing_fetch import LandingError, PageReads, TrustedDestination, public_url, validate_url
from .page_archive import asset_name, rewrite_css, save_dom

VIEWPORT = {"width": 1280, "height": 720}
PAGE_ID = "page_1"
WORKER_MODULE = "scamgraph.discovery.landing_visit"
VISIT_TIMEOUT = 22
EXPORT_RESERVE = 6


def atomic_json(path, value):
    tmp = path.with_suffix(".tmp")
    write_json(tmp, value)
    tmp.replace(path)


def capture_views(page, directory, api, issues, report):
    try:
        for _ in range(16):
            if not page.evaluate("() => {const y=scrollY; scrollBy(0, innerHeight); return scrollY!==y}"):
                break
            page.wait_for_timeout(90)
        else:
            if page.evaluate("() => scrollY + innerHeight < document.documentElement.scrollHeight"):
                issues.add("Osiągnięto limit przewijania strony.")
        page.evaluate("() => scrollTo(0, 0)")
        page.wait_for_timeout(150)
        page.wait_for_load_state("networkidle", timeout=2000)
    except api.Error:
        issues.add("Zapisano widok przed zakończeniem ładowania po przewinięciu.")
    try:
        image = page.screenshot(timeout=2200, animations="disabled")
        (directory / "screenshot.tmp").write_bytes(image)
        (directory / "screenshot.tmp").replace(directory / "screenshot.png")
    except api.Error:
        issues.add("Chrome nie zapisał widocznego obszaru strony.")
    try:
        width, height = page.evaluate("""() => [Math.max(innerWidth,document.documentElement.scrollWidth),
            Math.max(innerHeight,document.documentElement.scrollHeight,document.body?.scrollHeight || 0)]""")
        w = min(width, 8192)
        h = min(height, 16000, 24_000_000 // w)
        clipped = w < width or h < height
        name = "page-partial.png" if clipped else "screenshot_full.png"
        session = page.context.new_cdp_session(page)
        try:
            response = session.send("Page.captureScreenshot", {"format":"png", "captureBeyondViewport":True,
                                    "clip":{"x":0, "y":0, "width":w, "height":h, "scale":1}})
        finally:
            session.detach()
        image = base64.b64decode(response["data"], validate=True)
        (directory / "full.tmp").write_bytes(image)
        (directory / "full.tmp").replace(directory / name)
        report["page_screenshot"] = {"path": "landing/" + name, "complete": not clipped,
                                     "width": w, "height": h, "document_width": width, "document_height": height}
    except (api.Error, ValueError):
        pass  # Optional image. The required viewport has its own status above.


def render(directory, input_url, reads, metadata, report, issues):
    api = playwright_api()
    local, styles = {}, {}
    document = None
    final_url = None
    served = False
    with api.sync_playwright() as driver, driver.chromium.launch(channel="chrome", headless=True,
            chromium_sandbox=True, timeout=6000, args=["--disable-background-networking",
            "--host-resolver-rules=MAP * ~NOTFOUND", "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"]) as browser:
        context = browser.new_context(offline=True, viewport=VIEWPORT, service_workers="block", accept_downloads=False,
                                      record_har_path=directory / ".browser.har", record_har_mode="full",
                                      record_har_content="embed")
        page = context.new_page()
        def websocket(ws):
            issues.add("Pominięto połączenie WebSocket.")
            ws.close()
        context.route_web_socket("**/*", websocket)

        def route(r):
            nonlocal served, document, final_url
            req = r.request
            try:
                if req.method != "GET" or (req.is_navigation_request() and (served or req.frame != page.main_frame)):
                    reason = "Zablokowano dodatkową nawigację lub żądanie inne niż GET."
                    reads.blocked(req, reason)
                    issues.add(reason)
                    r.abort()
                    return
                if req.is_navigation_request():
                    if document is None:
                        final_url, mime, data, headers = reads.get(req.url, browser_headers=req.headers_array(), document=True)
                        metadata["final_url"] = final_url
                        status = reads.entries[-1]["response"]["status"]
                        if status >= 400:
                            issues.add(f"Dokument zwrócił HTTP {status}.")
                        if mime.partition(";")[0].lower().strip() not in {"text/html", "application/xhtml+xml"}:
                            raise LandingError("Cel CTA nie zwrócił dokumentu HTML.")
                        document = (mime, data, headers)
                        entry = len(reads.entries) - 1
                        report.update(final_url=public_url(final_url), document_entry=entry,
                                      observed_at=reads.entries[entry]["startedDateTime"])
                        (directory / "original").mkdir()
                        (directory / "original/response.html").write_bytes(data)
                        atomic_json(directory / ".progress.json", {"metadata": metadata, "report": report})
                        if req.url != final_url:
                            # Keep this frame idle while moving to the final URL of the pinned transport.
                            r.fulfill(status=204, body="")
                            return
                    served = True
                    mime, data, headers = document
                else:
                    origin = req.header_value("origin")
                    doc = urlsplit(final_url)
                    doc_origin = f"{doc.scheme}://{doc.netloc}"
                    if not origin and req.resource_type in {"xhr", "fetch"} and not req.url.startswith(doc_origin + "/"):
                        origin = doc_origin
                    final, mime, data, headers = reads.get(req.url, origin, resource=True, browser_headers=req.headers_array())
                    name = asset_name(final, mime, data)
                    (directory / "page_files" / name).write_bytes(data)
                    reads.entries[-1]["response"]["content"]["_localFile"] = "page_files/" + name
                    if origin and origin != f"{urlsplit(final).scheme}://{urlsplit(final).netloc}":
                        if headers.get("Access-Control-Allow-Origin") not in {origin, "*"}:
                            raise LandingError("Serwer zasobu nie udostępnił odpowiedzi tej stronie (CORS).")
                    local[req.url] = local[final] = name
                    if mime.partition(";")[0].strip().lower() == "text/css":
                        charset = re.search(r"""charset\s*=\s*["']?([\w.-]+)""", mime, re.I)
                        encoding = charset[1] if charset else None
                        styles[name] = (final, data, encoding)
                        if final != req.url:
                            # Chrome received a fulfilled route, so supply the stylesheet\'s final base URL.
                            source, _ = decode_stylesheet_bytes(data, protocol_encoding=encoding)
                            data = rewrite_css(source, final, {}, "").encode("utf8")
                            mime = "text/css; charset=utf-8"
                render_headers = {k: headers[k] for k in ("Access-Control-Allow-Origin", "Access-Control-Allow-Credentials",
                                  "Cross-Origin-Resource-Policy", "Content-Security-Policy") if k in headers}
                if req.is_navigation_request():
                    policies = [render_headers.get("Content-Security-Policy"),
                                "frame-src 'none'; object-src 'none'; worker-src 'none'; form-action 'none'"]
                    render_headers["Content-Security-Policy"] = ", ".join(p for p in policies if p)
                r.fulfill(status=reads.entries[report["document_entry"] if req.is_navigation_request() else -1]["response"]["status"],
                          body=data, content_type=mime or "application/octet-stream", headers=render_headers)
            except (OSError, ValueError, RuntimeError, api.Error, HTTPError) as exc:
                reason = str(exc) if isinstance(exc, LandingError) else f"Błąd odczytu ({type(exc).__name__})."
                issues.add(reason)
                if req.is_navigation_request() and not served:
                    report["reason"] = reason
                    if isinstance(exc, TrustedDestination):
                        report["trusted_domain"] = exc.host
                        atomic_json(directory / ".progress.json", {"metadata": metadata, "report": report})
                r.abort()

        context.route("**/*", route)
        try:
            page.goto(input_url, wait_until="domcontentloaded", timeout=8000)
        except api.Error:
            if not document:
                raise
            if served:
                issues.add("Upłynął czas wczytywania dokumentu.")
        if document and not served:
            page.goto(final_url, wait_until="domcontentloaded", timeout=8000)
        if not served:
            raise LandingError("Brak wyrenderowanego dokumentu.")
        # Keep a real DOM even if the worker runs out of time during lazy loading.
        save_dom(page, directory, input_url, local, styles, issues)
        capture_views(page, directory, api, issues, report)
        save_dom(page, directory, input_url, local, styles, issues)
        metadata["final_url"] = page.url
        timings = page.evaluate("""() => {const n=performance.getEntriesByType('navigation')[0];
            return n ? {onContentLoad:n.domContentLoadedEventEnd || -1, onLoad:n.loadEventEnd || -1} : {}}""")
        info = {"title": page.title(), "pageTimings": timings}
        context.close()  # Flush the browser trace before reconciling the pinned HTTP exchanges.
        return info


def browser_entries(directory, entries, issues):
    """Keep wire responses and redirects; add browser-only attempts and browser timings."""
    path = directory / ".browser.har"
    if not path.is_file():
        return
    try:
        browser_log = read_json(path)["log"]
    except (OSError, ValueError, KeyError):
        issues.add("Nie ukończono śladu przeglądarki.")
        return
    by_request = defaultdict(deque)
    for entry in entries:
        req = entry["request"]
        by_request[(req["method"], req["url"])].append(entry)
    for entry in browser_log["entries"]:
        req = entry["request"]
        matches = by_request[(req["method"], req["url"])]
        if matches:
            wire = matches.popleft()
            wire["request"]["_browserHeaders"] = req["headers"]
            wire["_browserTimings"] = entry["timings"]
            continue
        entry["pageref"] = PAGE_ID
        entries.append(entry)
        if entry["response"]["status"] <= 0 or "text" not in entry["response"]["content"]:
            issues.add("Przeglądarka zarejestrowała żądanie bez treści odpowiedzi.")


def initial(url):
    return {"input_url": url, "final_url": None, "captured_at": datetime.now(timezone.utc).isoformat(),
            "status": "failed", "errors": [], "viewport": dict(VIEWPORT)}


def finish(directory, metadata, report, entries, errors, page_info=None, *, worker=False):
    issues = set(errors)
    issues.update(e["_error"] for e in entries if e.get("_error") and e["response"]["status"] > 0)
    browser_entries(directory, entries, issues)
    errors = sorted(issues)
    log_page = {"startedDateTime": metadata["captured_at"], "id": PAGE_ID, "title": "",
                "pageTimings": {}, **(page_info or {})}
    atomic_json(directory / "network.har", {"log": {"version": "1.2", "creator": {"name": "ScamGraph", "version": "2"},
                                                  "pages": [log_page], "entries": entries}})
    rendered = (directory / "page.html").is_file()
    complete = rendered and (directory / "screenshot.png").is_file() and "document_entry" in report
    received = any(entry["response"]["status"] > 0 for entry in entries)
    status = "partial" if rendered or received else "failed"
    if complete and not errors:
        status = "success"
    metadata.update(status=status, errors=errors)
    if "document_entry" in report:
        metadata["document_entry"] = report["document_entry"]
    atomic_json(directory / "metadata.json", metadata)
    report.update(status="trusted_domain" if report.get("trusted_domain") else status, issues=errors)
    if worker:
        atomic_json(directory / ".finished.json", report)
    clear_temporary(directory)
    return report


def clear_temporary(directory):
    for name in (".progress.json", ".progress.tmp", ".entries.jsonl", ".pending.tmp", ".pending.json", ".browser.har", ".finished.tmp",
                 "screenshot.tmp", "full.tmp", "page.html.tmp"):
        (directory / name).unlink(missing_ok=True)


def gather(directory, url, *, worker=False, network_deadline=None, domain_db=None):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "page_files").mkdir(exist_ok=True)
    metadata = initial(url)
    atomic_json(directory / "metadata.json", metadata)
    seconds = VISIT_TIMEOUT - EXPORT_RESERVE if network_deadline is None else network_deadline - monotonic()
    reads = PageReads(seconds, directory / ".entries.jsonl", domain_db)
    report = {}
    issues = set()
    info = {}
    try:
        validate_url(url)
        report["url"] = public_url(url)
        info = render(directory, url, reads, metadata, report, issues)
    except Exception as exc:
        reason = report.get("reason") or (str(exc) if isinstance(exc, LandingError)
                                           else f"Nie ukończono renderowania ({type(exc).__name__}).")
        issues.add(reason)
        if not (directory / "page.html").is_file():
            report["reason"] = reason
    return finish(directory, metadata, report, reads.entries, issues, info, worker=worker)


def visit(store, url, timeout=VISIT_TIMEOUT, domain_db=None):
    directory = Path(store).resolve() / uuid4().hex
    directory.mkdir(parents=True)
    (directory / "page_files").mkdir()
    metadata = initial(url)
    atomic_json(directory / "metadata.json", metadata)
    try:
        reserve = min(EXPORT_RESERVE, timeout * EXPORT_RESERVE / VISIT_TIMEOUT)
        network_deadline = monotonic() + timeout - reserve
        policy_args = ["--domain-db", str(Path(domain_db).resolve())] if domain_db else []
        proc = subprocess.run([sys.executable, "-X", "utf8", "-m", WORKER_MODULE,
                               "--network-deadline", str(network_deadline), "--worker", str(directory), *policy_args],
                              input=json.dumps(url), cwd=Path(__file__).resolve().parents[2],
                              capture_output=True, encoding="utf8", timeout=timeout, check=True)
        report = json.loads(proc.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        reason = ("Upłynął limit czasu pobierania strony CTA." if isinstance(exc, subprocess.TimeoutExpired)
                  else "Proces zbierania strony CTA nie zakończył zapisu.")
        marker = directory / ".finished.json"
        if marker.is_file():
            report = read_json(marker)
            clear_temporary(directory)
            marker.unlink()
            return {**report, "page_id": directory.name}
        report = {}
        if (directory / ".progress.json").is_file():
            progress = read_json(directory / ".progress.json")
            metadata, report = progress["metadata"], progress["report"]
        entries = []
        if (directory / ".entries.jsonl").is_file():
            with (directory / ".entries.jsonl").open(encoding="utf8") as stream:
                for line in stream:
                    try:
                        entries.append(json.loads(line))
                    except ValueError:
                        break  # Last append may have been interrupted.
        pending = directory / ".pending.json"
        if pending.is_file():
            entry = read_json(pending)
            if entry.pop("_pendingIndex") == len(entries):
                entries.append(entry)
        report.setdefault("reason", reason)
        finish(directory, metadata, report, entries, [reason])
    (directory / ".finished.json").unlink(missing_ok=True)
    return {**report, "page_id": directory.name}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Zapisz prywatną paczkę dla każdego podanego URL-a HTTP(S).")
    parser.add_argument("urls", nargs="*")
    parser.add_argument("--store", type=Path, default=Path(".private-discovery/pages"))
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--network-deadline", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--domain-db", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(gather(args.worker, json.load(sys.stdin), worker=True, network_deadline=args.network_deadline,
                                domain_db=args.domain_db)))
    else:
        if not args.urls:
            parser.error("Podaj co najmniej jeden URL.")
        incomplete = False
        for url in args.urls:
            result = visit(args.store, url)
            print(result["status"], args.store / result["page_id"])
            incomplete |= result["status"] != "success"
        sys.exit(int(incomplete))
