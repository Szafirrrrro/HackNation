"""Zapis do PostgreSQL (scamgraph.db). Wymaga pustej bazy testowej:

    TEST_DATABASE_URL=postgresql://postgres@localhost:5432/scamgraph_test python -m unittest tests.test_db

Bez TEST_DATABASE_URL testy są pomijane. Każdy test czyści schemat public tej bazy.
"""
import json
import os
import socket
import tempfile
import threading
import time
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from scamgraph import db
from scamgraph.capture import read_json, staging, write_json
from scamgraph.discovery import landing_visit, meta
from scamgraph.discovery.engine import connection, store_card
from scamgraph.discovery.graph_feed import capture_metadata, export_graph, update_campaigns
from scamgraph.discovery.service import publish

from tests import test_live_scheduler as base

URL = os.environ.get("TEST_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[1]


def reset():
    import psycopg

    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    db._schema_ready.clear()


def write_capture(folder, ad, page_id):
    landing = folder / "landing"
    landing.mkdir(parents=True, exist_ok=True)
    write_json(landing / "metadata.json", {
        "input_url": "https://shop.example/offer?tracking=123",
        "captured_at": "2026-11-21T10:00:00+00:00", "status": "failed", "http_status": 502,
    })
    write_json(folder / "extracted.json", {"ad": ad, "landing_visit": {"page_id": page_id}})
    artifact = {"path": "landing/metadata.json", "sha256": db.sha256((landing / "metadata.json").read_bytes())}
    write_json(folder / "manifest.json", {
        "capture_id": folder.name, "artifacts": [artifact],
        "result": {"path": "extracted.json", "sha256": db.sha256((folder / "extracted.json").read_bytes())},
    })


class PageMetadata(unittest.TestCase):
    def test_failed_visit_keeps_redacted_url_and_stable_identity(self):
        with staging(Path(tempfile.gettempdir())) as root:
            ad = {"text": "Opisana reklama", "image_origin": "a" * 64}
            first = root / "capture1"
            second = root / "capture2"
            for folder in (first, second):
                write_capture(folder, ad, "page1")
                actual, page = capture_metadata(folder)
                self.assertEqual(actual, ad)
                self.assertEqual(page["capture_id"], "page1")
                self.assertEqual(page["url"], "https://shop.example/offer")
                self.assertEqual((page["status"], page["http_status"]), ("failed", 502))
                self.assertEqual(page["package_path"], f"captures/{folder.name}/landing")
            (first / "landing/metadata.json").write_text("{}", encoding="utf8")
            self.assertEqual(capture_metadata(first), (ad, None))


@unittest.skipUnless(URL, "brak TEST_DATABASE_URL")
class DatabaseMirror(base.LiveScheduler):
    maxDiff = 2000
    def setUp(self):
        super().setUp()
        reset()
        env = patch.dict(os.environ, {"DATABASE_URL": URL})
        env.start()
        self.addCleanup(env.stop)

    def sql(self, query, *args):
        with db.connect() as conn:
            return conn.execute(query, args).fetchall()

    def publish_three(self):
        opts = self.cfg["sources"]["meta"]
        body = "Czerwone jabłka z sadu w koszyku dostępne przez cały listopad"
        texts = {"81": body, "82": body, "85": "Szkolenie komputerowe dla początkujących pracowników biurowych"}
        self.source.write_text("".join(
            f"<article><div>Library ID: {ref}</div><p>{text}</p></article>" for ref, text in texts.items()
        ), encoding="utf8")
        cids = {}
        with patch.object(landing_visit, "visit", side_effect=AssertionError("unexpected network")):
            for card in meta.fetch({"mode": "import", "imports": {"test": str(self.source)}}, self.query):
                card.source_kind = "library"
                card.card["text"] = texts[card.ad_ref]
                cid = publish("meta", {**opts, "query_phrase": "test", "query_country": "PL"}, card)
                with connection(self.engine.db_path, write=True) as conn:
                    store_card(conn, self.run, "meta", self.engine.sources["meta"], self.query, card, cid)
                cids[card.ad_ref] = cid
        return cids

    def test_feed_and_run_match_files(self):
        cids = self.publish_three()
        feed = export_graph(self.state)
        lines = [json.loads(line) for line in feed.read_text(encoding="utf8").splitlines()]
        update_campaigns(feed)
        report = read_json(feed.with_suffix(".campaigns.json"))

        with db.connect() as conn:
            cards = db.load_cards(conn, "live")
            run = db.latest_run(conn, "live")
        self.assertEqual(cards, lines)  # ta sama treść i kolejność co JSONL
        sys.path.insert(0, str(ROOT / "graph"))
        from ftf_graph.card import parse_card
        self.assertEqual([parse_card(c).id for c in cards], [r["ad_id"] for r in lines])

        self.assertEqual(run["cards_sha256"], report["feed_sha256"])
        self.assertEqual(run["card_count"], 3)
        self.assertEqual(run["config"], {"min_cluster": 3, "min_samples": 2, "min_edge": 0.25})
        self.assertEqual(run["code_version"], report["code_version"])
        self.assertEqual(run["results"]["edge"], report["edges"])
        # Opis po poprawce TEXT_METHOD, ten sam co w pliku.
        self.assertEqual([r["method"] for r in run["results"]["edge"][0]["reasons"]], [lines[0]["text"]["method"]])
        self.assertEqual(sorted(m["ad_id"] for m in run["results"]["member"]), [r["ad_id"] for r in lines])
        ads = self.sql("SELECT ad_id, provider, ad_ref, source_kind, text, unavailable FROM ad ORDER BY ad_id")
        self.assertEqual([a[0] for a in ads], [r["ad_id"] for r in lines])
        self.assertEqual({a[3] for a in ads}, {"library"})  # źródło w trybie live
        self.assertTrue(all(a[4] and a[5] is None for a in ads))
        self.assertFalse(list((self.state / "graph").glob("*.db-error")))

        # Powtórka bez zmian: brak duplikatów i drugiego przebiegu, także gdy zmieniła się wersja repo.
        stored = self.sql("SELECT stored_at FROM feed_export")
        with patch.object(db, "code_version", return_value="inny-commit"):
            update_campaigns(export_graph(self.state))
        self.assertEqual(self.sql("SELECT stored_at FROM feed_export"), stored)
        self.assertEqual(self.sql("SELECT count(*) FROM raw_record")[0][0], 3)
        self.assertEqual(self.sql("SELECT count(*) FROM card")[0][0], 3)
        self.assertEqual(self.sql("SELECT count(*) FROM engine_run")[0][0], 1)

        # Uszkodzony pakiet: reklama znika z card_current, a przebieg ma wiersz 'unavailable'.
        manifest = self.state / "captures" / cids["85"] / "manifest.json"
        saved = manifest.with_suffix(".saved")
        manifest.rename(saved)
        update_campaigns(export_graph(self.state))
        with db.connect() as conn:
            self.assertEqual([c["ad_id"] for c in db.load_cards(conn, "live")],
                             ["meta-ad-library/81", "meta-ad-library/82"])
            run = db.latest_run(conn, "live")
        self.assertEqual([u["ad_id"] for u in run["results"]["unavailable"]], ["meta-ad-library/85"])
        self.assertEqual(run["card_count"], 2)
        self.assertEqual(self.sql("SELECT unavailable FROM ad WHERE ad_id='meta-ad-library/85'")[0][0],
                         "Brakuje plików pakietu")
        saved.rename(manifest)
        update_campaigns(export_graph(self.state))
        with db.connect() as conn:
            self.assertEqual(len(db.load_cards(conn, "live")), 3)
        self.assertEqual(self.sql("SELECT count(*) FROM engine_run")[0][0], 3)

    def test_database_enabled_after_files_exist(self):
        """Raport policzony bez bazy trafia do niej przy następnym przebiegu zegara."""
        source = ROOT / "graph/data/sample_cards.jsonl"
        feed = self.root / "replay.jsonl"
        feed.write_bytes(source.read_bytes())
        with patch.dict(os.environ, {"DATABASE_URL": ""}):
            update_campaigns(feed)
        import psycopg
        with psycopg.connect(URL) as conn:
            self.assertIsNone(conn.execute("SELECT to_regclass('engine_run')").fetchone()[0])
        before = feed.with_suffix(".campaigns.json").read_bytes()
        update_campaigns(feed)
        self.assertEqual(before, feed.with_suffix(".campaigns.json").read_bytes())
        report = read_json(feed.with_suffix(".campaigns.json"))
        with db.connect() as conn:
            run = db.latest_run(conn, "replay")
        self.assertEqual(len(run["results"]["campaign"]), len(report["campaigns"]))
        self.assertEqual(len(run["results"]["edge"]), len(report["edges"]))

    def test_existing_export_backfills_ad_and_page_metadata(self):
        cids = self.publish_three()
        ad = {"text": "Przykładowa reklama", "image_origin": "a" * 64, "audio_origin": "b" * 64,
              "landing_url": "https://shop.example/offer", "url_origin": "c" * 64}
        write_capture(self.state / "captures" / cids["81"], ad, "page1")
        feed = export_graph(self.state)
        before = feed.read_bytes()
        with db.connect() as conn:
            # Naśladuj zawartość sprzed wdrożenia metadanych przy tej samej dacie eksportu.
            conn.execute("UPDATE ad SET image_sha256=NULL, audio_sha256=NULL, landing_url=NULL")
            conn.execute("DELETE FROM page_capture")
            conn.execute("DELETE FROM raw_record WHERE kind='page'")
            conn.execute("UPDATE feed_export SET revision=%s", ("0" * 64,))
        export_graph(self.state)
        export_graph(self.state)
        self.assertEqual(feed.read_bytes(), before)
        self.assertEqual(self.sql("SELECT url, status, http_status FROM page_capture"),
                         [("https://shop.example/offer", "failed", 502)])
        self.assertEqual(self.sql("SELECT image_sha256, audio_sha256, landing_url FROM ad WHERE ad_ref='81'"),
                         [("a" * 64, "b" * 64, "https://shop.example/offer")])
        self.assertEqual(self.sql("SELECT kind, count(*) FROM raw_record GROUP BY kind ORDER BY kind"),
                         [("ad", 3), ("page", 1)])
        self.assertEqual(self.sql("SELECT count(*) FROM card"), [(3,)])

    def test_silent_database_does_not_hang(self):
        """Serwer przyjmuje TCP i milczy: limit połączenia kończy zapis, pliki powstają."""
        self.publish_three()
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen()
        held = []
        stop = threading.Event()

        def accept():
            server.settimeout(0.2)
            while not stop.is_set():
                try:
                    held.append(server.accept()[0])
                except OSError:
                    pass
        thread = threading.Thread(target=accept, daemon=True)
        thread.start()
        self.addCleanup(lambda: (stop.set(), thread.join(), [c.close() for c in held], server.close()))
        port = server.getsockname()[1]
        start = time.monotonic()
        with patch.dict(os.environ, {"DATABASE_URL": f"postgresql://nobody@127.0.0.1:{port}/none"}):
            feed = export_graph(self.state)
            update_campaigns(feed)
        self.assertLess(time.monotonic() - start, 60)
        self.assertTrue(feed.with_suffix(".campaigns.json").is_file())
        self.assertIn("Traceback", (self.state / "graph" / "live.feed.db-error").read_text(encoding="utf8"))
        self.assertTrue((self.state / "graph" / "live.run.db-error").is_file())

    def test_adapter_version_matches_feed(self):
        source = (ROOT / "scamgraph/discovery/graph_feed.py").read_text(encoding="utf8")
        self.assertIn(f'json.dumps(["{db.ADAPTER_VERSION}"', source)

    def test_older_report_does_not_replace_newer(self):
        report = {"feed_sha256": "a" * 64, "computed_at": "2026-11-21T10:00:00.000+00:00", "edges": [],
                  "campaigns": [], "unassigned": ["x/1"], "unavailable": [], "code_version": "v1"}
        newer = {**report, "feed_sha256": "b" * 64, "computed_at": "2026-11-21T11:00:00.000+00:00"}
        with db.connect() as conn:
            first = db.store_run(conn, "live", newer, {})
            self.assertIsNone(db.store_run(conn, "live", report, {}))
            self.assertEqual(db.latest_run(conn, "live")["run_id"], first)
            self.assertEqual(db.store_run(conn, "live", newer, {}), first)

    def test_database_down_keeps_files(self):
        self.publish_three()
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://nobody@127.0.0.1:1/none?connect_timeout=2"}):
            feed = export_graph(self.state)
            update_campaigns(feed)
        self.assertTrue(feed.with_suffix(".campaigns.json").is_file())
        self.assertEqual(sorted(p.name for p in (self.state / "graph").glob("*.db-error")),
                         ["live.feed.db-error", "live.run.db-error"])
        # Po powrocie bazy znaczniki znikają, a dane dochodzą.
        update_campaigns(export_graph(self.state))
        self.assertFalse(list((self.state / "graph").glob("*.db-error")))
        self.assertEqual(self.sql("SELECT count(*) FROM card")[0][0], 3)


# Testy klasy bazowej uruchamia tests.test_live_scheduler; tu nie powtarzamy ich.
for name in [n for n in vars(base.LiveScheduler) if n.startswith("test_")]:
    setattr(DatabaseMirror, name, None)

if __name__ == "__main__":
    unittest.main()
