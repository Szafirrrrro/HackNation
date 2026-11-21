import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from testowanie_modeli.scripts.report import METRICS, summarize

# Test wejść nie odczytuje CPU ani RAM i działa bez pakietów z kontenera.
with patch.dict(sys.modules, {"psutil": Mock()}):
    from testowanie_modeli.common import bench


class HarnessTest(unittest.TestCase):
    def test_distinct_input_ids_and_corpus_layout(self):
        with TemporaryDirectory() as tmp, patch.object(bench, "DATA", Path(tmp)):
            root = Path(tmp)
            for group in ("cleaned", "gemini"):
                path = root / "ai_generated" / group / "sample.png"
                path.parent.mkdir(parents=True)
                path.touch()
            inputs = bench.files("ai_generated", bench.IMG_EXT)
            self.assertEqual([bench.short_label(path) for path in inputs], [
                "ai_generated/cleaned/sample.png", "ai_generated/gemini/sample.png"])
            (root / "media").mkdir()
            (root / "media" / "capture.png").touch()
            ads = [{"ad_id": ad_id, "text": "ten sam tekst"} for ad_id in ("a", "b")]
            (root / "ads.jsonl").write_text("\n".join(map(json.dumps, ads)), encoding="utf-8")
            self.assertEqual(bench.texts(), [("a", "ten sam tekst"), ("b", "ten sam tekst")])
            self.assertEqual(bench.files("images", bench.IMG_EXT), [str(root / "media" / "capture.png")])

    def test_complete_filtered_and_partial_results(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {"use_case": "ocr", "machine": "test", "cgroup_cpu_limit": 2, "cgroup_measurement": True}
            valid = {"model": "fast", "threads": 1, **dict.fromkeys(METRICS, 1)}
            def write_rows(rows):
                (root / "ocr.json").write_text(json.dumps({"env": env, "results": rows}), encoding="utf-8")
            write_rows([valid])
            filtered = {**env, "use_case": "text_topic", "model_filter": ["fast"]}
            (root / "text_topic.json").write_text(json.dumps({"env": filtered, "results": []}), encoding="utf-8")
            self.assertFalse(summarize(root)[1])
            write_rows([valid, {"model": "slow", "threads": 1, "skipped": "brak danych"}, {}])
            (root / "expected-suites.txt").write_text("ocr\nasr\n", encoding="utf-8")
            (root / "face.json").write_text("{", encoding="utf-8")
            (root / "failed-containers.txt").write_text("face\n", encoding="utf-8")
            report, failed = summarize(root)
            self.assertTrue(failed)
            for message in ("| fast |", "brak danych", "uszkodzony wynik", "asr — brak pliku",
                            "face.json — błąd odczytu", "face — błąd uruchomienia"):
                self.assertIn(message, report)

    def test_empty_results_marked_unsuccessful(self):
        with TemporaryDirectory() as tmp:
            report, failed = summarize(Path(tmp))
            self.assertTrue(failed)
            self.assertIn("Brak udanych pomiarów", report)

    def test_completed_configuration_survives_interrupted_suite(self):
        first = Mock()
        first.name = "first"
        second = Mock()
        second.name = "second"
        valid = {"model": "first", "threads": 1, **dict.fromkeys(METRICS, 1)}
        with TemporaryDirectory() as tmp, patch.object(bench, "RESULTS", Path(tmp)), \
                patch.object(bench, "thread_counts", return_value=[1]), \
                patch.dict(bench.os.environ, {"BENCH_MODELS": ""}), \
                patch.object(bench, "_bench_one", side_effect=[valid, SystemExit(9)]):
            with self.assertRaises(SystemExit):
                bench.run_suite("ocr", [first, second])
            report, failed = summarize(Path(tmp))
            self.assertTrue(failed)
            self.assertIn("| first |", report)
            self.assertIn("zestaw nieukończony", report)
