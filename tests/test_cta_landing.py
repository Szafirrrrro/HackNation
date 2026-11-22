import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import tempfile
from threading import Thread
import unittest
import base64
import json
from unittest.mock import patch

from PIL import Image

from scamgraph.capture import read_json, staging, verified
from scamgraph.catalog import preview
from scamgraph.discovery import meta, landing_visit
from scamgraph.discovery.landing_fetch import LandingError, PageReads, read_public
from scamgraph.discovery.service import publish
from scamgraph.discovery.types import Query


QUERY = Query("test", "PL", 10)
URL = "https://shop.example/offer?token=private"
PAGE = "https://shop.example/product"


def card(label, target=URL, extra=""):
    return f'<article><div>Library ID: 401</div><a href="{target}"><span>{label}</span></a>{extra}</article>'


class LandingCTATests(unittest.TestCase):
    def test_labels_redirect_wrapper_and_ambiguous_target(self):
        for label in ("Obejrzyj więcej", "Kup teraz", "Watch more", "Learn More", "Dowiedz się więcej"):
            with self.subTest(label=label):
                row = meta._parse_html(card(label, "https://l.facebook.com/l.php?u=https%3A%2F%2Fshop.example"), QUERY)[0][0]
                self.assertEqual(row["cta"], label)
                self.assertIsInstance(row["cta_element"], int)
        html = card("Shop now", extra='<a href="https://other.example">Watch more</a>')
        self.assertNotIn("cta_element", meta._parse_html(html, QUERY)[0][0])
        hidden = card("Kup teraz", extra='<div hidden><a href="https://other.example">Watch more</a></div>')
        self.assertIn("cta_element", meta._parse_html(hidden, QUERY)[0][0])
        html = '<article><div>Library ID: 402</div><button>Watch more</button></article>'
        self.assertIn("bez dostępnego odnośnika", meta._parse_html(html, QUERY)[0][0]["landing_missing_reason"])
        html = '<article><div>Library ID: 402</div><button aria-label="Kup teraz" data-url="https://example.com/item"></button></article>'
        self.assertEqual(meta._parse_html(html, QUERY)[0][0]["cta_attribute"], "data-url")
        html = card("Kup teraz", '#" data-url="https://shop.example/item')
        self.assertEqual(meta._parse_html(html, QUERY)[0][0]["cta_attribute"], "data-url")
        html = card("Kup teraz", 'https://a.example/" data-url="https://b.example/')
        self.assertNotIn("cta_element", meta._parse_html(html, QUERY)[0][0])
        html = card('<div role="button"><span><div>Obejrzyj więcej</div></span></div>')
        self.assertEqual(meta._parse_html(html, QUERY)[0][0]["cta_attribute"], "href")
        html = card('<div role="button">Subscribe</div>')
        self.assertEqual(meta._parse_html(html, QUERY)[0][0]["cta"], "Subscribe")
        html = card('', extra='<a href="https://other.example">Inny sklep</a>')
        row = meta._parse_html(html, QUERY)[0][0]
        self.assertIn("kilka różnych celów", row["landing_missing_reason"])
        self.assertNotIn("cta_element", row)
        # Widoczny podpis domeny rozstrzyga między różnymi domenami (cel wybrany regułą).
        html = card('', extra='<a href="https://other.pl">Inny sklep</a><div>OTHER.PL</div>')
        row = meta._parse_html(html, QUERY)[0][0]
        self.assertEqual((row["cta_basis"], row["cta_caption"]), ("caption", "OTHER.PL"))
        self.assertNotIn("cta_element", meta._parse_html(html, QUERY, auto=False)[0][0])

    def test_private_ip_is_rejected_before_connecting(self):
        with self.assertRaisesRegex(LandingError, "publiczną"):
            read_public("http://127.0.0.1/hidden", 1000, 2)
        with staging(Path(tempfile.gettempdir())) as root:
            self.assertIn("publiczną", landing_visit.visit(root, "http://127.0.0.1/hidden")["reason"])

    def test_document_redirects_and_cross_origin_asset_redirects(self):
        target = "https://reviews.example/reviews"
        redirect = (302, "", b"", target, {})
        response = (200, "text/html", b"ok", None, {})
        with patch("scamgraph.discovery.landing_fetch.read_public", side_effect=[redirect, response]):
            self.assertEqual(PageReads(5).get(PAGE)[0], target)
        with patch("scamgraph.discovery.landing_fetch.read_public", return_value=redirect) as get:
            with self.assertRaisesRegex(LandingError, "innego źródła"):
                PageReads(5).get(PAGE, resource=True)
            self.assertEqual(get.call_count, 1)
        with patch("scamgraph.discovery.landing_fetch.read_public", return_value=(302, "", b"", "/moved", {})):
            with self.assertRaisesRegex(LandingError, "CORS"):
                PageReads(5).get(target, "https://shop.example", resource=True)

    def test_replay_stays_offline_and_denial_preserves_card(self):
        with staging(Path(tempfile.gettempdir())) as root:
            source = root / "cards.html"
            source.write_text(card("Kup teraz"), encoding="utf8")
            options = {"mode":"import", "imports":{"test":source}, "state_dir":root/"state",
                       "provider":"meta-ad-library", "query_phrase":"test", "query_country":"PL"}
            finding, = meta.fetch(options, QUERY)
            with patch.object(landing_visit, "visit", side_effect=AssertionError("unexpected network")):
                cid = publish("meta", options, finding)
                self.assertFalse(read_json(root/"state"/"captures"/cid/"extracted.json")["ad_page_links"])
            options["mode"] = "live"
            with patch.object(landing_visit, "visit", return_value={"reason":"HTTP 403"}):
                cid = publish("meta", options, finding)
            folder = root/"state"/"captures"/cid
            self.assertEqual(read_json(folder/"manifest.json")["availability"]["landing"]["reason"], "HTTP 403")
            self.assertFalse(read_json(folder/"extracted.json")["ad_page_links"])

    def test_caption_target_platform_skip_and_confidence(self):
        hidden = "https://l.facebook.com/l.php?u=http%3A%2F%2Ffb.me%2F&amp;h=AU"
        offline = (patch("scamgraph.discovery.verified_entity.match_verified_entity", return_value=None),
                   patch("scamgraph.discovery.authoritive_corpora.match_authoritative_corpus", return_value=None))
        with staging(Path(tempfile.gettempdir())) as root, offline[0], offline[1]:
            source = root / "cards.html"
            options = {"mode": "import", "imports": {"test": source}, "state_dir": root / "state",
                       "provider": "meta-ad-library", "query_phrase": "test", "query_country": "PL"}
            source.write_text('<article><div>Library ID: 401</div><div>Sponsorowane</div><p>Oferta</p>'
                              f'<a href="{hidden}"><div>SHOP.PL/offer</div><div role="button">Learn More</div></a>'
                              '</article>', encoding="utf8")
            finding, = meta.fetch(options, QUERY)
            self.assertEqual(finding.card["cta_basis"], "caption")
            options["mode"] = "live"
            with patch.object(landing_visit, "visit", return_value={"status": "failed", "reason": "HTTP 403"}) as visit:
                cid = publish("meta", options, finding)
            self.assertEqual(visit.call_args[0][1], "https://shop.pl/offer")
            saved = read_json(root / "state" / "captures" / cid / "extracted.json")["landing_visit"]
            self.assertEqual((saved["target_basis"], saved["attribute"]), ("caption", "text"))
            # Przycisk kontaktu prowadzi do komunikatora: brak wizyty, jawny powód.
            source.write_text('<article><div>Library ID: 402</div><a href="https://l.facebook.com/l.php?u='
                              'https%3A%2F%2Fwa.me%2F48500"><span>Wyślij wiadomość</span></a></article>', encoding="utf8")
            options["mode"] = "import"
            finding, = meta.fetch(options, QUERY)
            options["mode"] = "live"
            with patch.object(landing_visit, "visit", side_effect=AssertionError("unexpected visit")):
                cid = publish("meta", options, finding)
            summary = read_json(root / "state" / "captures" / cid / "manifest.json")["landing_summary"]
            self.assertEqual((summary["content_status"], summary["reason_code"]), ("skipped", "platform_internal"))

    def test_target_confidence_checks(self):
        from scamgraph.discovery.service import target_confidence
        with staging(Path(tempfile.gettempdir())) as root:
            (root / "page.html").write_text("<title>Sklep</title><p>Zikom  INVEST sp. z o.o.</p>", encoding="utf8")
            card_fields = {"page_name": "ZIKOM Invest", "cta_caption": "inwestycja.zikom.pl/"}
            self.assertEqual(target_confidence("label", {}, PAGE, {}, root)["target_confidence"], "high")
            both = target_confidence("single_link", card_fields, "https://inwestycja.zikom.pl/",
                                     {"final_url": "https://www.zikom.pl/oferta"}, root)
            self.assertEqual(both, {"target_confidence": "high", "target_checks": ["caption_domain", "advertiser_name"]})
            # Cel z podpisu nie potwierdza się tym samym podpisem.
            own = target_confidence("caption", {**card_fields, "page_name": "Inna Firma"}, "https://inwestycja.zikom.pl/",
                                    {"final_url": "https://inwestycja.zikom.pl/"}, root)
            self.assertEqual(own, {"target_confidence": "low", "target_checks": []})
            # Nazwa reklamodawcy jako całe słowa, nie fragment innego słowa.
            part = target_confidence("single_link", {"page_name": "Sklep"}, PAGE, {}, root)
            self.assertEqual(part["target_checks"], ["advertiser_name"])
            self.assertEqual(target_confidence("single_link", {"page_name": "Zikomx"}, PAGE, {}, root)["target_confidence"], "low")
            low = target_confidence("single_link", {"page_name": "Inna Firma"}, PAGE, {"final_url": PAGE}, root)
            self.assertEqual(low, {"target_confidence": "low", "target_checks": []})

    @unittest.skipUnless(os.environ.get("SCAMGRAPH_TEST_CHROME"), "Lokalny test renderowania w Chrome")
    def test_visible_meta_card_archives_its_external_link(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                raw = card('<div role="button"><span>Obejrzyj więcej</span></div>', PAGE).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server, staging(Path(tempfile.gettempdir())) as root:
            Thread(target=server.serve_forever, daemon=True).start()
            local = f"http://127.0.0.1:{server.server_port}/ads/library/"
            try:
                with patch.object(meta, "search_url", return_value=local), patch.object(
                        meta, "_allowed_url", side_effect=lambda url, _: url == local):
                    finding, = meta.fetch({"mode":"live", "permission":"syntetyczna próba localhost",
                                           "archive_dir":root}, Query("test", "PL", 1))
                self.assertEqual(finding.card["cta"], "Obejrzyj więcej")
                self.assertIn(PAGE, finding.original.read_text(encoding="utf8"))
            finally:
                server.shutdown()

    @unittest.skipUnless(os.environ.get("SCAMGRAPH_TEST_CHROME"), "Lokalny test renderowania w Chrome")
    def test_document_csp_and_cross_origin_denial(self):
        html = b"""<body><p>Offer</p><script>fetch('https://reviews.example/item').then(r=>r.text())
          .then(t=>document.body.insertAdjacentHTML('beforeend','<p>'+t+'</p>'))</script></body>"""
        for headers in ({}, {"Content-Security-Policy": "script-src 'none'"}):
            with self.subTest(headers=headers), staging(Path(tempfile.gettempdir())) as root:
                def response(url, *args):
                    if url == PAGE:
                        return 200, "text/html", html, None, headers
                    self.assertEqual(url, "https://reviews.example/item")
                    self.assertEqual(args[-1], "https://shop.example")
                    return 200, "text/plain", b"Denied review", None, {}
                with patch("scamgraph.discovery.landing_fetch.read_public", side_effect=response) as get:
                    report = landing_visit.gather(root, PAGE)
                self.assertTrue((root/"screenshot.png").exists())
                self.assertNotIn("Denied review", (root/"page.html").read_text(encoding="utf8"))
                self.assertEqual(get.call_count, 1 if headers else 2)
                if not headers:
                    self.assertTrue(any("CORS" in issue for issue in report["issues"]))

    @unittest.skipUnless(os.environ.get("SCAMGRAPH_TEST_CHROME"), "Lokalny test renderowania w Chrome")
    def test_long_page_is_labelled_and_ambiguous_consent_stays(self):
        api = landing_visit.playwright_api()
        with staging(Path(tempfile.gettempdir())) as root, api.sync_playwright() as driver:
            with driver.chromium.launch(channel="chrome", headless=True) as chrome:
                page = chrome.new_page(viewport={"width":300, "height":360})
                page.set_content('<div role="dialog">Cookies<button onclick="this.remove()">Rozumiem</button></div>'
                                 '<div style="height:23000px;background:linear-gradient(red,blue)">Długa strona</div>')
                report = {}
                landing_visit.capture_views(page, root, api, set(), report)
                self.assertNotIn("cookie_action", report)
                self.assertTrue(page.get_by_text("Rozumiem", exact=True).is_visible())
                self.assertFalse(report["page_screenshot"]["complete"])
                self.assertFalse((root/"screenshot_full.png").exists())
                with Image.open(root/"page-partial.png") as im:
                    self.assertEqual(im.height,16000)


    @unittest.skipUnless(os.environ.get("SCAMGRAPH_TEST_CHROME"), "Lokalny test renderowania w Chrome")
    def test_cta_to_rendered_evidence_packet(self):
        image = io.BytesIO()
        Image.new("RGB", (20, 20), "blue").save(image, "PNG")
        html = b'''<html><head><title>Example product</title></head><body><img src="/product.png">
          <div role="dialog" style="position:fixed;inset:0;background:white;z-index:99">
          Cookies. <button onclick="this.parentElement.remove()">Reject all</button>
          <button onclick="document.body.innerHTML='WRONG CHOICE'">Accept all</button></div>
          <script src="/bundle.js"></script><script src="/tracking.js"></script>
          <div style="height:1400px">Offer description</div><p>Bottom of offer.</p>
          <div class="review"><p class="review-text">First opinion.</p></div>
          <script>fetch("https://reviews.example/feed").then(r=>r.text()).then(text=>document.body.insertAdjacentHTML('beforeend',
          '<div class="review"><p class="review-text">'+text+'</p></div>'))</script></body></html>'''
        bundle = b"document.body.dataset.ready='yes';"
        responses = {URL:(302,"",b"",PAGE,{}), PAGE:(200,"text/html; charset=utf-8",html,None,{}),
                     "https://shop.example/bundle.js":(200,"text/javascript",bundle,None,{}),
                     "https://shop.example/tracking.js":(200,"text/javascript",b"if(window.fbq)fbq('init','12345678');",None,{}),
                     PAGE+".png":(200,"image/png",image.getvalue(),None,{}),
                     "https://reviews.example/feed":(200,"text/plain",b"Dynamic opinion.",None,
                                                     {"Access-Control-Allow-Origin":"https://shop.example"})}
        with staging(Path(tempfile.gettempdir())) as root:
            source = root/"cards.html"
            source.write_text(card("Learn more"), encoding="utf8")
            options = {"mode":"import","imports":{"test":source},"state_dir":root/"state",
                       "provider":"meta-ad-library","query_phrase":"test","query_country":"PL"}
            finding, = meta.fetch(options, QUERY)
            finding.source_kind = "library"
            options["mode"] = "live"
            def collect(store, url, timeout):
                directory = store / "fixture-page"
                return {**landing_visit.gather(directory, url), "page_id": directory.name}

            with patch("scamgraph.discovery.landing_fetch.read_public",
                       side_effect=lambda url, *_: responses[url]), patch.object(landing_visit, "visit", side_effect=collect):
                cid = publish("meta", options, finding)
            folder = root/"state"/"captures"/cid
            manifest = read_json(folder/"manifest.json")
            verified(folder, manifest)
            result = read_json(folder/"extracted.json")
            self.assertEqual(result["landing_visit"]["issues"], [])
            self.assertEqual(result["landing_visit"]["status"], "success")
            self.assertTrue(result["landing_visit"]["page_screenshot"]["complete"])
            with Image.open(folder/"landing/screenshot_full.png") as full, Image.open(folder/"landing/screenshot.png") as initial:
                self.assertGreater(full.height, initial.height)
            txt = (folder/"landing/page.txt").read_text(encoding="utf8")
            self.assertIn("Bottom of offer.", txt)
            self.assertIn("Dynamic opinion.", txt)
            self.assertNotIn("WRONG CHOICE", txt)
            self.assertIn("Reject all", (folder / "landing/page.html").read_text(encoding="utf8"))
            link, = result["ad_page_links"]
            self.assertEqual((link["ad_id"], link["capture_id"], link["final_url"]), ("meta-ad-library/401", cid, PAGE))
            self.assertEqual(preview(folder, manifest, link["evidence"])[1]["przycisk"], "Learn more")
            self.assertEqual(preview(folder, manifest, link["navigation_evidence"])[1]["status"], 200)
            from scamgraph.discovery.graph_feed import projection
            graph_card = projection(folder)
            self.assertEqual(graph_card["infra"]["final_domain"], "shop.example")
            self.assertEqual(graph_card["page"]["tracking_ids"], {"meta_pixel": "12345678"})
            self.assertEqual({o["text"] for o in result["opinions"]}, {"First opinion.", "Dynamic opinion."})
            self.assertTrue(all(o["evidence"]["file"] == "landing/page.html" for o in result["opinions"]))
            self.assertEqual(len(result["pages"]), 1)
            self.assertFalse(manifest["availability"]["screenshot"]["available"])
            self.assertTrue(manifest["availability"]["landing_screenshot"]["available"])
            self.assertTrue(list((folder/"landing/page_files").glob("*.png")))
            har = read_json(folder/"landing/network.har")["log"]["entries"]
            script, = (e["response"]["content"] for e in har if e["request"]["url"].endswith("/bundle.js"))
            self.assertEqual(script["text"].encode(), bundle)
            self.assertEqual(len(list((folder/"landing/page_files").glob("*.js"))), 2)
            self.assertTrue(result["pixels"])
            review_response, = (e for e in har if e["request"]["url"] == "https://reviews.example/feed")
            self.assertEqual(review_response["response"]["content"]["text"], "Dynamic opinion.")
            self.assertNotIn("token=private",(folder/"extracted.json").read_text(encoding="utf8"))
            self.assertIn("token=private",(folder/"landing/network.har").read_text(encoding="utf8"))
            archive = root / "state/pages/fixture-page"
            self.assertEqual(read_json(archive / "metadata.json")["input_url"], URL)
            self.assertEqual(read_json(archive / "network.har")["log"]["version"], "1.2")
            self.assertEqual(read_json(archive / "metadata.json")["status"], "success")
