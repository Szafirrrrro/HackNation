import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from models.scripts.report import METRICS, summarize
from models.common.corpus import load_corpus
from models.common.errors import Unavailable

# Test wejść nie odczytuje CPU ani RAM i działa bez pakietów z kontenera.
with patch.dict(sys.modules, {"psutil": Mock()}):
    from models.common import bench


def _ext(name, use_case="ocr"):
    e = Mock()
    e.name, e.use_case = name, use_case
    return e


class HarnessTest(unittest.TestCase):
    def test_distinct_input_ids_and_corpus_layout(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i, group in enumerate(("cleaned", "gemini")):
                path = root / "ai_generated" / group / "sample.png"
                path.parent.mkdir(parents=True)
                path.write_bytes(b"obraz-%d" % i)
            (root / "copy.png").write_bytes(b"obraz-0")  # identyczna kopia = ta sama reklama
            corpus = load_corpus(root)
            self.assertEqual(corpus.mode, "files")
            refs = sorted(a.record["source"]["ad_ref"] for a in corpus.ads)
            self.assertEqual(refs, ["ai_generated/cleaned/sample.png", "ai_generated/gemini/sample.png"])
            self.assertEqual(len({a.ad_id for a in corpus.ads}), 2)
            self.assertEqual(corpus.report["duplicate_files"][0]["path"], "copy.png")
            self.assertEqual(len(corpus.items("image")), 2)

            v0 = root / "v0"
            (v0 / "media").mkdir(parents=True)
            (v0 / "media" / "capture.png").write_bytes(b"png")
            ads = [{"ad_id": "a", "text": "ten sam tekst", "image_path": "media/capture.png"},
                   {"ad_id": "b", "text": "ten sam tekst"}, {"ad_id": "a", "text": "ponowny import"}]
            (v0 / "ads.jsonl").write_text("\n".join(map(json.dumps, ads)) + "\n{zły", encoding="utf-8")
            (v0 / "observations").mkdir()
            shot = {"ad_id": "a", "observation_group": "a-shot", "text_source": "manual_excerpt_from_screenshot"}
            (v0 / "observations" / "screenshots.jsonl").write_text(json.dumps(shot), encoding="utf-8")
            corpus = load_corpus(v0)
            texts = [(i.ad_id, i.text, i.origin_id) for i in corpus.items("text")]
            self.assertEqual(texts, [("a", "ten sam tekst", "a-shot"), ("b", "ten sam tekst", "b#text")])
            self.assertEqual([(i.path, i.origin_id) for i in corpus.items("image")],
                             [(str(v0 / "media" / "capture.png"), "a-shot")])
            self.assertEqual({a.ad_id for a in corpus.ads} - {i.ad_id for i in corpus.items("image")}, {"b"})
            self.assertEqual(corpus.report["duplicate_ad_ids"], ["a"])
            self.assertEqual(len(corpus.report["errors"]), 1)

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
        corpus = SimpleNamespace(dataset_id="t", mode="files", ads=[])
        valid = {"model": "first", "threads": 1, **dict.fromkeys(METRICS, 1)}
        with TemporaryDirectory() as tmp, \
                patch.object(bench, "thread_counts", return_value=[1]), \
                patch.dict(bench.os.environ, {}, clear=False), \
                patch.object(bench, "_run_child", side_effect=[valid, SystemExit(9)]):
            bench.os.environ.pop("BENCH_CHILD_MODEL", None)
            with self.assertRaises(SystemExit):
                bench.run_benchmark([_ext("first"), _ext("second")], corpus, Path(tmp))
            report, failed = summarize(Path(tmp))
            self.assertTrue(failed)
            self.assertIn("| first |", report)
            self.assertIn("zestaw nieukończony", report)

    def test_filtered_out_use_case_is_complete_and_empty(self):
        corpus = SimpleNamespace(dataset_id="t", mode="files", ads=[])
        valid = {"model": "e5", "threads": 1, **dict.fromkeys(METRICS, 1)}
        selected, other = _ext("e5", "text_embedding"), _ext("mdeberta", "text_topic")
        with TemporaryDirectory() as tmp, \
                patch.object(bench, "thread_counts", return_value=[1]), \
                patch.object(bench, "_run_child", return_value=valid):
            bench.os.environ.pop("BENCH_CHILD_MODEL", None)
            bench.run_benchmark([selected], corpus, Path(tmp), all_exts=[selected, other],
                                model_filter="e5")
            topic = json.loads((Path(tmp) / "text_topic.json").read_text(encoding="utf-8"))
            self.assertEqual((topic["state"], topic["results"], topic["env"]["model_filter"]),
                             ("complete", [], ["e5"]))
            report, failed = summarize(Path(tmp))
            self.assertFalse(failed)
            self.assertIn("Żaden model w tym zestawie nie odpowiada filtrowi.", report)


class CorpusContractTest(unittest.TestCase):
    def test_loose_dataset_id_comes_from_host_path(self):
        # B1: w kontenerze korpus jest zawsze /data - nazwa zbioru musi pochodzić z hosta
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "data"
            root.mkdir()
            (root / "a.txt").write_text("tekst", encoding="utf-8")
            with patch.dict(bench.os.environ, {"CORPUS_HOST_PATH": "/home/x/zbior-user"}):
                corpus = load_corpus(root)
            self.assertEqual(corpus.dataset_id, "zbior-user")
            self.assertEqual(len(corpus.fingerprint), 16)
            (root / "b.txt").write_text("inny", encoding="utf-8")
            self.assertNotEqual(load_corpus(root).fingerprint, corpus.fingerprint)

    def test_origin_rules_and_media_confinement(self):
        # M3 + kontrakt „Pochodzenie” i „Błędy i czas”
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "media").mkdir()
            (root / "media" / "x.png").write_bytes(b"png")
            ads = [
                {"ad_id": "explicit", "image_path": "media/x.png", "text": "t",
                 "image_origin": "export-7", "text_origin": "export-7"},
                {"ad_id": "inherit", "image_path": "media/x.png", "text": "t"},
                {"ad_id": "text-only", "text": "t"},
                {"ad_id": "escape", "image_path": "../poza.png", "text": "t"},
                {"ad_id": "absent", "image_path": "media/brak.png"},
                {"ad_id": "empty"},
            ]
            (root / "ads.jsonl").write_text("\n".join(map(json.dumps, ads)), encoding="utf-8")
            c = load_corpus(root)
            img = {i.ad_id: i.origin_id for i in c.items("image")}
            txt = {i.ad_id: i.origin_id for i in c.items("text")}
            self.assertEqual((img["explicit"], txt["explicit"]), ("export-7", "export-7"))
            self.assertEqual(txt["inherit"], img["inherit"])          # tekst dziedziczy po obrazie
            self.assertEqual(txt["text-only"], "text-only#text")
            self.assertNotIn("escape", img)                           # ścieżka poza korpusem
            self.assertIn("escape", txt)                              # ...ale tekst dalej analizowany
            ads_by_id = {a.ad_id: a for a in c.ads}
            self.assertTrue(c.missing_reason(ads_by_id["escape"], "image").startswith("path_outside_corpus"))
            self.assertTrue(c.missing_reason(ads_by_id["absent"], "image").startswith("file_not_found"))
            self.assertEqual(c.missing_reason(ads_by_id["text-only"], "image"), "no_image_input")
            errs = {(e.get("ad_id"), e["error"].split(":")[0], e["line"]) for e in c.report["errors"]}
            self.assertIn(("escape", "path_outside_corpus", 4), errs)
            self.assertIn(("absent", "file_not_found", 5), errs)
            self.assertIn(("empty", "no_usable_field", 6), errs)


class BenchOneTest(unittest.TestCase):
    # B2: model, który nie przetworzył żadnego wejścia, nie może wyglądać na tani i udany
    def _run(self, extract):
        ext = Mock()
        ext.name, ext.use_case, ext.modality = "m", "ocr", "image"
        ext.extract.side_effect = extract
        ext.summarize.side_effect = lambda outs: outs
        items = [SimpleNamespace(label=f"i{k}", ad_id=f"a{k}") for k in range(3)]
        with patch.object(bench, "set_threads"), patch.object(bench, "rss_bytes", return_value=0), \
                patch.object(bench, "cpu_seconds", return_value=0.0), \
                patch.object(bench, "Sampler") as smp:
            smp.return_value.__enter__.return_value = SimpleNamespace(samples_cores=[], peak_rss=0)
            return bench._bench_one(ext, items, 1, 0, 1)

    def test_exception_marks_configuration_as_error(self):
        r = self._run(RuntimeError("brak scipy"))
        self.assertIn("brak scipy", r["error"])
        self.assertEqual(r["n_errors"], 3)

    def test_all_unavailable_is_error_and_partial_is_counted(self):
        self.assertIn("żadne wejście", self._run(Unavailable("unreadable_image"))["error"])
        r = self._run([["ok"], Unavailable("x"), ["ok"]])
        self.assertNotIn("error", r)
        self.assertEqual((r["n_ok"], r["n_unavailable"], r["n_runs"]), (2, 1, 2))
        report_row = {k: r[k] for k in METRICS}
        self.assertTrue(all(v is not None for k, v in report_row.items() if k != "peak_cores_used"))


if __name__ == "__main__":
    unittest.main()
