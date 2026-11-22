"""Streamlit graph/app.py on scraper data from PostgreSQL. Wymaga pustej bazy testowej (TEST_DATABASE_URL).

    TEST_DATABASE_URL=postgresql://postgres@localhost:5432/scamgraph_test python -m unittest tests.test_database_source_app
"""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from scamgraph import db
from scamgraph.analyst_corpus import database_stamp, load_database_corpus
from scamgraph.discovery.control import read_control
from scamgraph.discovery.graph_feed import export_graph, update_campaigns

from tests import test_db, test_live_scheduler as base

URL = test_db.URL
APP = Path(__file__).resolve().parents[1] / "graph/app.py"


@unittest.skipUnless(URL, "brak TEST_DATABASE_URL")
class DatabaseSourceApp(unittest.TestCase):
    # Fixture of LiveScheduler without inheriting its tests.
    publish_three = test_db.DatabaseMirror.publish_three

    def setUp(self):
        base.LiveScheduler.setUp(self)
        test_db.reset()
        env = patch.dict(os.environ, {"DATABASE_URL": URL, "SCAMGRAPH_DISCOVERY_CONFIG": str(self.file)})
        env.start()
        self.addCleanup(env.stop)
        self.publish_three()
        self.feed = export_graph(self.state)
        update_campaigns(self.feed)

    def test_loader_returns_exported_cards_and_revision_changes_with_new_export(self):
        lines = [json.loads(line) for line in self.feed.read_text(encoding="utf8").splitlines()]
        with db.connect() as conn:
            corpus = load_database_corpus(conn, "live")
            before = database_stamp(conn, "live")
        self.assertEqual(corpus.dataset_id, "postgres:live")
        self.assertEqual(corpus.cards, lines)
        self.assertEqual(corpus.report["errors"], [])
        self.assertIsNotNone(before[0])
        self.assertIsNotNone(before[1])
        with db.connect() as conn:
            conn.execute("UPDATE feed_export SET written_ns = written_ns + 1 WHERE dataset_id = 'live'")
            self.assertNotEqual(database_stamp(conn, "live"), before)

    def test_app_defaults_to_database_and_draws_scraper_cards(self):
        app = AppTest.from_file(str(APP), default_timeout=60).run()
        self.assertEqual(app.exception, [])
        self.assertEqual(app.sidebar.radio[0].value, "Baza PostgreSQL (scraper)")
        self.assertEqual(app.sidebar.selectbox[0].value, "live")
        metrics = {m.label: m.value for m in app.metric}
        self.assertEqual(metrics["materiały"], "3")
        self.assertEqual(metrics["kampanie"], "0")  # min. 3 reklamy w kampanii; para 81-82 ma krawędź
        self.assertEqual(metrics["krawędzie SIMILAR"], "1")
        captions = " ".join(c.value for c in app.sidebar.caption)
        self.assertIn("postgres:live", captions)
        self.assertIn("przebieg silnika", captions)
        # Bazę zasila scraper: brak przycisku dopisywania do prywatnego korpusu.
        self.assertFalse([b for b in app.button if b.label.startswith("Dopisz")])

    def test_scraper_controls_pause_resume_and_intervals(self):
        app = AppTest.from_file(str(APP), default_timeout=60).run()
        stop = next(b for b in app.sidebar.button if b.label == "Stop")
        stop.click().run()
        self.assertTrue(read_control(self.state)["paused"])
        scrape, graph = [n for n in app.sidebar.number_input if n.label.endswith("(min)")]
        scrape.set_value(5.0)
        graph.set_value(6.0)
        next(b for b in app.sidebar.button if b.label == "Zapisz interwały").click().run()
        control = read_control(self.state)
        self.assertEqual((control["interval_seconds"], control["graph_interval_seconds"]), (300.0, 360.0))
        next(b for b in app.sidebar.button if b.label == "Start").click().run()
        self.assertFalse(read_control(self.state)["paused"])
        next(b for b in app.sidebar.button if b.label == "Przebuduj graf teraz").click().run()
        self.assertIsNotNone(read_control(self.state)["graph_requested"])
        self.assertEqual(app.exception, [])

    def test_missing_database_url_explains_setup(self):
        with patch.dict(os.environ, {"DATABASE_URL": ""}):
            app = AppTest.from_file(str(APP), default_timeout=60).run()
            app.sidebar.radio[0].set_value("Baza PostgreSQL (scraper)").run()
        self.assertEqual(app.exception, [])
        self.assertTrue(any("DATABASE_URL" in e.value for e in app.sidebar.error))


if __name__ == "__main__":
    unittest.main()
