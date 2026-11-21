import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from scamgraph.capture import staging
from scamgraph.discovery.diagnostic import first_status, last_live_run, measure, playwright_api
from scamgraph.discovery.engine import SCHEMA
from pathlib import Path


class DiagnosticTests(unittest.TestCase):
    def test_dialog_handles_status_and_only_submits_explicitly(self):
        # AppTest installs its temporary script as __main__; Windows workers reuse that module.
        self.addCleanup(sys.modules.__setitem__, "__main__", sys.modules["__main__"])
        app = AppTest.from_string("""
from scamgraph.discovery.dashboard import diagnostic_dialog
diagnostic_dialog("local.json", "meta", {"country":"PL", "mode":"live", "permission":"test",
                                         "phrases":["domyślna"], "state_dir":"unused"})
""")
        with patch("scamgraph.discovery.dashboard.last_live_run", return_value=None), patch(
                "scamgraph.discovery.dashboard.run_diagnostic") as probe:
            app.run()
            app.text_input[0].set_value("  inna fraza  ")
            app.button[0].click().run()
            probe.assert_not_called()
            for status, expected in [(403, "HTTP 403"), (200, "HTTP 200"), (None, "Brak zmierzonego")]:
                probe.return_value = {"http_status": status}
                app.button[1].click().run()
                self.assertFalse(app.exception)
                probe.assert_called_with("local.json", "inna fraza")
                messages = [e.value for e in [*app.error, *app.success, *app.warning]]
                self.assertTrue(any(expected in text for text in messages), messages)
            app.run()
            self.assertEqual(probe.call_count, 3)

    def test_history_matches_source_country_phrase_and_live_mode(self):
        with staging(Path(tempfile.gettempdir())) as state:
            db = sqlite3.connect(state / "discovery.sqlite3")
            with db:
                db.executescript(SCHEMA)
                for i, mode, source, country in [(1, "live", "meta", "PL"), (2, "replay", "meta", "PL"),
                                                 (3, "live", "meta", "DE"), (4, "live", "other", "PL")]:
                    db.execute("INSERT INTO runs(run_id,source_id,trigger,mode,started,deadline,status,phrase) "
                               "VALUES (?,?,'gui',?,?,20,'success','kolejna')", (str(i), source, mode, i))
                    db.execute("""INSERT INTO observations(run_id,source_id,mode,provider,ad_ref,phrase,country,
                               reason,card,capture_id,found_at,locator,missing) VALUES (?,?,?,'provider','42',
                               'test',?,'match','{"main_document_http_status":200}','abc',1,'p',0)""",
                               (str(i), source, mode, country))
            db.close()
            run = last_live_run(state, "meta", "test", "PL")
            self.assertEqual((run["run_id"], run["http"], run["cards"]), ("1", "200", 1))
            self.assertIsNone(last_live_run(state, "meta", "inna", "PL"))

    def test_inactive_source_cannot_probe(self):
        for mode, permission in [("replay", "test"), ("live", True), ("live", ["test"]), ("live", " ")]:
            options = {"provider": "meta-ad-library", "mode": mode, "permission": permission}
            with self.subTest(mode=mode, permission=permission), patch(
                    "scamgraph.discovery.diagnostic.load_config", return_value={"sources": {"meta": options}}):
                with self.assertRaisesRegex(ValueError, "trybu live"):
                    measure("local.json", "fraza")

    @unittest.skipUnless(os.environ.get("SCAMGRAPH_TEST_CHROME"), "Opcjonalny lokalny Chrome")
    def test_chrome_measures_first_document_status_once(self):
        api = playwright_api()
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_response(int(self.path[1:]))
                self.send_header("Location", "/landing")
                self.end_headers()

            def log_message(self, *args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with api.sync_playwright() as driver, driver.chromium.launch(channel="chrome") as browser:
                    for status in (200, 302, 403, 429):
                        with browser.new_context() as context:
                            url = f"http://127.0.0.1:{server.server_port}/{status}"
                            self.assertEqual(first_status(context.new_page(), url), status)
            finally:
                server.shutdown()
        self.assertEqual(requests, ["/200", "/302", "/403", "/429"])
