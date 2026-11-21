import json
import os
import re
import sys
import tempfile
import unittest
from html import unescape
from pathlib import Path
from unittest.mock import patch

from scamgraph.capture import capture, read_json, staging, verified
from scamgraph.catalog import catalog, matches, preview
from scamgraph.sources import digest

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_STRUCT = Path(os.environ.get("SCAMGRAPH_STRUCT_FIXTURE", ROOT / "data/struct"))


class CaptureTests(unittest.TestCase):
    def setUp(self):
        directory = staging(Path(tempfile.gettempdir()))
        self.tmp = directory.__enter__()
        self.addCleanup(directory.__exit__, None, None, None)
        self.store = self.tmp / "store"

    def source(self, name, data):
        p = self.tmp / name
        p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
        return p

    def imported(self, path, **kwargs):
        folder = capture(path, self.store, **kwargs)
        meta, result = read_json(folder / "manifest.json"), read_json(folder / "extracted.json")
        verified(folder, meta)
        return folder, meta, result

    def test_card_partial_variants_and_independent_identities(self):
        p = self.source("card.json", {"id": "9876543210987654321", "page_id": "3", "page_name": "Strona demo",
                                      "ad_creative_bodies": ["Oferta A", "Oferta B"], "ad_creative_link_captions": ["demo.example"],
                                      "platform_notice": "Treść została wycofana", "token": "private_secret",
                                      "comments": [{"message": "Wpis", "replies": [{"message": "Odpowiedź", "like_count": 0}]}],
                                      "quotes": ["Cytat z kreacji"]})
        folder, meta, result = self.imported(p)
        self.assertEqual(folder, capture(p, self.store))
        self.assertEqual((meta["provider"], meta["ad_ref"]), ("meta-ad-library", "9876543210987654321"))
        self.assertTrue(result["partial"])
        self.assertEqual(result["ad_page_links"], [])
        self.assertNotIn("landing_url", result["ad"])
        self.assertEqual([f["value"] for f in result["ad_fields"] if f["field"] == "text"], ["Oferta A", "Oferta B"])
        self.assertIn("removal_notice", [f["field"] for f in result["ad_fields"]])
        self.assertEqual(result["opinions"][1]["parent_id"], result["opinions"][0]["id"])
        self.assertEqual(result["opinions"][1]["reactions"][0]["count"], 0)
        self.assertEqual([r["source_kind"] for r in result["opinions"]], ["platform_comment", "platform_comment", "creative_quote"])
        self.assertNotIn("private_secret", (folder / "extracted.json").read_text())
        self.assertEqual(digest(p), digest(folder / meta["artifacts"][0]["path"]))
        other = self.source("another.json", {"ad": {"id": meta["ad_ref"], "status": "inactive"}, "advertiser": {"business_id": "22"}})
        other_folder, _, record = self.imported(other)
        self.assertNotEqual(folder, other_folder)
        self.assertIsNone(record["ad"])

    def test_card_id_and_truncated_screenshot_id(self):
        src = self.tmp / "observation" / "ad"
        src.mkdir(parents=True)
        shot = src / "a-screenshot.png"
        shot.write_bytes(b"synthetic image for mocked OCR")
        full = "41234567890"
        raw = "Library ID: 412345"

        def read_screen(path, artifact):
            return [{"value": raw, "method": "test-ocr",
                     "evidence": {"file": artifact["path"], "origin_id": artifact["sha256"],
                                  "locator": {"bbox": [1, 1, 20, 10]}}}]

        with patch("scamgraph.capture.ocr", side_effect=read_screen):
            _, manifest, _ = self.imported(shot)
            self.assertEqual(manifest["ad_ref"], "412345")
            (src / "z-card.json").write_text(json.dumps({"id": full}), encoding="utf8")
            for raw, expected in [("Library ID: 412345%890", [full]), ("Library ID: 4123467890", [full]),
                                  ("Library ID: " + full, [full, full])]:
                _, manifest, result = self.imported(src.parent)
                self.assertEqual(manifest["ad_ref"], full)
                self.assertEqual([f["value"] for f in result["ad_fields"] if f["field"] == "ad_ref"], expected)
                self.assertEqual(result["ocr"][0]["value"], raw)
            raw = "Library ID: 9999"
            with self.assertRaisesRegex(ValueError, "Kilka identyfikatorów"):
                self.imported(src.parent)

    def test_mixed_evidence_privacy_and_redirects(self):
        src = self.tmp / "observation"
        (src / "landing" / "assets").mkdir(parents=True)
        (src / "landing" / "assets" / "tag.js").write_text("fbq('init','12345678')", encoding="utf8")
        (src / "landing" / "page.html").write_text("""
            <script>const token='BAD-script'</script><form><textarea>BAD-value</textarea>
            <input value="BAD-input"><div contenteditable>BAD-entry</div></form>
            <p>Ostatnia szansa! https://offer.example/go?token=BAD-query</p>
            <div itemtype="https://schema.org/Product"><span itemprop="name">Produkt A</span></div>
            <div class="review" id="r"><span itemprop="reviewBody">Pierwsza opinia.</span>
            <div class="comment"><p class="comment-text">Zagnieżdżona odpowiedź.</p></div></div>
            <div class="reply" data-parent-id="missing"><p class="review-text">Osobna odpowiedź.</p></div>
            """, encoding="utf8")
        har = {"log": {"entries": [{"request": {"url": "https://user:BAD-password@a.example/p?token=BAD-query",
                                                "headers": [{"name": "Cookie", "value": "BAD-cookie"}],
                                                "postData": {"text": "BAD-input"}},
                                    "response": {"status": 302, "redirectURL": "/next?secret=BAD-location"}},
                                   {"request": {"url": "https://a.example/p?other=BAD-query"}, "response": {"status": 200}},
                                   {"request": {"url": "https://www.facebook.com/tr?id=12345678"}, "response": {"status": 200}}]}}
        (src / "log.har").write_text(json.dumps(har), encoding="utf8")
        folder, meta, result = self.imported(src)
        net = result["networks"][0]
        self.assertEqual(net["entries"][0]["redirect"], {"host": "a.example", "path": "/next"})
        self.assertEqual(len(net["repeated_resources"][0]["evidence"]), 2)
        self.assertEqual(result["pixels"][0]["value"]["id"], net["pixels"][0]["value"]["id"])
        self.assertNotIn("BAD-", json.dumps(result))
        self.assertEqual(result["pages"][0]["products"][0]["value"], "Produkt A")
        rows = result["opinions"]
        self.assertEqual([r["text"] for r in rows], ["Pierwsza opinia.", "Zagnieżdżona odpowiedź.", "Osobna odpowiedź."])
        self.assertEqual(rows[1]["parent_id"], rows[0]["id"])
        self.assertIsNone(rows[2]["parent_id"])
        self.assertEqual(rows[0]["reactions"], [])
        value = preview(folder, meta, result["signals"][0]["evidence"], "")
        self.assertIn("Ostatnia szansa!", value[1])
        self.assertNotIn("BAD-", value[1])
        self.assertEqual(preview(folder, meta, net["entries"][1]["evidence"], "")[1]["index"], 1)

    def test_repeated_reviews_preserve_occurrences_and_sources(self):
        original = "Ten produkt był dokładnie tym, czego szukałam od dawna."
        page = self.source("one.htm", '<section class="review">' + original + '</section>')
        left, _, _ = self.imported(page)
        card = self.source("two.json", {"quotes": [original, original.replace("dawna", "roku"), original]})
        right, _, _ = self.imported(card)
        pairs = list(matches(catalog(self.store), left.name))
        self.assertEqual([r[1] for r in pairs], [right.name] * 3)
        self.assertEqual([r[3] == 1 for r in pairs], [True, False, True])
        self.assertEqual(len({r[2]["id"] for r in pairs}), 3)

    def test_bad_artifact_leaves_good_text_and_reports_reason(self):
        src = self.tmp / "broken"
        src.mkdir()
        (src / "ad.png").write_bytes(b"bad")
        (src / "card.json").write_text('{"text":"Good"}')
        folder, meta, result = self.imported(src)
        self.assertEqual(result["ad"]["text"], "Good")
        self.assertTrue(result["issues"])
        (folder / "ad" / "card.json").write_text("{}")
        with self.assertRaises(ValueError):
            verified(folder, meta)

    def test_platform_threads_creative_ids_and_private_fields(self):
        document = {"id": "ad-1", "page_id": "p", "cards": [{"id": "v1", "text": "first"},
                   {"id": "v2", "text": "second"}], "comments": {"data": [
                   {"message": "Parent", "comments": {"data": [{"message": "Child", "like_count": 0}]}}]},
                   "body": 'Cookie: a=BAD-value; b=BAD-cookie\nhttps://a.example/access_token/BAD-path\n'
                           '{"access_token":"BAD-private"} password="BAD-first BAD-last"'}
        folder, meta, result = self.imported(self.source("ad.json", document))
        self.assertEqual(meta["ad_ref"], "ad-1")
        self.assertNotIn("BAD-", json.dumps(result))
        self.assertNotIn("BAD-", preview(folder, meta, next(f for f in result["ad_fields"] if f["field"] == "text")["evidence"])[1])
        rows = result["opinions"]
        self.assertEqual([r["text"] for r in rows], ["Parent", "Child"])
        self.assertEqual(rows[1]["parent_id"], rows[0]["id"])
        self.assertEqual(preview(folder, meta, rows[1]["evidence"], "Unrelated")[1]["text"], "Child")
        second = next(f for f in result["ad_fields"] if f["value"] == "second")
        self.assertEqual(preview(folder, meta, second["evidence"], "Unrelated"), ("text", "second"))

    def test_structured_comments_reactions_and_independent_code_proof(self):
        data = {"@type": "Comment", "text": "First", "interactionStatistic": {"interactionType":
                {"@type": "LikeAction"}, "userInteractionCount": 7}, "comment": [{"@type": "Comment", "text": "Second"}]}
        html = '<script type="application/ld+json">' + json.dumps(data) + '</script>'
        html += "<script>var token='BAD-secret'; fbq('init','12345678')</script>"
        html += '<div class="review"><span class="author">Person</span><p>A full review</p></div>'
        folder, meta, result = self.imported(self.source("page.html", html))
        first, second, plain = result["opinions"]
        self.assertEqual(first["reactions"][0]["count"], 7)
        self.assertEqual(second["parent_id"], first["id"])
        self.assertEqual(plain["text"], "A full review")
        self.assertEqual(preview(folder, meta, second["evidence"], "Wrong")[1]["opinions"][0]["text"], "Second")
        pixel = result["pages"][0]["pixels"][0]
        self.assertEqual(preview(folder, meta, pixel["evidence"], "Wrong"), ("text", "fbq('init','12345678'"))

    def test_saved_meta_html_media_identity_and_comments(self):
        from PIL import Image
        page = self.source("card.html", '<link rel="canonical" href="https://www.facebook.com/ads/library/?id=42">'
                           '<p>Creative text</p><img src="./card_files/creative.png">'
                           '<script type="application/ld+json">{"@type":"Comment","text":"On ad"}</script>')
        resources = self.tmp / "card_files"
        resources.mkdir()
        Image.new("RGB", (32, 32), "white").save(resources / "creative.png")
        folder, meta, result = self.imported(page)
        self.assertEqual((meta["provider"], meta["ad_ref"]), ("meta-ad-library", "42"))
        self.assertTrue(meta["availability"]["image"]["available"])
        self.assertFalse(meta["availability"]["landing"]["available"])
        self.assertEqual(result["opinions"][0]["source_kind"], "platform_comment")
        ref = next(f["evidence"] for f in result["ad_fields"] if f["field"] == "ad_ref")
        self.assertEqual(preview(folder, meta, ref)[1]["ad_ref"], "42")
        self.assertTrue((folder / "ad/card_files/creative.png").is_file())

    def test_new_model_can_enrich_existing_observation(self):
        media = self.source("clip.wav", "input")
        first, meta, result = self.imported(media)
        self.assertTrue(result["issues"])
        with patch("scamgraph.capture.transcribe", return_value={"segments": [], "text": "Test"}):
            second, newer, result = self.imported(media, model_dir=self.tmp)
            self.assertEqual(second, capture(media, self.store, model_dir=self.tmp))
        self.assertNotEqual(first, second)
        self.assertEqual(meta["observation_id"], newer["observation_id"])
        self.assertEqual(result["asr"][0]["text"], "Test")

    def test_analyst_can_open_signal_and_both_matched_sources(self):
        from streamlit.testing.v1 import AppTest
        text = "Sprawdziłam ofertę w zeszłym miesiącu i wróciłam."
        page = self.source("page.html", '<h1>Oferta</h1><p>Ostatnia szansa</p><div class="review">' + text + '</div>')
        folder, _, _ = self.imported(page)
        other, _, _ = self.imported(self.source("ad.json", {"page_name": "Karta", "quotes": [text]}))
        with patch.object(sys, "argv", ["scheduler_panel.py", "--store", str(self.store)]):
            app = AppTest.from_file(str(ROOT / "scheduler_panel.py"), default_timeout=20).run()
            app.button(key=folder.name).click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.tabs), 6)
            app.button(key="signal0").click().run()
            self.assertTrue(any("Lokalny dowód" in h.value for h in app.subheader))
            self.assertTrue(any("page.html" in row.value and "element" in row.value for row in app.text))
            for side in range(2):
                app.button(key=f"copy0-{side}").click().run()
                self.assertEqual(app.session_state["proof"][0], (folder if side == 0 else other).name)
                self.assertFalse(app.exception)

    @unittest.skipUnless(PRIVATE_STRUCT.is_dir(), "Prywatna próbka odbiorowa niedostępna")
    def test_private_acceptance_and_image_only(self):
        src = PRIVATE_STRUCT
        folder, meta, result = self.imported(src)
        rows = result["opinions"]
        html = next(src.glob("*.html"))
        original = html.read_text(encoding="utf-8")
        classes = [set(value.split()) for value in re.findall(r'\bclass="([^"]*)"', original)]
        self.assertEqual(len(rows), sum("fb-comment" in tags for tags in classes))
        self.assertEqual(sum(r["is_reply"] for r in rows), sum("fb-reply" in tags for tags in classes))
        likes = [v["count"] for r in rows for v in r["reactions"] if v["kind"] == "like"]
        self.assertEqual(likes, [int(n) for n in re.findall(r'class="meta-likes">\s*(\d+)\s*<', original)])
        self.assertEqual({r["source_kind"] for r in rows}, {"landing_review"})
        # Independent, fixture-only oracle for the full first review (private text stays on disk).
        first = re.search(r'<div class="fb-comment-text">(.*?)</div>', original, re.S)[1]
        self.assertEqual(rows[0]["text"], " ".join(unescape(first).split()))
        self.assertTrue(all(r["evidence"]["file"] == "landing/" + html.name for r in rows))
        har = read_json(next(src.glob("*.har")))
        assets = next(p for p in src.iterdir() if p.is_dir() and p.name.endswith("_files"))
        self.assertEqual(sum(len(h["entries"]) for h in result["networks"]), len(har["log"]["entries"]))
        self.assertEqual(sum(a["role"] == "asset" for a in meta["artifacts"]), sum(f.is_file() for f in assets.rglob("*")))
        self.assertEqual(result["ad_page_links"], [])
        self.assertTrue(all(r["parent_id"] for r in rows if r["is_reply"]))
        self.assertIn(rows[0]["text"], preview(folder, meta, rows[0]["evidence"], "")[1])
        _, meta, result = self.imported(next(src.glob("*.png")))
        self.assertEqual((result["opinion_source"], result["opinions"]), ("missing", []))
        self.assertFalse(meta["availability"]["landing"]["available"])
        self.assertFalse(meta["availability"]["har"]["available"])
        self.assertTrue(result["partial"])


if __name__ == "__main__":
    unittest.main()
