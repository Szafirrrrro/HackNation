"""Kontrakt wyjścia ekstrakcji (wymaga numpy: uruchamiaj w tm-base albo w środowisku z numpy)."""
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

try:
    import numpy as np
except ImportError:  # host bez numpy
    np = None

COMMON = Path(__file__).resolve().parent.parent / "common"


@unittest.skipIf(np is None, "brak numpy - uruchom w kontenerze tm-base")
class FeatureContractTest(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(COMMON))
        self.psutil = patch.dict(sys.modules, {"psutil": Mock()})
        self.psutil.start()
        import extractor
        import main
        from features_lib import FeatureStore
        self.extractor, self.main, self.FeatureStore = extractor, main, FeatureStore

    def tearDown(self):
        self.psutil.stop()
        sys.path.remove(str(COMMON))

    def _fake_exts(self):
        ex = self.extractor

        class FakeOCR(ex.Extractor):
            name, use_case, family, modality = "fake-ocr", "ocr", "text", "image"
            primary_field, version = "ocr.text", "1"

            def load(self, threads):
                pass

            def extract(self, item):
                if Path(item.path).read_bytes() == b"zepsuty":
                    raise ex.Unavailable("unreadable_image: test")
                return [ex.Out("ocr.text", "Wejdź na promocja-pl.online"),
                        ex.Out("ocr.urls", ex.find_urls("promocja-pl.online"), family="infrastructure")]

        class FakeEmbed(ex.Extractor):
            name, use_case, family, modality = "fake-embed", "text_embedding", "text", "text"
            primary_field, version, consumes_derived_text = "text.embedding", "1", True

            def load(self, threads):
                pass

            def extract(self, item):
                v = np.array([1.0, 0.0]) if "promocja" in item.text.lower() else np.array([0.0, 1.0])
                return [ex.Out("text.embedding", ex.l2(v))]

        return FakeOCR(), FakeEmbed()

    def test_extract_writes_contract_rows_vectors_and_inherited_origin(self):
        ocr, emb = self._fake_exts()
        with TemporaryDirectory() as tmp:
            data, out = Path(tmp) / "data", Path(tmp) / "out"
            data.mkdir()
            (data / "a.png").write_bytes(b"png-a")
            (data / "b.png").write_bytes(b"zepsuty")
            (data / "c.txt").write_text("PROMOCJA tylko dziś", encoding="utf-8")
            args = SimpleNamespace(data=str(data), out=str(out), threads=1)
            with patch("bench.set_threads"), patch("bench.cpu_seconds", return_value=0.0):
                self.main.cmd_extract(args, [ocr])
                self.main.cmd_extract(args, [emb])  # drugi kontener czyta ocr.text z pierwszego
            ds = out / "data"
            fs = self.FeatureStore(ds)
            rows = fs.rows(status=None)
            keys = {"ad_id", "family", "field", "value", "origin_id", "method_version", "status", "reason"}
            self.assertTrue(all(keys <= set(r) for r in rows))
            reasons = {(r["use_case"], r["reason"]) for r in rows if r["status"] == "unavailable"}
            self.assertIn(("ocr", "unreadable_image: test"), reasons)
            self.assertIn(("ocr", "no_image_input"), reasons)      # reklama tekstowa c.txt
            self.assertIn(("text_embedding", "no_text_input"), reasons)  # zepsuty obraz b.png
            urls = fs.rows(field="ocr.urls")
            self.assertEqual((urls[0]["value"], urls[0]["family"]), (["promocja-pl.online"], "infrastructure"))
            emb_rows = fs.rows(field="text.embedding")
            ocr_row = next(r for r in emb_rows if r["source_field"].startswith("ocr.text@"))
            img_ad = fs.rows(field="ocr.text")[0]
            self.assertEqual((ocr_row["ad_id"], ocr_row["origin_id"]), (img_ad["ad_id"], img_ad["origin_id"]))
            X, meta = fs.vectors(emb.method_version, "text.embedding")
            self.assertEqual(X.shape, (2, 2))
            ids, S, best = fs.ad_similarity(emb.method_version, "text.embedding")
            self.assertEqual(len(ids), 2)
            self.assertAlmostEqual(float(S[0, 1]), 1.0, places=5)  # OCR obrazu a ~ tekst c
            run = json.loads((ds / "runs" / f"{emb.slug}.json").read_text(encoding="utf-8"))
            self.assertEqual(run["vector_fields"], {"text.embedding": [2, 2]})

    def test_load_failure_is_recorded_and_next_model_runs(self):
        # M1: model, który się nie ładuje, nie zatrzymuje kolejnych i daje niezerowy kod wyjścia
        ex = self.extractor
        ocr, _ = self._fake_exts()

        class Broken(ex.Extractor):
            name, use_case, family, modality = "broken", "ocr", "text", "image"
            primary_field, version = "ocr.text", "1"

            def load(self, threads):
                raise ImportError("brak scipy")

        with TemporaryDirectory() as tmp:
            data, out = Path(tmp) / "data", Path(tmp) / "out"
            data.mkdir()
            (data / "a.png").write_bytes(b"png-a")
            args = SimpleNamespace(data=str(data), out=str(out), threads=1)
            with patch("bench.set_threads"), patch("bench.cpu_seconds", return_value=0.0):
                code = self.main.cmd_extract(args, [Broken(), ocr])
            self.assertEqual(code, 1)
            ds = out / "data"
            run = json.loads((ds / "runs" / "ocr_broken.json").read_text(encoding="utf-8"))
            self.assertEqual(run["status"], "failed")
            rows = [json.loads(l) for l in (ds / "features" / "ocr_broken.jsonl").read_text().splitlines()]
            self.assertTrue(rows and all(r["reason"].startswith("model_load_error: ImportError") for r in rows))
            self.assertTrue((ds / "features" / f"{ocr.slug}.jsonl").exists())

    def test_field_level_unavailable_numpy_scalars_and_source_ref(self):
        ex = self.extractor

        class Partial(ex.Extractor):
            name, use_case, family, modality = "partial", "image_embedding", "visual", "image"
            primary_field, version = "image.sha256", "1"
            params = {"tags": ["a"]}

            def load(self, threads):
                pass

            def extract(self, item):
                return [ex.Out("image.sha256", "ab"), ex.Out("image.score", np.float32(0.5)),
                        ex.Out("image.phash", reason="unreadable_image: test")]

        with TemporaryDirectory() as tmp:
            data, out = Path(tmp) / "data", Path(tmp) / "out"
            (data / "media").mkdir(parents=True)
            (data / "media" / "a.png").write_bytes(b"png")
            (data / "ads.jsonl").write_text(json.dumps({"ad_id": "a", "image_path": "media/a.png"}))
            args = SimpleNamespace(data=str(data), out=str(out), threads=1)
            with patch("bench.set_threads"), patch("bench.cpu_seconds", return_value=0.0):
                self.main.cmd_extract(args, [Partial()])
            rows = {r["field"]: r for r in self.FeatureStore(out / "data").rows(status=None)}
            self.assertEqual(rows["image.score"]["value"], 0.5)
            self.assertEqual((rows["image.phash"]["status"], rows["image.phash"]["reason"]),
                             ("unavailable", "unreadable_image: test"))
            self.assertEqual(rows["image.sha256"]["source_ref"], {"field": "image_path", "value": "media/a.png"})
            self.assertEqual(rows["image.sha256"]["object_type"], "ad")
            self.assertRegex(rows["image.sha256"]["method_version"], r"^image_embedding/partial@1#p[0-9a-f]{8}$")

    def test_profiles_select_by_stage_and_models_override(self):
        ex = self.extractor
        exts = []
        for stage in ("default", "candidate", "deferred", "excluded"):
            e = ex.Extractor()
            e.name, e.stage = f"m-{stage}", stage
            exts.append(e)
        names = lambda xs: [e.name for e in xs]
        self.assertEqual(names(self.main._select(exts, "", "default")), ["m-default"])
        self.assertEqual(names(self.main._select(exts, "", "eval")), ["m-default", "m-candidate"])
        self.assertEqual(len(self.main._select(exts, "", "all")), 4)
        self.assertEqual(names(self.main._select(exts, "m-deferred", "default")), ["m-deferred"])
        self.assertFalse(exts[3].grouping)
        self.assertTrue(exts[0].grouping)

    def test_array_values_are_stored_and_loadable(self):
        ex = self.extractor

        class Arr(ex.Extractor):
            name, use_case, family, modality = "arr", "image_embedding", "visual", "image"
            primary_field, version = "image.orb", "1"

            def load(self, threads):
                pass

            def extract(self, item):
                return [ex.Out("image.orb", {"array": np.arange(64, dtype=np.uint8).reshape(2, 32),
                                             "n_keypoints": 2})]

        with TemporaryDirectory() as tmp:
            data, out = Path(tmp) / "data", Path(tmp) / "out"
            data.mkdir()
            (data / "a.png").write_bytes(b"png-a")
            args = SimpleNamespace(data=str(data), out=str(out), threads=1)
            with patch("bench.set_threads"), patch("bench.cpu_seconds", return_value=0.0):
                self.main.cmd_extract(args, [Arr()])
            row = self.FeatureStore(out / "data").rows(field="image.orb")[0]
            self.assertEqual((row["value"]["shape"], row["value"]["dtype"], row["value"]["n_keypoints"]),
                             ([2, 32], "uint8", 2))
            arr = np.load(out / "data" / row["value"]["array"])[row["value"]["key"]]
            self.assertEqual(int(arr[1, 31]), 63)

    def test_find_urls_requires_known_tld(self):
        urls = self.extractor.find_urls("Wejdź: Investpro-AI.online/rejestracja tutaj.Sprawdz dokument.pdf "
                                        "dr.house www.gov.pl quantum-ai.ai bit.ly/x1 kontakt@promo-pl.online")
        self.assertEqual(urls, ["bit.ly/x1", "gov.pl", "investpro-ai.online/rejestracja",
                                "promo-pl.online", "quantum-ai.ai"])
        # krótkie polskie słowa po zgubionej spacji to nie domeny; z www./ścieżką już tak
        self.assertEqual(self.extractor.find_urls(
            "Zarabiaj teraz.To proste teraz.co tutaj.my juz.in rejestracja.id www.oferta.co bit.to/abc"),
            ["bit.to/abc", "oferta.co"])

    def test_rerun_is_idempotent(self):
        ocr, _ = self._fake_exts()
        with TemporaryDirectory() as tmp:
            data, out = Path(tmp) / "data", Path(tmp) / "out"
            data.mkdir()
            (data / "a.png").write_bytes(b"png-a")
            args = SimpleNamespace(data=str(data), out=str(out), threads=1)
            with patch("bench.set_threads"), patch("bench.cpu_seconds", return_value=0.0):
                self.main.cmd_extract(args, [ocr])
                first = (out / "data" / "features" / f"{ocr.slug}.jsonl").read_text(encoding="utf-8")
                self.main.cmd_extract(args, [ocr])
            self.assertEqual(first, (out / "data" / "features" / f"{ocr.slug}.jsonl").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
