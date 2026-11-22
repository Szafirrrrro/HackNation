"""Exercise the URL form through Streamlit, without contacting external sites."""
from importlib.util import find_spec
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(all(find_spec(name) for name in ("streamlit", "pyvis", "plotly")),
                     "Requires graph/requirements-app.txt")
class URLFormTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        private = patch("scamgraph.analyst_store.PRIVATE_ROOT", Path(temp.name) / "private")
        private.start()
        self.addCleanup(private.stop)

    def test_existing_url_is_highlighted_without_fetch_or_duplicate_even_when_noise_hidden(self):
        import json
        import re
        from streamlit.testing.v1 import AppTest

        app_file = Path(__file__).resolve().parents[1] / "graph/app.py"
        with tempfile.TemporaryDirectory() as tmp, patch("scamgraph.url_capture.capture_url") as fetch:
            corpus = Path(tmp) / "cards.jsonl"
            sample = app_file.parent / "data/sample_cards.jsonl"
            rows = [json.loads(line) for line in sample.read_text().splitlines()]
            rows.append({"ad_id": "page:existing", "provenance": {
                "record_kind": "page_capture", "url": "own.example/offer"}})
            corpus.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            original = corpus.read_bytes()
            app = AppTest.from_file(str(app_file), default_timeout=30).run()
            app.sidebar.text_input[0].set_value(str(corpus)).run()
            app.sidebar.checkbox[1].set_value(False).run()
            app.text_input[0].set_value("https://OWN.example/offer#details")
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any("już jest w bazie danych" in item.value for item in app.info))
            self.assertEqual(int(app.metric[0].value), len(rows))
            document = app.get("iframe")[0].proto.srcdoc
            nodes = json.loads(re.search(r"nodes = new vis.DataSet\((\[.*?\])\);", document, re.S)[1])
            self.assertEqual(next(n for n in nodes if n["id"] == "page:existing")["shape"], "star")
            self.assertFalse(any(b.label.startswith("Dopisz page:") for b in app.button))
            app.sidebar.slider[0].set_value(4).run()
            self.assertFalse(app.exception)
            self.assertEqual(int(app.metric[0].value), len(rows))
            self.assertEqual(corpus.read_bytes(), original)
            fetch.assert_not_called()

    def test_saved_url_stays_highlighted_and_resubmission_does_not_fetch(self):
        import json
        from streamlit.testing.v1 import AppTest

        app_file = Path(__file__).resolve().parents[1] / "graph/app.py"
        with tempfile.TemporaryDirectory() as tmp, patch("scamgraph.url_capture.capture_url") as fetch:
            corpus = Path(tmp) / "cards.jsonl"
            corpus.write_bytes((app_file.parent / "data/sample_cards.jsonl").read_bytes())
            fetch.return_value = {"archive": tmp, "report": {"status": "success", "content_status": "usable"},
                "card": {"ad_id": "page:new", "provenance": {"record_kind": "page_capture", "url": "own.example/"}}}
            app = AppTest.from_file(str(app_file), default_timeout=30).run()
            app.sidebar.text_input[0].set_value(str(corpus)).run()
            count = int(app.metric[0].value)
            app.text_input[0].set_value("https://own.example/?offer=1")
            app.button[0].click().run()
            next(b for b in app.button if b.label.startswith("Dopisz page:")).click().run()
            self.assertFalse(app.exception)
            self.assertEqual(int(app.metric[0].value), count + 1)
            self.assertFalse(any(b.label.startswith("Dopisz page:") for b in app.button))
            self.assertTrue(any("już jest w bazie danych" in item.value for item in app.info))
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(int(app.metric[0].value), count + 1)
            fetch.assert_called_once()
            from scamgraph.analyst_store import private_corpus_path
            self.assertEqual(corpus.read_bytes(), (app_file.parent / "data/sample_cards.jsonl").read_bytes())
            rows = [json.loads(line) for line in private_corpus_path(corpus).read_text().splitlines()]
            self.assertEqual(sum(row["ad_id"].startswith("page:") for row in rows), 1)

    def test_page_menu_stays_in_details_and_not_in_graph_tooltip(self):
        import json
        import re
        from streamlit.testing.v1 import AppTest

        app_file = Path(__file__).resolve().parents[1] / "graph/app.py"
        with tempfile.TemporaryDirectory() as tmp:
            full_text = "Home\nLogin\n" + "Language\n" * 1000
            card = {"ad_id": "page:long", "infra": {"final_domain": "own.example"},
                    "text": {"ad_text": full_text}, "provenance": {"record_kind": "page_capture"},
                    "extensions": {"page_observation": {"pages": [{
                        "titles": [{"value": '<a href=x>Own offer A & B</a><img src=x onerror=alert(1)>'}], "reading_text": [
                            {"section": "interface", "value": "Home Login Language"},
                            {"section": "content", "value": "Useful offer details"}]}]}}}
            app = AppTest.from_file(str(app_file), default_timeout=30).run()
            app.session_state["url_capture"] = {"archive": tmp, "card": card,
                "report": {"status": "success", "content_status": "usable"}}
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(app.text_area[0].value, full_text)
            self.assertTrue(app.text_area[0].disabled)
            document = app.get("iframe")[0].proto.srcdoc
            nodes = json.loads(re.search(r"nodes = new vis.DataSet\((\[.*?\])\);", document, re.S)[1])
            title = next(node["title"] for node in nodes if node["id"] == "page:long")
            self.assertIn("Own offer A & B", title)
            self.assertNotIn("&amp;", title)
            self.assertIn("popup.innerText = nodeData[0].title;", document)
            self.assertNotIn("popup.innerHTML = nodeData[0].title;", document)
            self.assertIn("Useful offer details", title)
            self.assertIn("domena: own.example", title)
            self.assertNotIn("Language", title)
            self.assertLess(len(title), 500)

    def test_missing_trust_dependency_displays_error_without_crashing(self):
        from streamlit.testing.v1 import AppTest

        app_file = Path(__file__).resolve().parents[1] / "graph/app.py"
        with patch("graph.ftf_graph.trusted.default_psl_path", side_effect=RuntimeError("Brak PSL")):
            app = AppTest.from_file(str(app_file), default_timeout=30).run()
            self.assertFalse(app.exception)
            self.assertTrue(any("Brak PSL" in error.value for error in app.error))

    def test_popular_url_fetches_without_safety_claim(self):
        from streamlit.testing.v1 import AppTest

        app_file = Path(__file__).resolve().parents[1] / "graph/app.py"
        with tempfile.TemporaryDirectory() as tmp, patch("scamgraph.url_capture.visit",
                return_value={"page_id": "fixture", "status": "failed"}) as visit, patch(
                "scamgraph.url_capture.capture", side_effect=OSError("fixture")):
            app = AppTest.from_file(str(app_file), default_timeout=30).run()
            app.text_input[0].set_value("https://bit.ly/x")
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertFalse(any("bezpieczn" in s.value for s in app.success))
            visit.assert_called_once()

    def test_capture_automatically_enters_graph_alongside_separate_image_form(self):
        from streamlit.testing.v1 import AppTest

        app_file = Path(__file__).resolve().parents[1] / "graph/app.py"
        with tempfile.TemporaryDirectory() as tmp, patch("scamgraph.url_capture.capture_url") as fetch:
            archive = Path(tmp)
            for name in ("page.html", "network.har", "metadata.json", "extracted.json", "manifest.json"):
                (archive / name).write_text("{}")
            card = {"ad_id": "page:fixture", "infra": {"final_domain": "own.example"},
                    "text": {"ad_text": "Own synthetic page"},
                    "provenance": {"record_kind": "page_capture", "source": "analyst_url"}}
            fetch.return_value = {"report": {"status": "success", "content_status": "usable"},
                                  "archive": str(archive), "capture": str(archive), "card": card}
            app = AppTest.from_file(str(app_file), default_timeout=30).run()
            count = int(app.metric[0].value)
            app.text_input[0].set_value("https://own.example/")
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(int(app.metric[0].value), count + 1)
            self.assertTrue(any("page:fixture" in w.value for w in app.warning))
            self.assertEqual(len(app.get("file_uploader")), 1)
            self.assertFalse(app.get("download_button"))
            self.assertFalse(app.selectbox)
            app.sidebar.slider[0].set_value(4).run()
            self.assertFalse(app.exception)
            self.assertEqual(int(app.metric[0].value), count + 1)
            fetch.assert_called_once_with("https://own.example/")

            # A failed replacement must remove the previous query from analysis.
            fetch.side_effect = RuntimeError("capture failed")
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.error)
            self.assertEqual(int(app.metric[0].value), count)

    def test_submit_rerun_and_missing_corpus(self):
        from streamlit.testing.v1 import AppTest

        app_file = Path(__file__).resolve().parents[1] / "graph/app.py"
        with tempfile.TemporaryDirectory() as tmp, patch("scamgraph.url_capture.capture_url") as fetch:
            archive = Path(tmp)
            (archive / "page.html").write_text("<h1>Own fixture</h1>")
            fetch.return_value = {"report": {"status": "success", "content_status": "usable"},
                                  "archive": str(archive), "capture": None}
            app = AppTest.from_file(str(app_file), default_timeout=30).run()
            self.assertFalse(app.exception)
            fetch.assert_not_called()
            app.sidebar.text_input[0].set_value(str(archive / "missing.jsonl")).run()
            app.text_input[0].set_value("https://own.example/")
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.success)
            fetch.assert_called_once_with("https://own.example/")
            app.run()
            self.assertTrue(app.success)
            fetch.assert_called_once()

    def test_invalid_address_displays_error(self):
        from streamlit.testing.v1 import AppTest

        app_file = Path(__file__).resolve().parents[1] / "graph/app.py"
        with patch("scamgraph.url_capture.visit") as fetch:
            app = AppTest.from_file(str(app_file), default_timeout=30).run()
            app.text_input[0].set_value("file:///etc/passwd")
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.error)
            fetch.assert_not_called()
