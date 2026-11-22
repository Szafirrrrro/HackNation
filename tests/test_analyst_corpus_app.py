"""Import and inspect self-created sources through the normal analyst UI."""
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

from streamlit.testing.v1 import AppTest

from graph.ftf_graph.card import parse_card
from scamgraph.image_query import analyze_image
from scamgraph.analyst_corpus import identify_corpus, load_analyst_corpus
from scamgraph.analyst_store import append_private_card, private_corpus_path
from scamgraph.analyst_timeline import card_events, event
from scamgraph.graph_features import text_features
from test_image_query import picture


APP = Path(__file__).resolve().parents[1] / "graph/app.py"


def jsonl(path, rows):
    path.write_text("\n".join(json.dumps(row) if isinstance(row, dict) else row for row in rows), encoding="utf-8")


def timeline_rows(app):
    markup = next(node.proto.body for node in app.get("html") if 'class="analyst-evidence-table"' in node.proto.body)
    table = ElementTree.fromstring(markup)
    labels = [cell.text for cell in table.findall(".//thead/tr/th")]
    return [dict(zip(labels, (cell.text for cell in row))) for row in table.findall(".//tbody/tr")]


class AnalystCorpusTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.observations = self.root / "observations"
        self.observations.mkdir()
        (self.root / "manifest.json").write_text('{"dataset_id":"own-audit","schema_version":"v0"}')
        self.source = {"kind": "synthetic", "provider": "own", "ad_ref": "lib-7",
                       "published_at": "2026-10-08", "collected_at": "2026-10-09T11:32:00+02:00"}
        self.ad = {"ad_id": "fresh-A", "source": self.source,
                   "text": "Wlasny przyklad oferty na kurs astronomii"}
        self.page_a = {"capture_id": "page-A", "bundle_ids": ["fresh-A"],
                       "document": {"url_without_query": "https://example.test/offer"},
                       "html": {"title": "Wlasny tytul", "headings": ["Przykladowy naglowek"]},
                       "har": {"document_started_at": "2026-10-09T11:01:00+02:00", "document_status": 200,
                               "meta_pixel_ids": ["test-42"]}}
        self.page_b = {**self.page_a, "capture_id": "page-B",
                       "document": {"url_without_query": "https://second.example.test/offer"}}
        jsonl(self.root / "ads.jsonl", [self.ad, "{broken", {**self.ad, "ad_id": "alias"},
              {**self.ad, "source": {**self.source, "ad_ref": "conflict"}},
              {"ad_id": "fresh-B", "text": self.ad["text"]}])
        jsonl(self.observations / "pages.jsonl", [self.page_a, "[]", self.page_b])
        private = patch("scamgraph.analyst_store.PRIVATE_ROOT", self.root / "private-ui")
        private.start()
        self.addCleanup(private.stop)

    def open_local(self, path):
        app = AppTest.from_file(str(APP), default_timeout=45).run()
        app.sidebar.radio[0].set_value("Korpus lokalny").run()
        return app.sidebar.text_input[0].set_value(str(path)).run()

    def test_v0_identity_conflicts_and_sources_are_visible_and_pages_do_not_create_ad_edges(self):
        app = self.open_local(self.root / "manifest.json")
        self.assertFalse(app.exception)
        self.assertEqual(int(app.metric[0].value), 2)
        self.assertEqual(int(app.metric[1].value), 0)
        report = app.session_state["corpus_import"][1].report
        self.assertEqual([item["ad_id"] for item in report["duplicates"]], ["alias"])
        self.assertEqual([item["line"] for item in report["errors"]], [2, 4, 2])
        self.assertEqual(report["errors"][1]["first_line"], 1)
        self.assertEqual(report["page_captures"], 2)
        self.assertEqual(report["verified_links"], 0)
        self.assertTrue(any("test-42" in item.value for item in app.markdown))
        self.assertTrue(any("Zapisy stron: 2" in item.value for item in app.caption))
        self.assertTrue(any("Data publikacji nieustalona" in item.value and "fresh-B" in item.value
                            for item in app.caption))
        rows = timeline_rows(app)
        publication = next(row for row in rows if row["Zdarzenie"] == "Publikacja")
        self.assertEqual(publication["Data źródłowa"], "2026-10-08")
        self.assertEqual(publication["Precyzja"], "dzień")
        self.assertIn("ads.jsonl:1#source.published_at", publication["Źródło"])
        self.assertIn("har.document_started_at", " ".join(row["Źródło"] for row in rows))
        lines = json.loads(app.get("plotly_chart")[0].proto.spec)["data"]
        self.assertEqual({line["name"]: line["y"] for line in lines},
                         {"Zapis strony": [2], "bez kampanii": [1]})
        self.assertTrue(all(line["mode"] == "lines+markers" for line in lines))
        self.assertEqual({line["name"]: line["marker"]["symbol"] for line in lines},
                         {"Zapis strony": ["square"], "bez kampanii": ["square"]})
        self.assertTrue(any(item.label == "Jak czytać oś czasu" for item in app.expander))

        app = app.sidebar.text_input[0].set_value(str(self.observations / "pages.jsonl")).run()
        self.assertFalse(app.exception)
        self.assertEqual(int(app.metric[0].value), 0)
        self.assertTrue(any("Zapisy stron: 2" in item.value for item in app.caption))

    def test_verified_source_field_grants_link_and_wrong_evidence_does_not(self):
        jsonl(self.root / "export.jsonl", [{"id": "lib-7", "destination_url": self.page_a["document"]["url_without_query"]}])
        link_path = self.observations / "ad_page_links.jsonl"
        link = {"ad_id": "fresh-A", "capture_id": "page-A", "origin_id": "export-line-1",
                "observed_at": "2026-10-09T11:01:00+02:00", "source_ref": {"file": "export.jsonl",
                    "record_id": "lib-7", "field": "destination_url",
                    "value": self.page_a["document"]["url_without_query"]}}
        jsonl(link_path, [link, {**link, "ad_id": "fresh-B", "capture_id": "page-B"}])
        result = load_analyst_corpus(self.root / "ads.jsonl")
        self.assertEqual(result.report["verified_links"], 1)
        self.assertEqual(result.cards[0]["page"]["tracking_ids"]["meta_pixel"], "test-42")
        self.assertNotIn("page", result.cards[1])
        events = card_events(parse_card(result.cards[0], trusted=frozenset()))
        acquisition = next(event for event in events if event.kind == "Pozyskanie")
        self.assertEqual(acquisition.instant, datetime(2026, 10, 9, 9, 32, tzinfo=timezone.utc))
        self.assertTrue(any(event.kind == "Obserwacja powiązanej strony" for event in events))

    def test_engine_jsonl_keeps_good_rows_and_pair_sources(self):
        path = self.root / "cards.jsonl"
        shared = {"page": {"tracking_ids": {"meta_pixel": "own-123"}}}
        source_ref = "raw-one  <source & evidence>\n next line"
        a = {**shared, "ad_id": "x-1", "first_seen": "2026-10-08T12:00:00Z",
             "provenance": {"provider": "own", "ad_ref": "one", "source_ref": source_ref}}
        b = {**shared, "ad_id": "x-2", "provenance": {"provider": "own", "ad_ref": "two", "source_ref": "raw-two"}}
        jsonl(path, [a, "{bad", {**a, "ad_id": "alias"}, {**a, "provenance": {"provider": "own", "ad_ref": "three"}}, b])
        app = self.open_local(path)
        self.assertFalse(app.exception)
        self.assertEqual(int(app.metric[0].value), 2)
        self.assertEqual(timeline_rows(app)[0]["Źródło"], source_ref + "#first_seen")
        graph = app.get("iframe")[0].proto.srcdoc
        self.assertNotIn("https://cdn.jsdelivr.net/npm/bootstrap", graph)
        self.assertIn("Content-Security-Policy", graph)
        pair = next(widget for widget in app.selectbox if widget.label == "Wybierz parę z grafu")
        pair.set_value("x-1 ↔ x-2").run()
        self.assertFalse(app.exception)
        sources = "\n".join(item.proto.body for item in app.get("json"))
        self.assertTrue(all(locator in sources for locator in ("raw-one", "raw-two")))

    def test_engine_jsonl_recognized_under_v0_filenames_even_with_a_mixed_prefix(self):
        sample = (APP.parent / "data/sample_cards.jsonl").read_bytes()
        ads_path = self.root / "ads.jsonl"
        pages_path = self.root / "pages.jsonl"
        ads_path.write_bytes(sample)
        pages_path.write_bytes(sample)
        for path in (ads_path, pages_path):
            with self.subTest(path=path):
                source = identify_corpus(path)
                self.assertEqual(source.storage_path, path.resolve())
                self.assertEqual(len(load_analyst_corpus(source).cards), 27)

        pages_path.write_bytes(b'\xffbad\n{"capture_id":"loose-page"}\n{"ad_id":"raw","text":"Raw ad"}\n' + sample)
        mixed = load_analyst_corpus(pages_path)
        self.assertEqual(len(mixed.cards), 27)
        self.assertEqual(len(mixed.pages), 0)
        self.assertEqual(sorted(row["line"] for row in mixed.report["errors"]), [1, 2, 3])

        append_private_card(ads_path, {"ad_id": "private-for-ads"})
        self.assertTrue(private_corpus_path(ads_path).is_file())
        self.assertFalse(private_corpus_path(pages_path).exists())
        app = self.open_local(ads_path)
        self.assertFalse(app.exception)
        self.assertEqual(int(app.metric[0].value), 28)
        app.sidebar.text_input[0].set_value(str(pages_path)).run()
        self.assertFalse(app.exception)
        self.assertEqual(int(app.metric[0].value), 27)

    def test_raw_content_recognized_under_custom_filenames_and_timeline_survives_utc_overflow(self):
        ads_path = self.root / "custom.jsonl"
        page = {**self.page_a, "har": {**self.page_a["har"], "document_started_at": "0001-01-01T00:00:00+01:00"}}
        jsonl(ads_path, ["{broken", self.ad])
        jsonl(self.observations / "pages.jsonl", [page])
        source = identify_corpus(ads_path)
        self.assertEqual(source.storage_path, ads_path.resolve())
        result = load_analyst_corpus(source)
        self.assertEqual(len(result.cards), 1)
        self.assertIn("custom.jsonl:2", result.cards[0]["provenance"]["source_ref"])
        value, locator = result.pages[0].captured_at
        item = event("page-A", "Obserwacja strony", value, locator)
        self.assertIsNone(item.instant)
        self.assertEqual(item.precision, "poza zakresem UTC")
        self.assertEqual(item.value, value)

        app = self.open_local(ads_path)
        self.assertFalse(app.exception)
        row = next(row for row in timeline_rows(app) if row["Data źródłowa"] == value)
        self.assertEqual(row["Precyzja"], "poza zakresem UTC")

    def test_ad_form_keeps_useful_input_and_distinguishes_engine_outcomes(self):
        path = self.root / "cards.jsonl"
        description = "Kurs astronomii obejmuje obserwacje komet i porownanie teleskopow"
        rows = [{"ad_id": f"in-campaign-{i}", "text": text_features(description, f"text-{i}"),
                 "infra": {"final_domain": "stars.example.test", "origin_id": f"url-{i}"}}
                for i in range(3)]
        rows += [{"ad_id": f"independent-{i}", "infra": {"final_domain": f"unrelated-{i}.test"}} for i in range(9)]
        jsonl(path, rows)
        app = self.open_local(path)
        self.assertEqual(int(app.metric[1].value), 1)
        reference = app.session_state["engine_reference"][1]
        app.sidebar.button(key="nav-ad").click().run()
        self.assertFalse(app.get("iframe"))

        def submit(text, url):
            tab = app.tabs[0]
            tab.text_area[0].set_value(text)
            tab.text_input[0].set_value(url)
            tab.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["engine_reference"][1].fingerprint, reference.fingerprint)

        submit(description, "https://stars.example.test/offer")
        self.assertTrue(any("Dodaj zdjęcie" in item.value for item in app.error))
        self.assertEqual(app.text_area[0].value, description)
        with (
            patch("scamgraph.image_query.analyze_image",
                  side_effect=lambda data: analyze_image(data, state_dir=self.root / "private")),
            patch("scamgraph.image_query.ocr", return_value=[]),
        ):
            app.file_uploader[0].set_value(("bad.png", b"broken", "image/png"))
            submit(description, "https://stars.example.test/offer")
            self.assertTrue(any("Nie udało się przeanalizować" in item.value for item in app.error))
            self.assertFalse(app.success)
            app.file_uploader[0].set_value(("ad.png", picture(), "image/png"))
            submit(description, "https://stars.example.test/offer")
            self.assertTrue(any("Prawdopodobne dopasowanie" in item.value for item in app.success))
            submit("Regularne pieczenie chleba zytniego i miesienie ciasta", "https://bread.example.test/")
            self.assertTrue(any("Możliwy nowy wzorzec" in item.value for item in app.warning))
            submit("x", "")
            self.assertTrue(any("Niewystarczające dane" in item.value for item in app.warning))


if __name__ == "__main__":
    unittest.main()
