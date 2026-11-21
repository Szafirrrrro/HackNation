"""Operator entry points with team-owned input only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from scamgraph.capture import read_json, staging, verified, write_json
from scamgraph.catalog import preview
from scamgraph.discovery.service import DEFAULT_CONFIG, load_config, restore_config, save_import


class DiscoveryFlow(unittest.TestCase):
    def setUp(self):
        temp = staging(Path(tempfile.gettempdir()))
        self.root = temp.__enter__()
        self.addCleanup(temp.__exit__, None, None, None)
        self.config_file = self.root / "config.json"
        self.config = read_json(DEFAULT_CONFIG)
        self.config["state_dir"] = str(self.root / "state")
        meta = self.config["sources"]["meta"]
        phrase = meta["phrases"][0]
        meta["imports"][phrase] = str(DEFAULT_CONFIG.parent / meta["imports"][phrase])
        nask = self.config["sources"]["nask"]
        nask["path"] = str(self.root / "corpus")
        Path(nask["path"]).mkdir()
        (Path(nask["path"]) / "ads.jsonl").write_text(json.dumps({
            "ad_id": "810001", "text": phrase, "source": {"kind": "synthetic", "provider": "fixture"}
        }), encoding="utf-8")
        write_json(self.config_file, self.config)
        self.command = [sys.executable, "-m", "scamgraph.discovery", "--config", str(self.config_file)]
        self.env = {**os.environ, "PYTHONUTF8": "1"}

    def cli(self, *args, code=0):
        proc = subprocess.run(self.command + list(args), cwd=DEFAULT_CONFIG.parent, env=self.env,
                              timeout=25, capture_output=True, encoding="utf-8")
        self.assertEqual(proc.returncode, code, proc.stderr + proc.stdout)
        return json.loads(proc.stdout)

    def test_cli_import_failure_isolation_and_proof(self):
        self.cli("run")
        state = self.cli("status")
        self.assertEqual(len(state["candidates"]), 3)
        self.assertEqual({row["provider"] for row in state["candidates"] if row["ad_ref"] == "810001"},
                         {"nask-hacknation-2026", "meta-ad-library"})
        for row in state["candidates"]:
            folder = self.root / "state/captures" / row["capture_id"]
            manifest, evidence = read_json(folder / "manifest.json"), read_json(folder / "extracted.json")
            verified(folder, manifest)
            self.assertIn(row["ad_ref"], str(preview(folder, manifest, evidence["source_record"])[1]))
        self.config["sources"]["nask"]["path"] = "missing"
        write_json(self.config_file, self.config)
        self.cli("run", code=1)
        after = self.cli("status")
        self.assertEqual(len(after["candidates"]), 3)
        sources = {r["source_id"]: r for r in after["sources"]}
        self.assertEqual(sources["meta"]["known_count"], 2)
        self.assertIn("ads.jsonl", sources["nask"]["error"])
        cfg = load_config(self.config_file)
        save_import(cfg, "meta", "saved.html", b"<html><body>No results found.</body></html>", "manual", "PL")
        self.cli("run", "--source", "meta")
        meta = next(r for r in self.cli("status")["sources"] if r["source_id"] == "meta")
        self.assertEqual((meta["mode"], meta["phrase"], meta["status"], meta["read_count"]), ("import", "manual", "success", 0))

    def test_wall_clock_and_process_restart(self):
        self.config["interval_seconds"] = 2
        write_json(self.config_file, self.config)
        previous = None
        for attempt in range(2):
            clock = subprocess.Popen(self.command + ["timer"], cwd=DEFAULT_CONFIG.parent, env=self.env)
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    state = self.cli("status")
                    rows = state["sources"]
                    ids = {r["run_id"] for r in rows}
                    if (all(r["trigger"] == "timer" and r["status"] == "success" for r in rows)
                            and (not previous or ids.isdisjoint(previous))):
                        break
                    time.sleep(.15)
                else:
                    self.fail("Brak zakończonego przebiegu zegara po starcie procesu")
                self.assertEqual(len(state["candidates"]), 3)
                self.assertEqual(sum(row["new_count"] for row in rows), 0 if attempt else 3)
                previous = ids
            finally:
                clock.terminate()
                clock.wait(timeout=5)

    def test_imports_keep_each_phrase_and_country_until_restored(self):
        cfg = load_config(self.config_file)
        for phrase, country in (("Alpha", "PL"), ("Beta", "PL"), ("Beta", "DE"), ("Alpha", "PL")):
            save_import(cfg, "meta", "result.html", country.encode(), phrase, country)
        selected = load_config(self.config_file)["sources"]["meta"]
        self.assertEqual(set(selected["imports"]), {"Alpha", "Beta"})
        self.assertTrue(all(Path(p).read_bytes() == b"PL" for p in selected["imports"].values()))
        restore_config(cfg, "meta")
        self.assertEqual(load_config(self.config_file)["sources"]["meta"]["mode"], "replay")

    def test_broken_provider_module_does_not_prevent_another_source(self):
        (self.root / "broken_adapter.py").write_text("raise RuntimeError('syntetyczna awaria modułu')", encoding="utf8")
        self.env["PYTHONPATH"] = str(self.root)
        self.config["sources"]["meta"]["adapter"] = "broken_adapter:fetch"
        write_json(self.config_file, self.config)
        self.cli("run", code=1)
        states = {r["source_id"]:r for r in self.cli("status")["sources"]}
        self.assertIn("RuntimeError", states["meta"]["error"])
        self.assertEqual(states["nask"]["status"], "success")
