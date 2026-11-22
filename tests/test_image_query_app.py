"""Real Streamlit upload -> extraction -> scorer -> graph, on generated images."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from scamgraph.image_query import analyze_image, reference_cards
from test_image_query import picture


class ImageFormTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        private = patch("scamgraph.analyst_store.PRIVATE_ROOT", self.root / "private-corpora")
        private.start()
        self.addCleanup(private.stop)
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
        extract_refs = patch("scamgraph.image_query.reference_cards", side_effect=lambda corpus:
                             reference_cards(corpus, state_dir=self.root / "private"))
        extract_refs.start()
        self.addCleanup(extract_refs.stop)
        self.extract = patch("scamgraph.image_query.analyze_image", side_effect=lambda data:
                             analyze_image(data, state_dir=self.root / "private"))
        self.mock_extract = self.extract.start()
        self.addCleanup(self.extract.stop)
        self.app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "graph/app.py"),
                                    default_timeout=30).run()
        self.base = int(self.app.metric[0].value)

    def submit(self, data):
        if not self.app.file_uploader:
            self.app.sidebar.button(key="nav-ad").click().run()
        self.app.file_uploader[0].set_value(("input.png", data, "image/png"))
        next(b for b in self.app.button if b.label == "Porównaj reklamę").click().run()

    def dashboard(self):
        self.app.sidebar.button(key="nav-overview").click().run()
        self.assertFalse(self.app.file_uploader)
        return self.app

    def test_upload_matches_real_reference_and_reruns_without_reextracting(self):
        self.app.sidebar.radio[0].set_value("Korpus organizatora NASK").run()
        self.assertEqual(int(self.app.metric[0].value), 2)
        self.submit(picture())
        app = self.app
        self.assertFalse(app.exception)
        self.assertFalse(any("referencyjn" in field.label for field in app.tabs[0].text_input))
        self.assertFalse(app.get("iframe"))
        self.assertTrue(any("Brak OCR" in w.value for w in app.warning))
        self.assertTrue(any("wspólne źródło" in c.value for c in app.caption))
        self.assertTrue(any("Identyczny plik obrazu (SHA-256)" in item.value for item in app.info))
        self.assertTrue(any("Do przeglądu" in item.value for item in app.warning))
        app.sidebar.slider[0].set_value(4).run()
        self.assertFalse(app.exception)
        self.dashboard()
        self.assertEqual(int(app.metric[0].value), 3)
        html = app.get("iframe")[0].proto.srcdoc
        self.assertIn("identyczny plik obrazu", html)
        self.assertIn("image:", html)
        self.mock_extract.assert_called_once()
        app.sidebar.button(key="nav-ad").click().run()
        app.button(key="clear-image").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(int(self.dashboard().metric[0].value), 2)

    def test_demo_does_not_import_nask_and_invalid_replacement_clears_query(self):
        self.submit(picture())
        self.assertEqual(int(self.dashboard().metric[0].value), self.base + 1)
        self.submit(b"broken")
        self.assertFalse(self.app.exception)
        self.assertTrue(self.app.error)
        self.assertEqual(int(self.dashboard().metric[0].value), self.base)
        self.submit(picture())
        self.assertFalse(self.app.exception)
        self.assertEqual(int(self.dashboard().metric[0].value), self.base + 1)

    def test_save_once_to_graph_corpus_and_clear_query(self):
        corpus_file = self.root / "cards.jsonl"
        sample = Path(__file__).resolve().parents[1] / "graph/data/sample_cards.jsonl"
        corpus_file.write_bytes(sample.read_bytes())
        self.app.sidebar.radio[0].set_value("Korpus lokalny").run()
        self.app.sidebar.text_input[0].set_value(str(corpus_file)).run()
        self.submit(picture())
        self.assertEqual(int(self.dashboard().metric[0].value), self.base + 1)
        self.app.sidebar.button(key="nav-ad").click().run()
        save = next(b for b in self.app.button if b.label.startswith("Dopisz image:"))
        save.click().run()
        self.assertFalse(self.app.exception)
        from scamgraph.analyst_store import private_corpus_path
        self.assertEqual(corpus_file.read_bytes(), sample.read_bytes())
        rows = [json.loads(line) for line in private_corpus_path(corpus_file).read_text().splitlines()]
        self.assertEqual(sum(r["ad_id"].startswith("image:") for r in rows), 1)
        self.assertFalse(any(b.label.startswith("Dopisz image:") for b in self.app.button))
        self.submit(picture())
        self.assertFalse(self.app.exception)
        self.assertFalse(any(b.label.startswith("Dopisz image:") for b in self.app.button))
        self.assertEqual(int(self.dashboard().metric[0].value), self.base + 1)


if __name__ == "__main__":
    unittest.main()
