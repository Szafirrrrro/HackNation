"""Real Streamlit upload -> extraction -> scorer -> graph, on generated images."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from scamgraph.image_query import analyze_image
from test_image_query import picture


class ImageFormTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.refs = self.root / "references"
        self.refs.mkdir()
        (self.refs / "source.png").write_bytes(picture())
        (self.refs / "different.png").write_bytes(picture(7))
        self.addCleanup(self.tmp.cleanup)
        self.ocr = patch("scamgraph.image_query.ocr", side_effect=ValueError("Brak OCR"))
        self.ocr.start()
        self.addCleanup(self.ocr.stop)
        self.default_refs = patch("scamgraph.image_query.DEFAULT_REFERENCES", self.refs)
        self.default_refs.start()
        self.addCleanup(self.default_refs.stop)
        self.extract = patch("scamgraph.image_query.analyze_image", side_effect=lambda data:
                             analyze_image(data, state_dir=self.root / "private"))
        self.mock_extract = self.extract.start()
        self.addCleanup(self.extract.stop)
        self.app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "graph/app.py"),
                                    default_timeout=30).run()
        self.base = int(self.app.metric[0].value)

    def submit(self, data):
        self.app.file_uploader[0].set_value(("input.png", data, "image/png"))
        next(b for b in self.app.button if b.label == "Analizuj zdjęcie").click().run()

    def test_upload_matches_real_reference_and_reruns_without_reextracting(self):
        self.submit(picture())
        app = self.app
        self.assertFalse(app.exception)
        self.assertFalse(any("referencyjn" in field.label for field in app.text_input))
        self.assertEqual(int(app.metric[0].value), self.base + 3)
        html = app.get("iframe")[0].proto.srcdoc
        self.assertIn("identyczny plik obrazu", html)
        self.assertIn("image:", html)
        self.assertTrue(any("Brak OCR" in w.value for w in app.warning))
        self.assertTrue(any("wspólne źródło" in c.value for c in app.caption))
        app.sidebar.slider[0].set_value(4).run()
        self.assertFalse(app.exception)
        self.assertEqual(int(app.metric[0].value), self.base + 3)
        self.mock_extract.assert_called_once()
        app.button(key="clear-image").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(int(app.metric[0].value), self.base)

    def test_invalid_replacement_clears_previous_query_and_missing_default_uses_cards(self):
        self.submit(picture())
        self.submit(b"broken")
        self.assertFalse(self.app.exception)
        self.assertTrue(self.app.error)
        self.assertEqual(int(self.app.metric[0].value), self.base)
        with patch("scamgraph.image_query.DEFAULT_REFERENCES", self.root / "missing"):
            self.submit(picture())
        self.assertFalse(self.app.exception)
        self.assertEqual(int(self.app.metric[0].value), self.base + 1)
        self.assertEqual(self.app.session_state["image_analysis"]["references"], [])

    def test_save_once_to_graph_corpus_and_clear_query(self):
        corpus_file = self.root / "cards.jsonl"
        sample = Path(__file__).resolve().parents[1] / "graph/data/sample_cards.jsonl"
        corpus_file.write_bytes(sample.read_bytes())
        self.app.sidebar.text_input[0].set_value(str(corpus_file)).run()
        self.submit(picture())
        self.assertEqual(int(self.app.metric[0].value), self.base + 3)
        save = next(b for b in self.app.button if b.label.startswith("Dopisz image:"))
        save.click().run()
        self.assertFalse(self.app.exception)
        rows = [json.loads(line) for line in corpus_file.read_text().splitlines()]
        self.assertEqual(sum(r["ad_id"].startswith("image:") for r in rows), 1)
        self.assertFalse(any(b.label.startswith("Dopisz image:") for b in self.app.button))
        self.submit(picture())
        self.assertFalse(self.app.exception)
        self.assertEqual(int(self.app.metric[0].value), self.base + 3)
        self.assertFalse(any(b.label.startswith("Dopisz image:") for b in self.app.button))


if __name__ == "__main__":
    unittest.main()
