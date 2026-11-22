import json
import os
from pathlib import Path
import tempfile
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch

from scamgraph.capture import read_json, staging, verified, write_json
from scamgraph.catalog import catalog, matches
from scamgraph.discovery import landing_visit, meta
from scamgraph.discovery.engine import connection, store_card
from scamgraph.discovery.graph_feed import export_graph, update_campaigns
from scamgraph.discovery.page_queue import confirm_target, drain, process_one, run_landing_totals
from scamgraph.discovery.service import engine_for, load_config, publish
from scamgraph.discovery.types import Query
from scamgraph.discovery.trusted_domains import canonical_domain, match_url
from scamgraph.discovery.landing_fetch import PageReads, TrustedDestination


class LiveScheduler(unittest.TestCase):
    def setUp(self):
        ctx = staging(Path(tempfile.gettempdir()))
        self.root = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        self.file = self.root / "options.json"
        self.state = self.root / "state"
        self.source = self.root / "cards.html"
        self.source.write_text('<article><div>Library ID: 401</div><a href="https://shop.example/offer">Kup teraz</a></article>', encoding="utf8")
        self.query = Query("test", "PL", 3)
        self.spec = {"state_dir": str(self.state), "sources": {"meta": {"provider": "meta-ad-library",
                     "country": "PL", "phrases": ["test"], "limit": 3, "mode": "live", "permission": "test"}}}
        write_json(self.file, self.spec)
        self.cfg = load_config(self.file)
        self.engine = engine_for(self.cfg)
        self.run = self.engine._claim({"meta"}, "cli", time.time())["meta"]

    def insert(self, auto_target=True):
        opts = self.engine.sources["meta"]
        finding, = meta.fetch({"mode": "import", "imports": {"test": str(self.source)}, "auto_target": auto_target},
                              self.query)
        finding.source_kind = "library"
        finding.card["comments"] = [{"text": "przykładowa opinia"}]
        finding.observed_at = "2026-01-01T00:00:00+00:00"
        cid = publish("meta", {**opts, "query_phrase": "test", "query_country": "PL"}, finding)
        with connection(self.engine.db_path, write=True) as db:
            store_card(db, self.run, "meta", opts, self.query, finding, cid)
        return cid

    def test_publish_during_visit_history_and_race(self):
        base = self.insert()
        entered, release = Event(), Event()

        def visit(*args):
            entered.set()
            if not release.wait(10):
                raise RuntimeError("synchronization timeout")
            return {"status": "partial", "reason": "Test częściowy"}

        with patch.object(landing_visit, "visit", side_effect=visit) as reader:
            worker = Thread(target=process_one, args=(self.cfg,))
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                row, = self.engine.snapshot()["candidates"]
                self.assertEqual((row["capture_id"], row["page_status"]), (base, "running"))
                self.assertFalse(process_one(self.cfg))
                self.assertEqual(read_json(export_graph(self.state))["provenance"]["capture_id"], base)
                self.insert()
            finally:
                release.set()
                worker.join(10)
            self.assertEqual(reader.call_count, 1)
        with connection(self.engine.db_path) as db:
            jobs = db.execute("SELECT * FROM page_jobs ORDER BY seq").fetchall()
        self.assertEqual([j["status"] for j in jobs], ["partial", "queued"])
        result = jobs[0]["result_capture"]
        self.assertNotEqual(result, base)
        records = catalog(self.state / "captures")
        self.assertEqual(records[base][1]["observation_id"], records[result][1]["observation_id"])
        self.assertTrue(records[result][2]["opinions"])
        self.assertFalse(list(matches(records, result)))
        for cid in (base, result):
            verified(self.state / "captures" / cid, records[cid][1])
        self.assertEqual(self.engine.snapshot()["candidates"][0]["seq"], jobs[1]["seq"])
        self.assertEqual(self.engine.snapshot()["candidates"][0]["page_status"], "queued")
        self.assertEqual(export_graph(self.state, "replay").read_bytes(), b"")

    def test_analyst_confirms_one_candidate_and_binary_keeps_its_proof(self):
        self.source.write_text('<article><div>Library ID: 401</div><a href="https://shop.example/a">A</a>'
                               '<a href="https://shop.example/picture.png">B</a></article>', encoding="utf8")
        # Przy włączonym auto_target te same odnośniki dałyby cel „dominant_domain”; tu sprawdzamy ścieżkę analityka.
        base = self.insert(auto_target=False)
        row, = self.engine.snapshot()["candidates"]
        self.assertEqual(run_landing_totals(self.state, [self.run])[self.run]["content"], {"review": 1})
        card = read_json(self.state / "captures" / base / "ad/card.json")
        picked = card["landing_candidates"][1]
        with self.assertRaises(ValueError):
            confirm_target(self.state, row["seq"], {**picked, "element": 999})
        confirm_target(self.state, row["seq"], picked)
        with self.assertRaises(ValueError):
            confirm_target(self.state, row["seq"], picked)

        def visit(store, url, *_):
            import io
            from PIL import Image

            self.assertEqual(url, "https://shop.example/picture.png")
            data = io.BytesIO()
            Image.new("RGB", (1, 1)).save(data, "PNG")
            folder = store / "test-image"
            with patch("scamgraph.discovery.landing_fetch.read_public", return_value=(200, "image/png", data.getvalue(), None, {})):
                result = landing_visit.gather(folder, url)
            return {**result, "page_id": folder.name}

        with patch.object(landing_visit, "visit", side_effect=visit):
            self.assertTrue(process_one(self.cfg))
        latest, = self.engine.snapshot()["candidates"]
        folder = self.state / "captures" / latest["capture_id"]
        result = read_json(folder / "extracted.json")
        verified(folder, read_json(folder / "manifest.json"))
        self.assertEqual(result["ad_target_link"]["source_ref"]["element"], picked["element"])
        self.assertEqual(result["landing_visit"]["target_basis"], "analyst")
        self.assertEqual(result["ad_page_links"], [])
        self.assertEqual(read_json(export_graph(self.state))["infra"], {})
        self.assertEqual(run_landing_totals(self.state, [self.run])[self.run]["by_type"], {"image": {"usable": 1}})

    def test_restart_and_permission_revoked_between_jobs(self):
        self.insert()
        self.insert()
        with connection(self.engine.db_path, write=True) as db:
            db.execute("UPDATE page_jobs SET status='running',attempts=1 WHERE seq=(SELECT min(seq) FROM page_jobs)")
        def revoke(*_):
            self.spec["sources"]["meta"]["mode"] = "import"
            write_json(self.file, self.spec)
            return {"status": "failed", "reason": "Test odmowy"}
        with patch.object(landing_visit, "visit", side_effect=revoke) as visit:
            drain(load_config(self.file), [self.run])
        self.assertEqual(visit.call_count, 1)
        with connection(self.engine.db_path) as db:
            self.assertEqual([tuple(r) for r in db.execute("SELECT status,attempts FROM page_jobs ORDER BY seq")],
                             [("failed", 2), ("skipped", 0)])

    def test_trust_before_queue_and_before_resuming_existing_jobs(self):
        db_path = self.engine.db_path
        self.insert()
        with connection(db_path, write=True) as db:
            db.execute("INSERT INTO trusted_domains VALUES (?)", ("shop.example",))
        with patch.object(landing_visit, "visit", side_effect=AssertionError("unexpected visit")) as browser:
            base = self.insert()
            latest, = self.engine.snapshot()["candidates"]
            self.assertEqual(latest["page_status"], "trusted_domain")
            result = read_json(self.state / "captures" / base / "extracted.json")
            self.assertEqual(result["landing_visit"]["trusted_domain"], "shop.example")
            self.assertFalse(result["ad_page_links"])
            self.assertTrue(process_one(self.cfg))
            self.assertFalse(process_one(self.cfg))
            browser.assert_not_called()
        with connection(db_path, write=True) as db:
            self.assertEqual([tuple(r) for r in db.execute("SELECT status,attempts FROM page_jobs ORDER BY seq")],
                             [("trusted_domain", 1), ("trusted_domain", 0)])
            db.execute("DELETE FROM trusted_domains")
        self.insert()
        with patch.object(landing_visit, "visit", return_value={"status":"partial", "reason":"fixture"}) as browser:
            self.assertTrue(process_one(self.cfg))
            browser.assert_called_once()

    def test_exact_domain_and_redirect_without_contacting_target(self):
        db_path = self.engine.db_path
        with connection(db_path, write=True) as db:
            db.execute("INSERT INTO trusted_domains VALUES (?)", (canonical_domain("FAẞ.Example."),))
        expected = "xn--fa-hia.example"
        target = "https://" + expected + "/a"
        self.assertEqual(match_url(db_path, "https://faß.example./"), expected)
        for host in ("fass.example", "foo." + expected, expected + ".invalid", "unrelated.example"):
            self.assertIsNone(match_url(db_path, "https://" + host))
        for invalid in ("https://shop.example", "*.shop.example", "127.0.0.1", "localhost", "two..example"):
            with self.assertRaises(ValueError):
                canonical_domain(invalid)
        start = "https://outside.example/link"
        reads = PageReads(10, domain_db=db_path)
        with patch("scamgraph.discovery.landing_fetch.read_public", return_value=(302, "", b"", target, {})) as get:
            with self.assertRaises(TrustedDestination):
                reads.get(start, document=True)
            self.assertEqual([call.args[0] for call in get.call_args_list], [start])
            self.assertEqual([e["response"]["redirectURL"] for e in reads.entries], [target])
        with patch("scamgraph.discovery.landing_fetch.read_public", return_value=(200, "text/css", b"", None, {})):
            self.assertEqual(reads.get(target, resource=True)[0], target)

    @unittest.skipUnless(os.environ.get("SCAMGRAPH_TEST_CHROME"), "Lokalny test Chrome")
    def test_trusted_redirect_keeps_partial_archive(self):
        with connection(self.engine.db_path, write=True) as db:
            db.execute("INSERT INTO trusted_domains VALUES ('shop.example')")
        folder = self.root / "redirect"
        start, target = "https://outside.example/link", "https://shop.example/product"
        with patch("scamgraph.discovery.landing_fetch.read_public", return_value=(302, "", b"", target, {})) as get:
            report = landing_visit.gather(folder, start, domain_db=self.engine.db_path)
        self.assertEqual([call.args[0] for call in get.call_args_list], [start])
        self.assertEqual((report["status"], report["trusted_domain"]), ("trusted_domain", "shop.example"))
        self.assertNotIn("document_entry", report)
        self.assertEqual(read_json(folder / "metadata.json")["status"], "partial")
        log = read_json(folder / "network.har")["log"]["entries"]
        self.assertEqual([(e["request"]["url"], e["response"]["redirectURL"]) for e in log], [(start, target)])

    def test_cards_without_destination_reach_graph(self):
        opts = self.cfg["sources"]["meta"]
        body = "Czerwone jabłka z sadu w koszyku dostępne przez cały listopad"
        texts = {"81": body, "82": body, "85": "Szkolenie komputerowe dla początkujących pracowników biurowych"}
        self.source.write_text("".join(
            f"<article><div>Library ID: {ref}</div><p>{text}</p></article>" for ref, text in texts.items()
        ), encoding="utf8")
        findings = list(meta.fetch({"mode": "import", "imports": {"test": str(self.source)}}, self.query))
        self.assertEqual([card.ad_ref for card in findings], list(texts))
        for card in findings:
            card.source_kind = "library"
            card.card["text"] = texts[card.ad_ref]
        with patch.object(landing_visit, "visit", side_effect=AssertionError("unexpected network")):
            for finding in findings:
                cid = publish("meta", {**opts, "query_phrase": "test", "query_country": "PL"}, finding)
                with connection(self.engine.db_path, write=True) as db:
                    store_card(db, self.run, "meta", self.engine.sources["meta"], self.query, finding, cid)
        self.assertEqual(self.engine.snapshot()["page_jobs"], {})
        file = export_graph(self.state)
        exported = [json.loads(line) for line in file.read_text(encoding="utf8").splitlines()]
        self.assertEqual(exported[0]["text"]["ad_text"], body)
        self.assertTrue(exported[0]["text"]["origin_id"])
        self.assertFalse(exported[0]["infra"])
        update_campaigns(file)
        report = file.with_suffix(".campaigns.json")
        edge, = read_json(report)["edges"]
        self.assertEqual({edge["a"], edge["b"]}, {"meta-ad-library/81", "meta-ad-library/82"})
        self.assertEqual([r["method"] for r in edge["reasons"]], [exported[0]["text"]["method"]])
        manifest = self.state / "captures" / cid / "manifest.json"
        other = manifest.with_suffix(".saved")
        manifest.rename(other)
        update_campaigns(export_graph(self.state))
        self.assertEqual([r["ad_id"] for r in read_json(report)["unavailable"]], ["meta-ad-library/85"])
        self.assertEqual(len(read_json(report)["edges"]), 1)
        other.rename(manifest)
        update_campaigns(export_graph(self.state))
        self.assertEqual(read_json(report)["unavailable"], [])

    def test_existing_graph_engine_and_atomic_report(self):
        source = Path(__file__).resolve().parents[1] / "graph/data/sample_cards.jsonl"
        feed = self.root / "replay.jsonl"
        feed.write_bytes(source.read_bytes())
        update_campaigns(feed)
        report = feed.with_suffix(".campaigns.json")
        result = read_json(report)
        self.assertTrue(result["edges"])
        self.assertTrue(result["campaigns"])
        before = report.read_bytes()
        update_campaigns(feed)
        self.assertEqual(before, report.read_bytes())
