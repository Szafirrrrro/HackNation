"""Image-to-engine regressions on self-created assets; no organizer images."""
import copy
import io
import json
import random
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from scamgraph.image_query import analyze_image, image_card, image_references, validate_image
from graph.ftf_graph.card import parse_card
from graph.ftf_graph.scoring import Scorer


def picture(seed=0, fmt="PNG"):
    image = Image.new("RGB", (180, 120), "white")
    draw = ImageDraw.Draw(image)
    for x in range(10):
        draw.rectangle((x * 17, (x * 11 + seed * 29) % 100, x * 17 + 10, 119),
                       fill=((x * 37 + seed * 59) % 256, x * 23, seed * 57 % 256))
    out = io.BytesIO()
    image.save(out, format=fmt)
    return out.getvalue()


class ImageQueryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ocr = patch("scamgraph.image_query.ocr", side_effect=ValueError("Brak lokalnego silnika OCR"))
        self.ocr.start()
        self.addCleanup(self.ocr.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_validated_private_bytes_and_failure_degrades_to_image(self):
        data = picture()
        card = image_card(data, self.root / "private")
        self.assertEqual(Path(card["provenance"]["image_path"]).read_bytes(), data)
        self.assertEqual(len(card["visual"]["phash"]), 16)
        self.assertEqual(card["visual"]["origin_id"], card["text"]["ocr_origin_id"])
        self.assertIn("OCR", card["extraction"]["warnings"][0])
        self.assertTrue(all(e["method_version"] and e["source_ref"] for e in card["extraction"]["evidence"]))
        self.assertEqual(image_card(data, self.root / "private")["ad_id"], card["ad_id"])
        self.assertEqual(len(list((self.root / "private").iterdir())), 1)
        with self.assertRaises(ValueError):
            image_card(b"not an image", self.root / "invalid")
        self.assertFalse((self.root / "invalid").exists())

    def test_formats_and_limits(self):
        for fmt in ("PNG", "JPEG", "WEBP"):
            self.assertEqual(validate_image(picture(fmt=fmt))[0].size, (180, 120))
        for data in (b"", picture(fmt="GIF"), picture()[:40]):
            with self.assertRaises(ValueError):
                validate_image(data)
        with patch("scamgraph.image_query.MAX_BYTES", 10):
            with self.assertRaises(ValueError):
                validate_image(picture())
        with patch("scamgraph.image_query.MAX_PIXELS", 10):
            with self.assertRaises(ValueError):
                validate_image(picture())

    def make_corpus(self):
        root = self.root / "reference"
        root.mkdir()
        (root / "a.png").write_bytes(picture())
        (root / "broken.png").write_bytes(b"broken")
        (root / "manifest.json").write_text(json.dumps({"dataset_id": "own"}))
        records = [
            {"ad_id": "fresh-1", "image_path": "a.png", "text": "Oferta testowa numer jeden"},
            {"ad_id": "fresh-2", "image_path": "a.png"},
            {"ad_id": "fresh-1", "image_path": "a.png"},
            {"ad_id": "damaged", "image_path": "broken.png", "text": "Użyteczny tekst"},
            {"ad_id": "outside", "image_path": "../secret.png"},
            {"ad_id": "missing", "image_path": "missing.png", "text": "Sam tekst"},
        ]
        (root / "ads.jsonl").write_text("\n".join(json.dumps(r) for r in records))
        return root

    def test_reference_dedup_missing_fields_and_new_ids_reach_engine(self):
        root = self.make_corpus()
        result = analyze_image(picture(), str(root), self.root / "private")
        refs = result["references"]
        self.assertEqual(len(refs), 4)
        self.assertEqual(result["report"]["duplicate_ad_ids"], [])
        self.assertTrue(any(e["error"] == "conflicting_local_record" and e["ad_id"] == "fresh-1"
                            for e in result["report"]["errors"]))
        self.assertTrue(any("path_outside_corpus" in e["error"] for e in result["report"]["errors"]))
        self.assertEqual(refs[0]["visual"]["sha256"], refs[1]["visual"]["sha256"])
        self.assertNotEqual(refs[0]["ad_id"], refs[1]["ad_id"])
        self.assertIn("text", refs[2])
        cards = [parse_card(r, trusted=frozenset()) for r in refs + [result["card"]]]
        scores, edges = Scorer(cards).score_all()
        self.assertAlmostEqual(scores[0, -1], .95)
        self.assertTrue(any(r.kind == "image_sha256" for e in edges for r in e.reasons))

    def test_empty_missing_and_escaping_loose_reference(self):
        with self.assertRaises(ValueError):
            image_references(self.root / "missing")
        empty = self.root / "empty"
        empty.mkdir()
        with self.assertRaises(ValueError):
            image_references(empty)
        (self.root / "secret.png").write_bytes(picture())
        try:
            (empty / "escape.png").symlink_to(self.root / "secret.png")
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                self.skipTest("Windows user lacks permission to create a symbolic link")
            raise
        with self.assertRaisesRegex(ValueError, "poza katalogiem"):
            image_references(empty)

    def test_ocr_lines_keep_source_and_method(self):
        with patch("scamgraph.image_query.ocr", return_value=[{
            "value": "Oferta testowa", "method": "test-ocr/v1", "evidence": {"bbox": [1, 2, 3, 4]}}]):
            card = image_card(picture(), self.root / "private")
        self.assertEqual(card["text"]["ocr_text"], "Oferta testowa")
        self.assertEqual(card["extraction"]["warnings"], [])
        self.assertEqual(card["extraction"]["evidence"][-1]["method_version"], "test-ocr/v1")

    def test_same_source_signals_take_max_and_two_card_sha_survives(self):
        a = image_card(picture(), self.root / "private")
        b = copy.deepcopy(a)
        a["provenance"]["record_kind"] = "image_reference"
        a["ad_id"], b["ad_id"] = "unseen-ref", "unseen-query"
        for card in (a, b):
            card["text"]["ocr_text"] = "Ta sama bardzo charakterystyczna oferta"
        def score():
            return Scorer([parse_card(c, trusted=frozenset()) for c in (a, b)]).score_all()
        scores, edges = score()
        self.assertAlmostEqual(scores[0, 1], .95)
        # Without SHA, image + OCR still constitute only one source, not .84.
        a["visual"].pop("sha256")
        scores, edges = score()
        self.assertAlmostEqual(scores[0, 1], .60)
        self.assertIn("TF-IDF", " ".join(r.detail for e in edges for r in e.reasons))

    def test_query_does_not_change_reference_tfidf(self):
        def card(cid, text, kind):
            return parse_card({"ad_id": cid, "provenance": {"record_kind": kind},
                               "text": {"ocr_text": text}}, trusted=frozenset())
        refs = [card("a", "bardzo wyjątkowa oferta suplementu numer jeden", "image_reference"),
                card("b", "bardzo wyjątkowa oferta suplementu numer dwa", "image_reference")]
        before, _ = Scorer(refs).score_all()
        query = card("novel", "oferta suplementu jeden jeden jeden", "image_query")
        after, _ = Scorer(refs + [query]).score_all()
        self.assertEqual(before[0, 1], after[0, 1])
        # A query alone cannot train its own reference vocabulary.
        self.assertEqual(Scorer([query]).score_all()[1], [])

    def test_recompressed_variant_and_unrelated_image(self):
        ref = image_card(picture(), self.root / "private")
        ref["provenance"]["record_kind"] = "image_reference"
        variant = image_card(picture(fmt="JPEG"), self.root / "private")
        noise = Image.frombytes("RGB", (180, 120), random.Random(42).randbytes(180 * 120 * 3))
        buffer = io.BytesIO()
        noise.save(buffer, format="PNG")
        unrelated = image_card(buffer.getvalue(), self.root / "private")
        self.assertNotEqual(ref["visual"]["sha256"], variant["visual"]["sha256"])
        scores, edges = Scorer([parse_card(c, trusted=frozenset())
                                for c in (ref, variant, unrelated)]).score_all()
        self.assertGreaterEqual(scores[0, 1], .5)
        self.assertEqual(scores[0, 2], 0)
        self.assertTrue(any(r.kind == "phash" for e in edges if (e.a, e.b) == (0, 1)
                            for r in e.reasons))


if __name__ == "__main__":
    unittest.main()
