"""Discovery coordinator acceptance with local, synthetic adapters."""
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
import time
import unittest

from scamgraph.capture import read_json, staging
from scamgraph.discovery import nask
from scamgraph.discovery.engine import Engine, connection, store_card, work
from scamgraph.discovery.graph_feed import export_graph, update_campaigns
from scamgraph.discovery.service import publish
from scamgraph.discovery.types import Finding, SourceError
from scamgraph.sources import digest


def demo_fetch(options, query):
    if options.get("wait"):
        Path(options["started"]).touch()
        while not Path(options["release"]).exists():
            time.sleep(.02)
    if options.get("ad_error"):
        raise SourceError("Nie rozpoznano układu syntetycznej karty.")
    if options.get("hang"):
        time.sleep(120)
    if query.phrase == "pusta":
        return
    yield Finding("7", {"text": query.phrase}, "Trafienie w zapisie testowym.",
                  bool(options.get("missing")), Path(__file__), "row 1")


def demo_publish(source, options, finding):
    if options.get("record_budget"):
        Path(options["record_budget"]).write_text(str(options["landing_timeout"]))
    return f"{source}-{finding.ad_ref}-{options['query_phrase']}"


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.root = self.enterContext(staging(Path(tempfile.gettempdir())))
        source = {"provider": "library-a", "mode": "replay", "country": "PL", "limit": 2,
                  "phrases": ["pierwsza"], "timeout_seconds": 15}
        self.config = {"state_dir": str(self.root), "interval_seconds": 1800,
                       "sources": {"one": source, "two": {**source, "provider": "corpus-b", "mode": "import",
                                                          "country_filter": False}}}
        self.adapters = {s: demo_fetch for s in self.config["sources"]}
        self.engine = self.reopen()

    def reopen(self):
        return Engine(self.config, self.adapters, demo_publish)

    def state(self, source):
        return next(s for s in self.engine.snapshot()["sources"] if s["source_id"] == source)

    def test_dedup_reasons_versions_partial_and_restart(self):
        self.config["sources"]["one"].update(phrases=["pierwsza", "druga"], missing=True)
        self.assertEqual(set(self.engine.run()), {"one", "two"})
        snapshot = self.engine.snapshot()
        self.assertEqual(len(snapshot["candidates"]), 2)
        candidates = {c["provider"]: c for c in snapshot["candidates"]}
        self.assertEqual({c["ad_ref"] for c in candidates.values()}, {"7"})
        self.assertEqual(len(candidates["library-a"]["reasons"]), 2)
        self.assertTrue(all(s.split(" · ")[0] in {"pierwsza", "druga"} for s in candidates["library-a"]["reasons"]))
        self.assertIn("korpus bez filtra kraju", candidates["corpus-b"]["reasons"][0])
        self.assertIsNone(candidates["library-a"]["observed_at"])
        source = self.state("one")
        self.assertEqual((source["read_count"], source["new_count"], source["known_count"], source["missing_count"]),
                         (2, 1, 1, 2))
        self.engine = self.reopen()
        self.assertEqual(snapshot, self.engine.snapshot())
        self.engine.run(["one"])
        self.assertEqual((self.state("one")["new_count"], self.state("one")["known_count"]), (0, 2))
        with connection(self.engine.db_path, write=True) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM observations").fetchone()[0], 5)
            history = db.execute("""SELECT phrase, capture_id, card FROM observations
                                    WHERE provider='library-a' ORDER BY seq""").fetchall()
        self.assertEqual([(r[1], json.loads(r[2])["text"]) for r in history],
                         [("one-7-pierwsza", "pierwsza"), ("one-7-druga", "druga")] * 2)

    def test_source_failure_preserves_success_and_does_not_block_peer(self):
        self.engine.run("one")
        previous = self.state("one")["last_success"]
        self.config["sources"]["one"]["ad_error"] = True
        self.engine.run()
        failed = self.state("one")
        self.assertEqual((failed["status"], failed["last_success"]), ("error", previous))
        self.assertIn("układu", failed["error"])
        self.assertEqual(self.state("two")["status"], "success")
        self.config["sources"]["one"].update(ad_error=False, phrases=["pusta"])
        self.engine.run("one")
        self.assertEqual((self.state("one")["status"], self.state("one")["read_count"]), ("success", 0))

    def test_high_result_limit_allows_visiting_the_first_actual_card(self):
        budget = self.root / "budget"
        self.config["sources"]["one"].update(limit=100, timeout_seconds=180, record_budget=str(budget))
        self.engine.run("one")
        self.assertEqual(float(budget.read_text()), 22)

    def test_nask_resolves_aliases_and_conflicts_before_phrase_filter(self):
        from scamgraph.discovery.types import Query

        corpus = self.root / "organizer"
        corpus.mkdir()
        ads = corpus / "ads.jsonl"
        rows = [("z-first", "7", "pierwsza fraza w oryginalnej emisji"),
                ("a-alias", "7", "inna fraza w aliasie tej samej emisji"),
                ("z-first", "8", "inna fraza w konflikcie tego samego lokalnego ID"),
                ("healthy", "9", "inna fraza w innej poprawnej emisji")]
        ads.write_text("\n".join(json.dumps({"ad_id": ident, "text": text,
                         "source": {"provider": "provider-a", "ad_ref": ref}})
                                  for ident, ref, text in rows) + "\n", encoding="utf8")
        options = {"provider": "nask", "mode": "import", "path": str(corpus),
                   "state_dir": str(self.root), "phrases": ["pierwsza", "inna"], "country": "PL", "limit": 5}
        engine = Engine({**self.config, "sources": {"nask": options}}, {"nask": nask.fetch}, publish)
        run_id = engine._claim({"nask"}, "cli", time.time())["nask"]
        with self.assertLogs("scamgraph.discovery.nask", "WARNING") as messages:
            work(engine.db_path, run_id, "nask", options, nask.fetch, publish)
        self.assertTrue(all("wiersz 3" in msg and "pierwszy zapis w wierszu 1" in msg for msg in messages.output))
        imported = engine.snapshot()["candidates"]
        self.assertEqual({(row["provider"], row["ad_ref"]) for row in imported}, {("nask", "z-first"), ("nask", "healthy")})

        # A historical adapter could already have archived an alias. Preserve the observation and
        # recover its provider identity from the package to keep it from counting twice in analysis.
        run_id = engine._claim({"nask"}, "cli", time.time())["nask"]
        alias = Finding("a-alias", {"library_ref": "7", "text": rows[1][2]}, "Historyczna obserwacja", False,
                        ads, "line:2", source_kind="organizer", source_sha256=digest(ads))
        cid = publish("nask", {**options, "query_phrase": "inna", "query_country": "PL"}, alias)
        with connection(engine.db_path, write=True) as db:
            store_card(db, run_id, "nask", options, Query("inna", "PL", 5), alias, cid)
        feed = export_graph(self.root, "import")
        projected = [json.loads(line) for line in feed.read_text(encoding="utf8").splitlines()]
        self.assertEqual(len(projected), 3)
        identities = [p["provenance"]["original_ad_ref"] for p in projected]
        self.assertCountEqual(identities, ["7", "7", "9"])
        update_campaigns(feed)
        report = read_json(feed.with_suffix(".campaigns.json"))
        self.assertEqual(report["unassigned"], ["nask/a-alias", "nask/healthy"])

    def test_overdue_timer_races_click_and_reports_live_progress(self):
        options = self.config["sources"]["one"]
        options.update(wait=True, started=str(self.root / "started"), release=str(self.root / "release"))
        # Both sources become due before the timer and the GUI enter concurrently.
        with connection(self.engine.db_path, write=True) as db:
            db.execute("UPDATE schedules SET next_run=0")
        start = Barrier(2)
        def trigger(timer):
            start.wait(5)
            return self.reopen().tick() if timer else self.engine.run(["one"], trigger="gui")
        with ThreadPoolExecutor(max_workers=2) as executor:
            calls = [executor.submit(trigger, flag) for flag in (False, True)]
            try:
                deadline = time.monotonic() + 8
                while not Path(options["started"]).exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(Path(options["started"]).exists())
                row = self.state("one")
                self.assertEqual((row["status"], row["phrase"]), ("running", "pierwsza"))
                # A refreshed reader and another manual request both see the active job.
                self.assertEqual(self.reopen().run("one", trigger="gui"), {})
            finally:
                Path(options["release"]).touch()
            claims = [future.result(timeout=10) for future in calls]
        self.assertEqual(sum("one" in claim for claim in claims), 1)
        self.assertEqual(sum("two" in claim for claim in claims), 1)
        self.assertEqual(len(self.engine.snapshot()["candidates"]), 2)

    def test_timer_and_abandoned_lease_recovery(self):
        self.config["sources"]["one"]["interval_seconds"] = 180
        self.engine = self.reopen()
        self.assertEqual(self.engine.tick(), {})
        with connection(self.engine.db_path, write=True) as db:
            db.execute("UPDATE schedules SET next_run=? WHERE source_id='one'", (time.time() - 1,))
        self.assertEqual(set(self.engine.tick()), {"one"})
        self.assertEqual(self.state("one")["trigger"], "timer")
        self.assertEqual(self.reopen().tick(), {})
        # Simulate a supervisor crash after claiming a different source. A new
        # supervisor keeps a valid lease, then reclaims once its deadline passes.
        old = self.engine._claim({"two"}, "cli", time.time())["two"]
        self.assertEqual(self.reopen().run("two"), {})
        with connection(self.engine.db_path, write=True) as db:
            db.execute("UPDATE runs SET deadline=0 WHERE run_id=?", (old,))
        restarted = self.reopen()
        self.assertIn("two", restarted.tick())
        with connection(self.engine.db_path, write=True) as db:
            self.assertEqual(db.execute("SELECT status FROM runs WHERE run_id=?", (old,)).fetchone()[0], "error")

    def test_hung_source_is_terminated_and_sibling_finishes(self):
        self.config["sources"]["one"].update(hang=True, timeout_seconds=1.5)
        began = time.monotonic()
        self.engine.run()
        self.assertLess(time.monotonic() - began, 10)
        self.assertEqual(self.state("one")["status"], "error")
        self.assertIn("czas", self.state("one")["error"])
        self.assertEqual(self.state("two")["status"], "success")
        self.assertEqual(len(self.engine.snapshot()["candidates"]), 1)


if __name__ == "__main__":
    unittest.main()
