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
from .cta import target_identity
from .diagnostic import playwright_api
from .landing_content import MIME_FILES, file_format, html_content
from .landing_fetch import DocumentTimeout, LandingError, PageReads, TrustedDestination, public_url, validate_url
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


def capture_viewport(page, directory, api, issues):
    try:
        image = page.screenshot(timeout=2200, animations="disabled")
        (directory / "screenshot.tmp").write_bytes(image)
        (directory / "screenshot.tmp").replace(directory / "screenshot.png")
    except api.Error:
        issues.add("Chrome nie zapisał widocznego obszaru strony.")


def capture_views(page, directory, api, issues, report):
    if not (directory / "screenshot.png").is_file():
        capture_viewport(page, directory, api, issues)
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


def render(directory, input_url, final_url, document, reads, report, issues, *, document_only=False):
    api = playwright_api()
    local, styles = {}, {}
    served = False
    with api.sync_playwright() as driver, driver.chromium.launch(channel="chrome", headless=True,
            chromium_sandbox=True, timeout=6000, args=["--disable-background-networking",
            "--host-resolver-rules=MAP * ~NOTFOUND", "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"]) as browser:
        context = browser.new_context(offline=True, viewport=VIEWPORT, service_workers="block", accept_downloads=False,
                                      java_script_enabled=not document_only,
                                      record_har_path=directory / ".browser.har", record_har_mode="full",
                                      record_har_content="embed")
        page = context.new_page()
        def websocket(ws):
            issues.add("Pominięto połączenie WebSocket.")
            ws.close()
        context.route_web_socket("**/*", websocket)

        def route(r):
            nonlocal served
            req = r.request
            try:
                if document_only and not req.is_navigation_request():
                    r.abort()
                    return
                if req.method != "GET" or (req.is_navigation_request() and (served or req.frame != page.main_frame)):
                    reason = "Zablokowano dodatkową nawigację lub żądanie inne niż GET."
                    reads.blocked(req, reason)
                    issues.add(reason)
                    r.abort()
                    return
                if req.is_navigation_request():
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
                r.abort()

        context.route("**/*", route)
        try:
            page.goto(final_url, wait_until="domcontentloaded", timeout=8000)
        except api.Error:
            if served:
                issues.add("Upłynął czas wczytywania dokumentu.")
        if not served:
            raise LandingError("Brak wyrenderowanego dokumentu.")
        # Keep a real DOM even if the worker runs out of time during lazy loading.
        save_dom(page, directory, input_url, local, styles, issues)
        if document_only:
            capture_viewport(page, directory, api, issues)
        else:
            capture_views(page, directory, api, issues, report)
            save_dom(page, directory, input_url, local, styles, issues)
        timings = page.evaluate("""() => {const n=performance.getEntriesByType('navigation')[0];
            return n ? {onContentLoad:n.domContentLoadedEventEnd || -1, onLoad:n.loadEventEnd || -1} : {}}""")
        info = {"title": page.title(), "pageTimings": timings}
        context.close()  # Flush the browser trace before reconciling the pinned HTTP exchanges.
        return info


def browser_entries(directory, entries, issues, document_entry):
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
    for i, entry in enumerate(entries):
        req = entry["request"]
        matches = by_request[(req["method"], req["url"])]
        if i == document_entry:
            matches.appendleft(entry)
        else:
            matches.append(entry)
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
    browser_entries(directory, entries, issues, report.get("document_entry"))
    errors = sorted(issues)
    log_page = {"startedDateTime": metadata["captured_at"], "id": PAGE_ID, "title": "",
                "pageTimings": {}, **(page_info or {})}
    atomic_json(directory / "network.har", {"log": {"version": "1.2", "creator": {"name": "ScamGraph", "version": "2"},
                                                  "pages": [log_page], "entries": entries}})
    rendered = (directory / "page.html").is_file()
    complete = rendered and (directory / "screenshot.png").is_file() and "document_entry" in report
    received = any(entry["response"]["status"] > 0 for entry in entries)
    status = "partial" if rendered or received else "failed"
    binary = report.get("original_file") and report.get("target_kind") in {"pdf", "image", "audio", "video"}
    if not errors and (complete or binary and report.get("content_status") == "usable"):
        status = "success"
    report.setdefault("content_status", "error")
    report.setdefault("reason_code", "worker_error")
    metadata.update(status=status, errors=errors)
    for field in ("document_entry", "http_status", "target_kind", "content_status", "reason_code", "reason",
                  "content_evidence", "original_file", "document_attempts"):
        if field in report:
            metadata[field] = report[field]
    atomic_json(directory / "metadata.json", metadata)
    report.update(status="trusted_domain" if report.get("trusted_domain") else status, issues=errors)
    if worker:
        atomic_json(directory / ".finished.json", report)
    clear_temporary(directory)
    return report


def fetch_document(reads, url, report):
    for attempt in (1, 2):
        report["document_attempts"] = attempt
        try:
            final_url, mime, body, headers = reads.get(url, document=True)
        except DocumentTimeout:
            if attempt == 2 or monotonic() >= reads.deadline:
                raise
            continue
        entry = reads.entries[-1]
        status = entry["response"]["status"]
        if 500 <= status < 600 and attempt == 1 and monotonic() < reads.deadline:
            continue
        report.update(document_entry=len(reads.entries) - 1, http_status=status,
                      final_url=public_url(final_url), observed_at=entry["startedDateTime"])
        return final_url, (mime, body, headers)


def record_document(directory, expected, final_url, document, report):
    mime, body, _ = document
    mime = mime.partition(";")[0].strip().lower()
    status = report["http_status"]
    html = mime in {"text/html", "application/xhtml+xml"}
    report["content_status"], report["reason_code"] = "error", "invalid_document"
    parsed = urlsplit(final_url)
    final_kind = target_identity(final_url)[0]
    access_route = parsed.path.rstrip("/") if final_kind.startswith("facebook_") else ""
    if access_route == "/unsupportedbrowser":
        report.update(content_status="blocked", reason_code="client_unsupported")
    elif status in {401, 403, 407, 429, 451} or re.match(r"^/(?:login(?:\.php)?|checkpoint)(?:/|$)", access_route):
        report.update(content_status="blocked", reason_code="access_denied")
    elif status in {404, 410}:
        report.update(content_status="unavailable", reason_code="http_unavailable")
    elif not 200 <= status < 300 or status == 206:
        report["reason_code"] = "http_error" if status != 206 else "incomplete_response"
    if not body:
        return False
    if html:
        if expected[0].startswith("facebook_"):
            report["target_kind"] = expected[0]
        else:
            report["target_kind"] = final_kind if final_kind.startswith("facebook_") else "web"
        extension = "html"
    else:
        hint = final_kind if final_kind in {"pdf", "image", "audio", "video"} else expected[0]
        file = file_format(mime or "application/octet-stream", body, hint)
        if file is None:
            if status == 200:
                report.update(content_status="error" if mime in MIME_FILES else "unsupported",
                              reason_code="invalid_file" if mime in MIME_FILES else "unsupported_mime")
            return False
        report["target_kind"], extension = file
        if status == 200:
            if expected[0].startswith("facebook_"):
                report["reason_code"] = "target_mismatch"
            else:
                report.update(content_status="usable", reason_code=None)
    relative = f"original/response.{extension}"
    (directory / relative).parent.mkdir(exist_ok=True)
    (directory / relative).write_bytes(body)
    report["original_file"] = f"landing/{relative}"
    if html and report["reason_code"] == "invalid_document":
        report["content_status"], report["reason_code"], report["content_evidence"] = html_content(
            directory / relative, report["original_file"], final_url, expected)
    elif report["content_status"] == "usable":
        report["content_evidence"] = {"file": report["original_file"]}
    return html


def recover_dom_content(directory, url, metadata, report):
    dom = directory / "page.html"
    if report.get("reason_code") not in {"content_missing", "unverified_facebook_object"} or not dom.is_file():
        return
    report["content_status"], report["reason_code"], report["content_evidence"] = html_content(
        dom, "landing/page.html", metadata["final_url"], target_identity(url))
    if report["content_status"] == "usable":
        report.pop("reason", None)


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
        expected = target_identity(url)
        report.update(url=public_url(url), target_kind=expected[0])
        final_url, document = fetch_document(reads, url, report)
        metadata["final_url"] = final_url
        html = record_document(directory, expected, final_url, document, report)
        if report["http_status"] >= 400:
            report["reason"] = f"Dokument zwrócił HTTP {report['http_status']}."
            issues.add(report["reason"])
        atomic_json(directory / ".progress.json", {"metadata": metadata, "report": report})
        if html and report["http_status"] != 206:
            document_only = report["http_status"] != 200 or report["content_status"] in {"blocked", "unavailable", "unsupported"}
            info = render(directory, url, final_url, document, reads, report, issues, document_only=document_only)
    except Exception as exc:
        reason = report.get("reason") or (str(exc) if isinstance(exc, LandingError)
                                           else f"Nie ukończono renderowania ({type(exc).__name__}).")
        issues.add(reason)
        if isinstance(exc, TrustedDestination):
            report.update(trusted_domain=exc.host, content_status="skipped", reason_code="trusted_domain")
        if isinstance(exc, DocumentTimeout):
            report["reason_code"] = "document_timeout"
        if report.get("content_status") != "usable" and not report.get("reason"):
            report["reason"] = reason
        if "http_status" not in report and reads.entries:
            report["http_status"] = reads.entries[-1]["response"]["status"] or None
    recover_dom_content(directory, url, metadata, report)
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
        recover_dom_content(directory, url, metadata, report)
        if report.get("content_status") != "usable":
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
