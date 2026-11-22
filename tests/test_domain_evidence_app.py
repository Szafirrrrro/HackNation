"""Popularity must neither hide material nor be presented as safety."""
from importlib.util import find_spec
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1] / "graph/app.py"


@unittest.skipUnless(all(find_spec(name) for name in ("streamlit", "pyvis", "plotly")),
                     "Requires graph/requirements-app.txt")
class DomainEvidenceAppTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        private = patch("scamgraph.analyst_store.PRIVATE_ROOT", self.root / "private")
        private.start()
        self.addCleanup(private.stop)

    def open(self, broken_overlay=False):
        from scamgraph.analyst_store import private_corpus_path
        from streamlit.testing.v1 import AppTest
        rows = (APP.parent / "data/sample_cards.jsonl").read_text(encoding="utf-8")
        for host in ("jotform.com", "bit.ly"):
            rows += json.dumps({"ad_id": "AD-" + host, "infra": {"final_domain": host}}) + "\n"
        corpus = self.root / "corpus.jsonl"
        corpus.write_text(rows, encoding="utf-8")
        if broken_overlay:
            overlay = private_corpus_path(corpus)
            overlay.parent.mkdir(parents=True)
            overlay.write_text('{"broken\n{"ad_id":"bad","visual":{"phash":"not-hex"}}\n'
                               '{"ad_id":"wide","visual":{"phash":"' + "f" * 40 + '"}}\n'
                               '{"ad_id":"shape","extensions":{"page_observation":"x"}}\n', encoding="utf-8")
        app = AppTest.from_file(str(APP), default_timeout=60).run()
        app.sidebar.radio[0].set_value("Korpus lokalny").run()
        app.sidebar.text_input[0].set_value(str(corpus)).run()
        return app

    def test_popular_targets_stay_visible_until_analyst_hides_them(self):
        app = self.open()
        self.assertFalse(app.exception)
        self.assertEqual(int(app.metric[4].value), 0)
        box = next(c for c in app.checkbox if c.label.startswith("ukryj"))
        self.assertFalse(box.value)
        box.check().run()
        self.assertEqual(int(app.metric[4].value), 2)
        self.assertNotIn("zaufan", " ".join([box.label, box.help, app.metric[4].label]).lower())

    def test_broken_private_line_warns_instead_of_crashing(self):
        app = self.open(broken_overlay=True)
        self.assertFalse(app.exception)
        self.assertTrue(any("prywatnego korpusu" in w.value for w in app.warning))
