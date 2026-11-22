import hashlib
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from scamgraph.capture import staging
from scamgraph.discovery import meta
from scamgraph.discovery.types import Query, SourceError
from scamgraph.landing import Document

QUERY = Query("fraza testowa", "PL", 10)
URL = meta.search_url(QUERY)
CARDS = """
<header>Biblioteka reklam</header><main role="feed">
<div><div><b>Aktywna</b></div><span>Identyfikator biblioteki:</span><span>4100001</span>
<div>5–13 października 2026</div><div><a href="/studio.test">Studio Test</a></div>
<div>Sponsorowane</div><p>Treść pierwszej karty.</p><img src="./cards_files/a.png">
<img src="https://example.test/external.png"><img src="./cards_files/../../b.png"></div>
<article><div>Inactive</div><span>Library ID: 4100002</span><div>Started running on Jan 2, 2026</div>
<a href="https://www.facebook.com/people/Other-Studio/22">Other Studio</a>
<p>This ad is unavailable because the account was disabled.</p>
<div hidden>Private text</div></article></main>
"""


class MetaPublicTests(unittest.TestCase):
    def setUp(self):
        sandbox = staging(Path(tempfile.gettempdir()))
        self.root = sandbox.__enter__()
        self.addCleanup(sandbox.__exit__, None, None, None)

    def html(self, body=CARDS):
        p = self.root / "cards.html"
        p.write_text(body, encoding="utf8")
        return p

    def test_live_and_manual_rendered_cards(self):
        p = self.html()
        (self.root / "cards_files").mkdir()
        (self.root / "cards_files/a.png").write_bytes(b"image")
        imported = list(meta.fetch({"mode":"import", "imports":{QUERY.phrase:p}}, QUERY))
        self.assertEqual([f.ad_ref for f in imported], ["4100001", "4100002"])
        first, removed = imported
        self.assertEqual((first.card["status"], first.card["page_name"], first.card["text"]),
                         ("Aktywna", "Studio Test", "Treść pierwszej karty."))
        self.assertEqual(first.card["daty_jak_na_karcie"], "5–13 października 2026")
        self.assertEqual(first.media, (self.root / "cards_files/a.png",))
        self.assertFalse(first.missing)
        self.assertEqual(removed.card["page_name"], "Other Studio")
        self.assertEqual(removed.card["creative_state"], "withdrawn")
        self.assertEqual(removed.card["removal_notice"], "This ad is unavailable because the account was disabled.")
        self.assertNotIn("text", removed.card)
        self.assertTrue(removed.missing)
        self.assertEqual(first.source_sha256, hashlib.sha256(p.read_bytes()).hexdigest())
        for f in imported:
            index = int(f.locator.split(":")[1])
            node = Document(p.read_text(encoding="utf8")).nodes[index-1]
            self.assertIn(f.ad_ref, node.words())
        # Mock transport only; normalization and evidence for both modes stay identical.
        with patch.object(meta, "_live", return_value=[(p, first.source_sha256, meta._parse_html(CARDS, QUERY), None)]):
            live = list(meta.fetch({"mode":"live", "permission":"test"}, QUERY))
        self.assertEqual([f.card for f in imported], [f.card for f in live])
        self.assertEqual(live[0].source_kind, "library")
        self.assertIsNotNone(live[0].observed_at)

    def test_manual_scope_empty_failure_and_changed_layout(self):
        p = self.html('<link rel="canonical" href="' + URL.replace("&", "&amp;") + '"><p>0 wyników</p>')
        self.assertEqual(list(meta.fetch({"mode":"import", "path":p}, QUERY)), [])
        with self.assertRaisesRegex(SourceError, "innego zapytania"):
            list(meta.fetch({"mode":"import", "path":p}, Query(QUERY.phrase,"DE",10)))
        p = self.html("<main>Tutaj pojawi się nowy układ.</main>")
        with self.assertRaisesRegex(SourceError, "Brak opisu zapytania"):
            list(meta.fetch({"mode":"import","path":p}, QUERY))
        with self.assertRaisesRegex(SourceError, "Nierozpoznany układ"):
            list(meta.fetch({"mode":"import","imports":{QUERY.phrase:p}}, QUERY))
        p = self.html("<script>Library ID: 99</script><p hidden>No results</p><main>Log in to continue</main>")
        with self.assertRaisesRegex(SourceError, "logowanie"):
            list(meta.fetch({"mode":"import","imports":{QUERY.phrase:p}}, QUERY))
        with self.assertRaisesRegex(SourceError, "odczytać"):
            list(meta.fetch({"mode":"import","path":self.root/"missing.html"}, QUERY))

    def test_partial_card_with_overlaid_platform_error(self):
        body = "<article><p>Library ID: 42</p><p>Advertiser: Studio</p><p>One visible offer mentions captcha.</p></article>"
        [row] = meta._parse_html("<main>"+body+"</main>", QUERY)
        self.assertEqual(row[0]["text"], "One visible offer mentions captcha.")
        self.assertNotIn("status", row[0])
        with self.assertRaisesRegex(SourceError, "blokadę"):
            meta._parse_html("<main>"+body+"<aside role=alert>Security check required</aside></main>", QUERY)

    def test_removal_notice_keeps_inline_link_and_punctuation(self):
        source = """<article><p>Library ID: 4100003</p>
        <div>This ad is unavailable because the account was disabled under our
        <a><span>advertising</span> standards</a>.<br>See the
        <a>full policy</a>.<span hidden>Hidden text</span></div>
        <button>See ad details</button></article>"""
        [(card, _, _)] = meta._parse_html(source, QUERY)
        self.assertEqual(card["removal_notice"], "This ad is unavailable because the account was disabled "
                         "under our advertising standards. See the full policy.")

    def test_library_removal_and_disclaimer_notices_withdraw_card(self):
        # Regresja: bench-500 zawierał 36 kart z tym komunikatem traktowanych jako widoczne,
        # a link do standardów Meta wyglądał na cel reklamy.
        policy = "https://l.facebook.com/l.php?u=https%3A%2F%2Ftransparency.meta.com%2Fpolicies%2Fad-standards%2F"
        notices = ('Te materiały zostały usunięte, ponieważ naruszyły nasze <a href="{0}">Standardy dotyczące reklam</a>.',
                   'Ta reklama była wyświetlana bez <a href="{0}">wymaganego zastrzeżenia</a>.',
                   'These materials were removed because they violated our <a href="{0}">Advertising Standards</a>.')
        for i, notice in enumerate(notices):
            source = (f"<article><p>Identyfikator biblioteki: {4200000 + i}</p><div>Studio</div>"
                      f"<div>Sponsorowane</div><div>{notice.format(policy)}</div></article>")
            [(card, _, _)] = meta._parse_html(source, QUERY)
            self.assertEqual(card["creative_state"], "withdrawn")
            self.assertNotIn("landing_candidates", card)
            self.assertNotIn("cta_element", card)
        for text in ("Te materiały zostały usunięte z magazynu, nowe już są!",
                     "These materials were removed from stock because of high demand."):
            visible = ("<article><p>Identyfikator biblioteki: 4200009</p><div>Studio</div><div>Sponsorowane</div>"
                       f"<p>{text}</p></article>")
            [(card, _, _)] = meta._parse_html(visible, QUERY)
            self.assertEqual(card["creative_state"], "visible", text)

    def test_reports_have_grounded_scope_nullable_fields_and_distinct_notes(self):
        p = self.root/"historic.json"
        data = {"data":"2020-01-01","wyszukiwania":[{"fraza":QUERY.phrase, "url":URL,
                "szacunkowa_liczba_wynikow":2,"liczba_kart_w_odczytanym_widoku":2,
                "wybrane_karty":[{"meta_ad_library_id":str(i), "nazwa_na_karcie":"Autor",
                                      "obserwacja":"Opis obserwatora: reklama konta wyłączonego za naruszenie standardów."}
                                     for i in (1000, 1001)]}]}
        p.write_text(json.dumps(data), encoding="utf8")
        [f] = meta.fetch({"mode":"replay","path":p,"synthetic":True}, Query(QUERY.phrase, "PL", 1))
        self.assertEqual((f.ad_ref,f.card["observation_date"],f.source_kind), ("1000","2020-01-01","synthetic"))
        self.assertNotIn("removal_notice", f.card)
        self.assertNotIn("text", f.card)
        self.assertEqual(f.card["creative_state"], "withdrawn_reported")
        self.assertEqual(f.locator, "/wyszukiwania/0/wybrane_karty/0")
        with self.assertRaisesRegex(SourceError, "Brak zapisanego wyniku"):
            list(meta.fetch({"path":p}, Query(QUERY.phrase,"DE",10)))
        data["wyszukiwania"][0]["wybrane_karty"] = []
        p.write_text(json.dumps(data), encoding="utf8")
        with self.assertRaisesRegex(SourceError, "potwierdzenia"):
            list(meta.fetch({"path":p},QUERY))
        data["wyszukiwania"][0].update(szacunkowa_liczba_wynikow=0,liczba_kart_w_odczytanym_widoku=0)
        p.write_text(json.dumps(data), encoding="utf8")
        self.assertEqual(list(meta.fetch({"path":p},QUERY)), [])

    def test_permission_and_allowed_navigation(self):
        with self.assertRaisesRegex(SourceError, "Brak potwierdzonego uprawnienia"):
            list(meta.fetch({"mode":"live","permission":"","headless":False}, QUERY))
        with self.assertRaisesRegex(SourceError, "Pole headless"):
            list(meta.fetch({"mode":"live","permission":"syntetyczny localhost","headless":"false"}, QUERY))
        self.assertTrue(meta._allowed_url(URL, True))
        for url in ("https://www.facebook.com/login", "https://example.test/landing",
                    "http://www.facebook.com/ads/library/", "https://www.facebook.com:444/ads/library/",
                    "https://notfacebook.com/ads/library/", "https://www.facebook.com/go"):
            self.assertFalse(meta._allowed_url(url, True))
        self.assertFalse(meta._allowed_url("https://example.test/media",False))
        self.assertTrue(meta._allowed_url("https://static.xx.fbcdn.net/a", False))

    @unittest.skipUnless(os.environ.get("SCAMGRAPH_TEST_CHROME") in {"1", "headed"}, "Test opcjonalny z lokalnym Chrome i Playwright")
    def test_chrome_reads_rendered_cards_and_stops_at_redirect(self):
        requests = []
        destinations = []
        user_agents = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                requests.append(self.path)
                destinations.append(self.headers.get("Sec-Fetch-Dest"))
                user_agents.append(self.headers.get("User-Agent"))
                if self.path.endswith("?empty"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"<main>No results found</main>")
                    return
                if self.path.endswith("?denied"):
                    self.send_response(403)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"<title>Access denied</title><h1>Access denied</h1>")
                    return
                if self.path == "/ads/library/?redirect":
                    self.send_response(302)
                    self.send_header("Location", "/landing")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                document = """<main style="height:2500px"></main><img src="/landing">
                    <script>
                    const card = id => '<article><div>Library ID: '+id+'</div><a>Test</a><div>Sponsored</div><p>Offer</p></article>';
                    setTimeout(() => {document.querySelector('main').innerHTML=card(401)}, 150);
                    addEventListener('scroll', () => {document.querySelector('main').innerHTML=card(402)}, {once:true});
                    </script>"""
                self.wfile.write(document.encode("utf-8"))

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        local = f"http://127.0.0.1:{server.server_port}/ads/library/"
        options = {"mode":"live", "permission":"syntetyczny localhost", "archive_dir":self.root/"archive"}
        if os.environ.get("SCAMGRAPH_TEST_CHROME") == "headed":
            options["headless"] = False
        # Only the local test origin is allowed. /landing and every external host are denied.
        with patch.object(meta, "_allowed_url", side_effect=lambda url, navigation: url.split("?")[0] == local):
            with patch.object(meta, "search_url", return_value=local):
                cards = list(meta.fetch(options, QUERY))
                self.assertEqual([f.ad_ref for f in cards], ["401", "402"])
                self.assertEqual([f.card["main_document_http_status"] for f in cards], [200, 200])
                self.assertEqual(len({f.original for f in cards}), 2)
                self.assertEqual(len({f.image for f in cards}), 2)
                self.assertTrue(all(f.image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") for f in cards))
            with patch.object(meta, "search_url", return_value=local+"?redirect"):
                with self.assertRaisesRegex(SourceError, "302"):
                    list(meta.fetch(options, QUERY))
            with patch.object(meta, "search_url", return_value=local+"?denied"):
                with self.assertRaisesRegex(SourceError, r"HTTP 403.*Odmowa dostępu.*Access denied.*Zrzut widoku: (\w+\.png)") as error:
                    list(meta.fetch({**options, "user_agent": "ScamGraph-Test/1"}, QUERY))
                screenshot = str(error.exception).split()[-1]
                self.assertTrue((options["archive_dir"] / screenshot).is_file())
            with patch.object(meta, "search_url", return_value=local+"?empty"):
                self.assertEqual(list(meta.fetch(options, QUERY)), [])
                [report] = options["archive_dir"].glob("*.json")
                evidence = json.loads(report.read_text(encoding="utf8"))
                self.assertEqual((evidence["result"], evidence["main_document_http_status"]), ("empty", 200))
                self.assertIn("No results found", (report.parent / evidence["visible_html"]).read_text(encoding="utf8"))
        self.assertEqual(requests, ["/ads/library/" + suffix for suffix in ("", "?redirect", "?denied", "?empty")])
        self.assertEqual(destinations, ["document"] * 4)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as driver:
            with driver.chromium.launch(channel="chrome", headless=options.get("headless", True)) as browser:
                native_agent = browser.new_page().evaluate("navigator.userAgent")
        self.assertEqual(user_agents, [native_agent, native_agent, "ScamGraph-Test/1", native_agent])
