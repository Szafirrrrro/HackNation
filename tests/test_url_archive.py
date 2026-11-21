import base64
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import gzip
import os
from pathlib import Path
import socket
import subprocess
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from scamgraph.capture import capture, read_json, verified
from scamgraph.landing import Document
from scamgraph.discovery import landing_fetch, landing_visit

GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==")
HTML = b'''<!doctype html><base href="/offer/"><link rel="stylesheet" href="style/main">
<img src="a/same" srcset="a/same 1x, b/same 2x"><img src="b/same">
<div style="background-image:url(a/same)">Offer</div>
<a href="next">Next</a><form action="order"><input name="test"><button>Send</button></form>
<div style="height:2400px"></div><img id="lazy"><script src="code"></script>'''
SCRIPT = b"""document.body.dataset.rendered='yes';addEventListener('scroll',()=>{
document.querySelector('#lazy').src='lazy-image';},{once:true});fetch('data?q=1&q=2');"""
CSS = b""".broken{background:url(http://[)}.a{background:url('../offer/a/same')}.b{background:url(../offer/b/same)}"""


@contextmanager
def website():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            responses = {"/start": (302, "text/plain", b"Redirect"),
                         "/offer/page": (200, "text/html", HTML),
                         "/short": (200, "text/html", b"<p>Short body</p>"),
                         "/denied": (403, "text/html;charset=utf-8", b"<h1>Access denied</h1>"),
                         "/post": (200, "text/html", b"<script>fetch('/order',{method:'POST',body:'tracking'})</script>"),
                         "/broken": (200, "text/html", b'<img src="/missing"><p>Still here</p>'),
                         "/offer/style/main": (302, "text/plain", b"Moved"),
                         "/styles/main.css": (200, "text/css", CSS),
                         "/offer/code": (200, "text/javascript", SCRIPT),
                         "/offer/data": (200, "application/json", b'{"ok":true}'),
                         "/offer/a/same": (200, "image/gif", GIF),
                         "/offer/b/same": (200, "image/gif", GIF),
                         "/offer/lazy-image": (200, "image/gif", GIF)}
            status, mime, body = responses.get(urlsplit(self.path).path, (404, "text/plain", b"No image"))
            self.send_response(status)
            if status == 302:
                self.send_header("Location", "/styles/main.css" if self.path == "/offer/style/main" else "/offer/page")
            if self.path == "/short":
                self.send_header("Content-Length", str(len(body) + 100))
            if self.path == "/denied":
                self.send_header("Content-Type", "text/html")
            if self.path.startswith("/offer/data?"):
                body = gzip.compress(body)
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Type", mime)
            self.send_header("X-Fixture", "recorded")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        resolver = socket.getaddrinfo
        pool = landing_fetch.urllib3.HTTPConnectionPool
        # Substitute only the socket destination of this fixture's validated public hostname.
        try:
            with patch.object(landing_fetch.socket, "getaddrinfo", side_effect=lambda host, port, *args, **kw:
                              resolver("93.184.216.34" if host == "fixture.test" else host, port, *args, **kw)), patch.object(
                    landing_fetch.urllib3, "HTTPConnectionPool", side_effect=lambda ip, port: pool("127.0.0.1", server.server_port)):
                yield requests
        finally:
            server.shutdown()
            thread.join()


class URLArchiveTests(unittest.TestCase):
    def test_worker_reserves_export_time_within_the_supplied_timeout(self):
        def worker(cmd, *, timeout, **kwargs):
            deadline = float(cmd[cmd.index("--network-deadline") + 1])
            self.assertGreater(deadline, 100)
            self.assertLess(deadline, 100 + timeout)
            if timeout == 22:
                self.assertEqual(deadline, 116)
            return subprocess.CompletedProcess(cmd, 0, '{"status":"partial"}')

        with tempfile.TemporaryDirectory() as tmp, patch.object(landing_visit, "monotonic", return_value=100), \
                patch.object(subprocess, "run", side_effect=worker):
            for timeout in (22, 3):
                landing_visit.visit(Path(tmp), "https://fixture.test", timeout)

    @unittest.skipUnless(os.environ.get("SCAMGRAPH_TEST_CHROME"), "Lokalny Chrome")
    def test_denial_with_repeated_html_headers_preserves_document(self):
        with tempfile.TemporaryDirectory() as tmp, website():
            folder = Path(tmp)
            result = landing_visit.gather(folder, "http://fixture.test/denied")
            self.assertEqual(result["status"], "partial")
            self.assertIn("Dokument zwrócił HTTP 403.", result["issues"])
            self.assertIn("Access denied", (folder / "page.html").read_text(encoding="utf8"))
            self.assertTrue((folder / "screenshot.png").is_file())
            entry = read_json(folder / "network.har")["log"]["entries"][result["document_entry"]]
            self.assertEqual(entry["response"]["status"], 403)
            self.assertEqual([h["value"] for h in entry["response"]["headers"] if h["name"].lower() == "content-type"],
                             ["text/html", "text/html;charset=utf-8"])

    @unittest.skipUnless(os.environ.get("SCAMGRAPH_TEST_CHROME"), "Lokalny Chrome")
    def test_one_session_through_wire_to_offline_import(self):
        with tempfile.TemporaryDirectory() as tmp, website() as requests:
            folder = Path(tmp) / "visit"
            url = "http://fixture.test/start?ref=private"
            result = landing_visit.gather(folder, url)
            self.assertEqual(result["issues"], [])
            metadata = read_json(folder / "metadata.json")
            self.assertEqual((metadata["input_url"], metadata["final_url"], metadata["status"]),
                             (url, "http://fixture.test/offer/page", "success"))
            html = (folder / "page.html").read_text(encoding="utf8")
            self.assertIn(url, html)
            self.assertIn('data-rendered="yes"', html)
            nodes = Document(html).nodes
            get = lambda tag: next(n for n in nodes if n.tag == tag)
            self.assertEqual(get("a").attr("href"), "http://fixture.test/offer/next")
            self.assertEqual(get("form").attr("action"), "http://fixture.test/offer/order")
            self.assertEqual(get("input").attr("name"), "test")
            self.assertEqual((folder / get("script").attr("src")).read_bytes(), SCRIPT)
            images = [n.attr("src") for n in nodes if n.tag == "img"]
            self.assertEqual(len(set(images)), 3)
            self.assertTrue(all((folder / p).read_bytes() == GIF for p in images))
            self.assertEqual(get("img").attr("srcset"), f"{images[0]} 1x, {images[1]} 2x")
            css = (folder / get("link").attr("href")).read_text(encoding="utf8")
            for p in images[:2]:
                self.assertIn("./" + Path(p).name, css)
            self.assertIn(images[0], get("div").attr("style"))
            log = read_json(folder / "network.har")["log"]
            self.assertEqual(log["version"], "1.2")
            self.assertEqual(len(requests), len(log["entries"]))
            self.assertEqual(log["entries"][0]["response"]["content"]["text"], "Redirect")
            for e in log["entries"]:
                self.assertEqual(e["pageref"], log["pages"][0]["id"])
                self.assertIn("text", e["response"]["content"])
                self.assertIn({"name": "X-Fixture", "value": "recorded"}, e["response"]["headers"])
            api = next(e for e in log["entries"] if "/data?" in e["request"]["url"])
            self.assertEqual([v["value"] for v in api["request"]["queryString"]], ["1", "2"])
            self.assertEqual(json.loads(api["response"]["content"]["text"]), {"ok": True})
            for e in log["entries"]:
                body = e["response"]["content"]
                if body["mimeType"] == "image/gif":
                    self.assertEqual(body["encoding"], "base64")
                    self.assertEqual(base64.b64decode(body["text"]), GIF)
            self.assertNotIn("/offer/order", requests)
            from PIL import Image
            with Image.open(folder / "screenshot.png") as im:
                self.assertEqual(im.size, tuple(metadata["viewport"][k] for k in ("width", "height")))
            imported = capture(folder, Path(tmp) / "captures")
            manifest = read_json(imported / "manifest.json")
            verified(imported, manifest)
            self.assertEqual(manifest["source_observed_at"], metadata["captured_at"])
            analysis = read_json(imported / "extracted.json")
            self.assertIsNone(analysis["ad"])
            self.assertFalse(analysis["ad_page_links"])
            self.assertEqual(len(analysis["networks"]), 1)
            self.assertTrue(manifest["availability"]["landing_screenshot"]["available"])

    @unittest.skipUnless(os.environ.get("SCAMGRAPH_TEST_CHROME"), "Lokalny Chrome")
    def test_partial_keeps_error_response_and_remote_reference(self):
        with tempfile.TemporaryDirectory() as tmp, website():
            root = Path(tmp)
            result = landing_visit.gather(root, "http://fixture.test/broken")
            self.assertEqual(result["status"], "partial")
            self.assertTrue((root / "screenshot.png").is_file())
            self.assertIn('src="http://fixture.test/missing"', (root / "page.html").read_text(encoding="utf8"))
            entries = read_json(root / "network.har")["log"]["entries"]
            self.assertEqual(entries[-1]["response"]["content"]["text"], "No image")
            self.assertEqual(entries[-1]["response"]["status"], 404)

    @unittest.skipUnless(os.environ.get("SCAMGRAPH_TEST_CHROME"), "Lokalny Chrome")
    def test_short_response_and_blocked_post_are_partial(self):
        with tempfile.TemporaryDirectory() as tmp, website() as requests:
            for path in ("short", "post"):
                folder = Path(tmp) / path
                report = landing_visit.gather(folder, "http://fixture.test/" + path)
                self.assertEqual(report["status"], "partial")
                entries = read_json(folder / "network.har")["log"]["entries"]
                if path == "short":
                    self.assertIn("Short body", entries[0]["response"]["content"]["text"])
                    self.assertEqual(entries[0]["response"]["status"], 200)
                    self.assertIn("Niepełna", entries[0]["_error"])
                else:
                    post, = [e for e in entries if e["request"]["method"] == "POST"]
                    self.assertEqual(post["request"]["postData"]["text"], "tracking")
                    self.assertIn("_error", post)
            self.assertNotIn("/order", requests)

    def test_completed_archive_survives_timeout_before_worker_exits(self):
        def complete_then_timeout(cmd, **kwargs):
            folder = Path(cmd[-1])
            metadata = landing_visit.initial("https://fixture.test/")
            report = {"document_entry": 0}
            (folder / "page.html").write_text("<html></html>")
            (folder / "screenshot.png").write_bytes(GIF)
            reads = landing_fetch.PageReads(1)
            reads.record(metadata["input_url"], "GET", [], metadata["captured_at"], 2, status=200, body=b"ok")
            landing_visit.finish(folder, metadata, report, reads.entries, [], worker=True)
            raise subprocess.TimeoutExpired(cmd, 1)
        with tempfile.TemporaryDirectory() as tmp, patch.object(subprocess, "run", side_effect=complete_then_timeout):
            result = landing_visit.visit(Path(tmp), "https://fixture.test")
            self.assertEqual(result["status"], "success")
            log = read_json(Path(tmp) / result["page_id"] / "network.har")["log"]
            self.assertEqual(len(log["entries"]), 1)

    def test_timeout_keeps_journal_and_assets_for_each_attempt(self):
        def stop(cmd, **kwargs):
            target = Path(cmd[-1])
            (target / "page_files/asset.bin").write_bytes(b"abc")
            reads = landing_fetch.PageReads(1, target / ".entries.jsonl")
            reads.record("https://fixture.test", "GET", [], "2026-01-01T00:00:00Z", 5, status=200, body=b"abc")
            reads.record("https://fixture.test/img", "GET", [], "2026-01-01T00:00:01Z", 0, pending=True,
                         error="Przerwano oczekiwanie na odpowiedź.")
            with (target / ".entries.jsonl").open("ab") as stream:
                stream.write(b'{"interrupted":')
            raise subprocess.TimeoutExpired(cmd, 1)
        with tempfile.TemporaryDirectory() as tmp, patch.object(subprocess, "run", side_effect=stop):
            store = Path(tmp)
            for _ in range(2):
                result = landing_visit.visit(store, "https://fixture.test", timeout=1)
                folder = store / result["page_id"]
                self.assertEqual(result["status"], "partial")
                self.assertEqual((folder / "page_files/asset.bin").read_bytes(), b"abc")
                self.assertEqual(len(read_json(folder / "network.har")["log"]["entries"]), 2)
                self.assertTrue(read_json(folder / "metadata.json")["errors"])
            self.assertEqual(len(list(store.iterdir())), 2)
