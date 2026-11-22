"""Manual URL acquisition: source preservation and explicit capture action."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scamgraph.url_capture import capture_url, existing_url_ids, url_key


class URLCaptureTests(unittest.TestCase):
    def test_url_identity_keeps_path_query_and_normalizes_host_fragment_and_default_port(self):
        self.assertEqual(url_key(" https://OWN.example.:443/#section "), url_key("https://own.example/"))
        cards = [{"ad_id": "exact", "provenance": {"url_key": url_key("https://own.example/a?x=1")}},
                 {"ad_id": "old", "provenance": {"url": "own.example/old"}},
                 {"ad_id": "ad", "provenance": {"url": "https://own.example/ad"}}]
        self.assertEqual(existing_url_ids("https://own.example/a?x=1#anchor", cards), {"exact"})
        for url in ("https://own.example/a?x=2", "https://own.example/b?x=1",
                    "https://own.example/old?x=1", "https://fake-own.example/ad"):
            self.assertEqual(existing_url_ids(url, cards), set())
        self.assertEqual(existing_url_ids("https://OWN.example/old", cards), {"old"})
        self.assertEqual(existing_url_ids("https://own.example/ad", cards), {"ad"})

    def test_explicit_url_always_visits_including_popular_and_ugc_hosts(self):
        urls = ["https://mbank.pl/", "https://WWW.MBANK.PL./login", "https://bit.ly/x",
                "https://t.me/x", "https://docs.google.com/forms/d/x", "https://forms.gle/x",
                "https://x.weebly.com/", "https://x.tilda.ws/", "https://pastebin.com/x",
                "https://filesdl.top/", "https://BÜCHER.example/"]
        with tempfile.TemporaryDirectory() as tmp, patch(
                "scamgraph.url_capture.visit", return_value={"page_id": "fixture", "status": "failed"}) as visit, patch(
                "scamgraph.url_capture.capture", side_effect=OSError("fixture")) as extract:
            for url in urls:
                with self.subTest(url=url):
                    result = capture_url(url, Path(tmp))
                    self.assertEqual(result["report"]["status"], "failed")
                    self.assertIsNotNone(result["archive"])
                    self.assertIsNone(result["card"])
            self.assertEqual(visit.call_count, len(urls))
            self.assertEqual(extract.call_count, len(urls))

    def test_page_projection_uses_observed_pixels_and_saved_scripts(self):
        from scamgraph.capture import capture, read_json, write_json
        from scamgraph.sources import digest
        from scamgraph.url_capture import page_graph_card

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "page_files").mkdir()
            script = source / "page_files/site.js"
            script.write_text("console.log('Own fixture');")
            (source / "page.html").write_text(
                '<html><head><script src="page_files/site.js"></script></head><body>'
                '<h1>Own fixture</h1><script>fbq("init", "123456789");</script></body></html>')
            write_json(source / "metadata.json", {
                "input_url": "https://input.example/", "final_url": "https://final.example/",
                "captured_at": "2026-11-22T10:00:00+00:00", "errors": [], "status": "partial",
                "http_status": 200, "target_kind": "web", "content_status": "usable"})
            folder = capture(source, root / "captures")
            card = page_graph_card(folder)
            self.assertEqual(card["infra"]["final_domain"], "final.example")
            self.assertEqual(card["page"]["tracking_ids"], {"meta_pixel": "123456789"})
            self.assertIn(digest(script), card["page"]["script_hashes"])
            self.assertEqual(card["extensions"]["page_observation"]["ad_page_links"], [])

            # Several observed IDs must not be resolved by document order.
            data = read_json(folder / "extracted.json")
            pixel = data["pages"][0]["pixels"][0]
            data["pixels"].append({**pixel, "value": {"provider": "meta", "id": "987654321"}})
            write_json(folder / "extracted.json", data)
            manifest = read_json(folder / "manifest.json")
            manifest["result"]["sha256"] = digest(folder / "extracted.json")
            write_json(folder / "manifest.json", manifest)
            self.assertEqual(page_graph_card(folder)["page"]["tracking_ids"], {})

    def test_invalid_url_never_starts_visit(self):
        for url in ("", "file:///etc/passwd", "https://user:secret@example.org", "ftp://example.org"):
            with self.subTest(url=url), patch("scamgraph.url_capture.visit") as visit:
                with self.assertRaises(ValueError):
                    capture_url(url)
                visit.assert_not_called()

    def test_archive_is_extracted_without_ad_page_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp).resolve()

            def visit(store, url):
                page = store / "visit-id"
                page.mkdir(parents=True)
                (page / "page_files").mkdir()
                (page / "metadata.json").write_text(json.dumps({
                    "input_url": url, "final_url": url,
                    "captured_at": "2026-11-22T10:00:00+00:00",
                    "status": "partial", "errors": ["No screenshot"],
                    "target_kind": "web", "content_status": "usable",
                    "http_status": 200,
                }))
                (page / "page.html").write_text(
                    '<html><title>Own test page</title><body><h1>Offer</h1>'
                    '<p>Synthetic content for a manual capture test.</p></body></html>')
                return {"page_id": page.name, "status": "partial", "content_status": "usable"}

            with patch("scamgraph.url_capture.visit", side_effect=visit) as fetch:
                result = capture_url(" https://own.example/offer ", state)
            fetch.assert_called_once_with(state / "pages", "https://own.example/offer")
            folder = Path(result["capture"])
            manifest = json.loads((folder / "manifest.json").read_text())
            extracted = json.loads((folder / "extracted.json").read_text())
            self.assertEqual(manifest["acquisition_method"], "manual_url")
            self.assertEqual(extracted["ad_page_links"], [])
            self.assertTrue(extracted["pages"])
            self.assertEqual(result["report"]["status"], "partial")
            card = result["card"]
            self.assertEqual(card["ad_id"], "page:" + manifest["capture_id"])
            self.assertEqual(card["infra"]["final_domain"], "own.example")
            self.assertEqual(card["provenance"]["record_kind"], "page_capture")
            self.assertIn("Synthetic content", card["text"]["ad_text"])
            self.assertNotIn("embedding", card["text"])
            self.assertNotIn("first_seen", card)
            self.assertEqual(card["extensions"]["page_observation"], extracted)

            # Blocked/error documents must not become matching queries even with HTML present.
            from scamgraph.url_capture import page_graph_card
            for change in ({"content_status": "blocked"}, {"http_status": 404}, {"target_kind": "pdf"}):
                with self.subTest(change=change):
                    from scamgraph.sources import digest
                    modified = {**extracted, "landing_visit": {**extracted["landing_visit"], **change}}
                    (folder / "extracted.json").write_text(json.dumps(modified))
                    manifest["result"]["sha256"] = digest(folder / "extracted.json")
                    (folder / "manifest.json").write_text(json.dumps(manifest))
                    self.assertIsNone(page_graph_card(folder))

    def test_failed_visit_and_extraction_error_keep_archive(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
                "scamgraph.url_capture.visit", return_value={"page_id": "failed", "status": "failed"}), patch(
                "scamgraph.url_capture.capture", side_effect=OSError("disk error")):
            result = capture_url("https://own.example/", Path(tmp))
            self.assertEqual(result["report"]["status"], "failed")
            self.assertEqual(Path(result["archive"]), Path(tmp).resolve() / "pages" / "failed")
            self.assertIsNone(result["capture"])
            self.assertIsNone(result["card"])
            self.assertIn("OSError", result["extraction_error"])


if __name__ == "__main__":
    unittest.main()
