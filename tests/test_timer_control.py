"""Operator control of the scheduler clock: pause, scrape interval and graph interval."""
import json
import tempfile
from pathlib import Path
import time
import unittest

SLEEP = time.sleep
from unittest import mock

from scamgraph.discovery import __main__ as cli
from scamgraph.discovery.control import read_control, status, update_control
from scamgraph.discovery.service import load_config


def write_config(root: Path, **extra) -> Path:
    config = {"state_dir": "state", "interval_seconds": 1800, **extra, "sources": {
        "demo": {"name": "Demo", "provider": "demo", "adapter": "x:y", "mode": "replay", "country": "PL",
                 "phrases": ["fraza"], "limit": 1, "interval_seconds": 900}}}
    path = root / "discovery.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


class FakeEngine:
    def __init__(self):
        self.runs = []

    def due(self):
        return ["demo"]

    def run(self, sources, trigger):
        self.runs.append((tuple(sources), trigger))
        return {}


def run_timer(file, loops, *, between=None):
    engine = FakeEngine()
    graph_calls, export_calls, page_calls, count = [], [], [], [0]

    def stop():
        count[0] += 1
        if between and count[0] in between:
            between[count[0]]()
        return count[0] > loops

    with mock.patch.object(cli, "engine_for", return_value=engine), \
            mock.patch.object(cli, "process_one", side_effect=lambda config: page_calls.append(1)), \
            mock.patch.object(cli, "refresh_graph", side_effect=lambda config, campaigns=True:
                              (graph_calls if campaigns else export_calls).append(time.time())), \
            mock.patch.object(cli.time, "sleep", lambda _: SLEEP(.01)):
        cli.timer(file, stop=stop)
    run_timer.exports = export_calls
    return engine, graph_calls, page_calls


class TimerControlTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.file = write_config(self.root)
        self.state = self.root / "state"

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_and_operator_override_of_scrape_interval(self):
        config = load_config(self.file)
        self.assertFalse(config["_control"]["paused"])
        self.assertEqual(config["sources"]["demo"]["interval_seconds"], 900)
        update_control(self.state, interval_seconds=300)
        config = load_config(self.file)
        self.assertEqual(config["interval_seconds"], 300)
        self.assertNotIn("interval_seconds", config["sources"]["demo"])  # override wins over per-source value
        update_control(self.state, interval_seconds=None)
        self.assertEqual(load_config(self.file)["sources"]["demo"]["interval_seconds"], 900)

    def test_invalid_values_are_rejected_and_broken_file_falls_back(self):
        with self.assertRaises(ValueError):
            update_control(self.state, graph_interval_seconds=0.5)
        with self.assertRaises(ValueError):
            update_control(self.state, interval_seconds=True)
        self.state.mkdir(exist_ok=True)
        (self.state / "timer-control.json").write_text("{broken", encoding="utf-8")
        self.assertFalse(read_control(self.state)["paused"])
        (self.state / "timer-control.json").write_text('{"paused": true, "graph_interval_seconds": -4}')
        control = read_control(self.state)
        self.assertTrue(control["paused"])
        self.assertIsNone(control["graph_interval_seconds"])

    def test_paused_clock_starts_no_runs_and_no_page_visits_but_still_publishes_graph(self):
        update_control(self.state, paused=True)
        engine, graph_calls, page_calls = run_timer(self.file, 15)
        self.assertEqual(engine.runs, [])
        self.assertEqual(page_calls, [])
        self.assertEqual(len(graph_calls), 1)
        clock = status(load_config(self.file))
        self.assertTrue(clock["alive"])
        self.assertTrue(clock["control"]["paused"])

    def test_resume_starts_due_sources(self):
        update_control(self.state, paused=True)
        engine, _, page_calls = run_timer(self.file, 15, between={5: lambda: update_control(self.state, paused=False)})
        self.assertIn((("demo",), "timer"), engine.runs)
        self.assertTrue(page_calls)

    def test_finished_source_run_exports_cards_before_the_next_graph_rebuild(self):
        update_control(self.state, graph_interval_seconds=3600)
        engine, graph_calls, _ = run_timer(self.file, 20)
        self.assertTrue(engine.runs)
        self.assertEqual(len(graph_calls), 1)
        self.assertTrue(run_timer.exports)  # cards reach the feed/PostgreSQL right after the scrape

    def test_graph_interval_and_immediate_request(self):
        update_control(self.state, graph_interval_seconds=3600)
        _, graph_calls, _ = run_timer(self.file, 20)
        self.assertEqual(len(graph_calls), 1)  # only the start-up rebuild
        _, graph_calls, _ = run_timer(self.file, 20, between={8: lambda: update_control(self.state, request_graph=True)})
        self.assertEqual(len(graph_calls), 2)
        write_config(self.root, graph_interval_seconds=1)  # configured value applies without an override
        update_control(self.state, graph_interval_seconds=None)
        _, graph_calls, _ = run_timer(self.file, 160)  # ~1.6 s of 10 ms ticks
        self.assertGreaterEqual(len(graph_calls), 2)

    def test_cli_control_updates_file_and_prints_status(self):
        with mock.patch("sys.argv", ["scamgraph", "--config", str(self.file), "control", "--pause",
                                     "--scrape-minutes", "5", "--graph-minutes", "6"]), \
                mock.patch("builtins.print") as printed:
            self.assertEqual(cli.main(), 0)
        out = json.loads(printed.call_args[0][0])
        self.assertTrue(out["control"]["paused"])
        self.assertEqual(out["scrape_interval"], 300)
        self.assertEqual(out["graph_interval"], 360)
        self.assertFalse(out["alive"])


if __name__ == "__main__":
    unittest.main()
