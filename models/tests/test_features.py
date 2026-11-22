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
        for stage in ("default", "on_demand"):
            e = ex.Extractor()
            e.name, e.stage = f"m-{stage}", stage
            exts.append(e)
        exts[1].grouping = False
        names = lambda xs: [e.name for e in xs]
        self.assertEqual(names(self.main._select(exts, "", "default")), ["m-default"])
        self.assertEqual(len(self.main._select(exts, "", "all")), 2)
        self.assertEqual(names(self.main._select(exts, "m-on_demand", "default")), ["m-on_demand"])
        with self.assertRaises(SystemExit):
            self.main._select(exts, "", "eval")
        self.assertFalse(exts[1].grouping)
        self.assertTrue(exts[0].grouping)

    def test_array_values_are_stored_and_loadable(self):
        ex = self.extractor

        class Arr(ex.Extractor):
            name, use_case, family, modality = "arr", "image_embedding", "visual", "image"
            primary_field, version = "image.keypoints", "1"

            def load(self, threads):
                pass

            def extract(self, item):
                return [ex.Out("image.keypoints", {"array": np.arange(64, dtype=np.uint8).reshape(2, 32),
                                             "n_keypoints": 2})]

        with TemporaryDirectory() as tmp:
            data, out = Path(tmp) / "data", Path(tmp) / "out"
            data.mkdir()
            (data / "a.png").write_bytes(b"png-a")
            args = SimpleNamespace(data=str(data), out=str(out), threads=1)
            with patch("bench.set_threads"), patch("bench.cpu_seconds", return_value=0.0):
                self.main.cmd_extract(args, [Arr()])
            row = self.FeatureStore(out / "data").rows(field="image.keypoints")[0]
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

    def test_audio_family_rows_share_recording_origin(self):
        ex = self.extractor
        fp = np.random.default_rng(0).integers(-2**31, 2**31, size=120, dtype=np.int64).astype(np.int32)

        class FakeAudio(ex.Extractor):
            name, use_case, family, modality = "fake-audio", "audio_fingerprint", "audio", "audio"
            primary_field, version = "audio.fingerprint", "1"

            def load(self, threads):
                pass

            def extract(self, item):
                if Path(item.path).read_bytes() == b"wideo-bez-dzwieku":
                    raise ex.Unavailable("no_audio_stream")
                return [ex.Out("audio.fingerprint", {"array": fp, "n_frames": fp.size}),
                        ex.Out("audio.speaker_embedding", ex.l2(np.array([3.0, 4.0]))),
                        ex.Out("asr.text", "Kup teraz", family="text")]

        with TemporaryDirectory() as tmp:
            data, out = Path(tmp) / "corpus", Path(tmp) / "out"
            (data / "media").mkdir(parents=True)
            for n, b in (("a.mp3", b"mp3-a"), ("b.mp4", b"mp4-b"), ("c.mp4", b"wideo-bez-dzwieku")):
                (data / "media" / n).write_bytes(b)
            ads = [{"ad_id": "a", "audio_path": "media/a.mp3"},
                   {"ad_id": "b", "video_path": "media/b.mp4", "audio_origin": "nagranie-b"},
                   {"ad_id": "c", "video_path": "media/c.mp4"},
                   {"ad_id": "d", "text": "sam tekst"}]
            (data / "ads.jsonl").write_text("".join(json.dumps(a) + "\n" for a in ads), encoding="utf-8")
            args = SimpleNamespace(data=str(data), out=str(out), threads=1)
            with patch("bench.set_threads"), patch("bench.cpu_seconds", return_value=0.0):
                self.main.cmd_extract(args, [FakeAudio()])
            fs = self.FeatureStore(out / "corpus")
            rows = {(r["ad_id"], r["field"]): r for r in fs.rows(status=None)}
            # jedno nagranie = jedno źródło: odcisk, głos i transkrypcja mają wspólny origin_id
            self.assertEqual({rows[("a", f)]["origin_id"] for f in
                              ("audio.fingerprint", "audio.speaker_embedding", "asr.text")}, {"a#audio_path"})
            self.assertEqual(rows[("b", "audio.fingerprint")]["origin_id"], "nagranie-b")
            self.assertEqual(rows[("b", "audio.fingerprint")]["source_ref"],
                             {"field": "video_path", "value": "media/b.mp4"})
            self.assertEqual(rows[("a", "audio.fingerprint")]["source_ref"],
                             {"field": "audio_path", "value": "media/a.mp3"})
            self.assertEqual((rows[("a", "audio.fingerprint")]["family"], rows[("a", "asr.text")]["family"]),
                             ("audio", "text"))
            self.assertEqual((rows[("c", "audio.fingerprint")]["status"], rows[("c", "audio.fingerprint")]["reason"]),
                             ("unavailable", "no_audio_stream"))
            self.assertEqual((rows[("d", "audio.fingerprint")]["status"], rows[("d", "audio.fingerprint")]["reason"]),
                             ("unavailable", "no_audio_input"))
            from features_lib import fingerprint_match
            sim, off, overlap = fingerprint_match(fs, "a", "b")
            self.assertEqual((sim, off, overlap), (1.0, 0, 120))
            self.assertIsNone(fingerprint_match(fs, "a", "c"))

    def test_chromaprint_similarity_finds_cropped_fragment(self):
        from features_lib import chromaprint_similarity
        rng = np.random.default_rng(1)
        full = rng.integers(-2**31, 2**31, size=400, dtype=np.int64).astype(np.int32)
        frag = full[100:220].copy()
        frag ^= np.int32(1)   # 1 z 32 bitów zmieniony (rekompresja)
        sim, off, overlap = chromaprint_similarity(full, frag)
        self.assertEqual((off, overlap), (100, 120))
        self.assertAlmostEqual(sim, 31 / 32)
        other = rng.integers(-2**31, 2**31, size=400, dtype=np.int64).astype(np.int32)
        self.assertLess(chromaprint_similarity(other[:200], frag)[0], 0.7)
        self.assertIsNone(chromaprint_similarity(full, np.array([], dtype=np.int32)))
        # liczby bez znaku prosto z JSON fpcalc dają ten sam wynik co int32 z arrays/
        self.assertEqual(chromaprint_similarity(full.view(np.uint32).tolist(), frag), (sim, off, overlap))
        # krótkie fragmenty na brzegach nie wygrywają: wspólna część >= połowa krótszego odcisku
        long_a = rng.integers(0, 2**32, size=4000, dtype=np.int64)
        long_b = rng.integers(0, 2**32, size=4000, dtype=np.int64)
        s, _, ov = chromaprint_similarity(long_a, long_b)
        self.assertGreaterEqual(ov, 2000)
        self.assertLess(s, 0.52)

    def test_chromaprint_maps_fpcalc_errors_to_reasons(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "asr_models", COMMON.parent / "containers" / "asr" / "models.py")
        asr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(asr)
        ext, item = asr.Chromaprint(), SimpleNamespace(path="/data/x.wav")
        asr.load_audio = Mock(return_value=np.ones(16000, dtype=np.float32))  # bez av/ffmpeg w tm-text
        cases = [("ERROR: Empty fingerprint", "audio_too_short"),
                 ("ERROR: Could not find audio stream", "no_audio_stream"),
                 ("ERROR: Could not open the input file (Invalid data)",
                  "unreadable_audio: ERROR: Could not open the input file (Invalid data)")]
        for stderr, reason in cases:
            done = SimpleNamespace(returncode=2, stdout="", stderr=stderr)
            with patch.object(asr.subprocess, "run", return_value=done):
                with self.assertRaises(self.extractor.Unavailable) as cm:
                    ext.extract(item)
            self.assertEqual(str(cm.exception), reason)
        ok = SimpleNamespace(returncode=0, stderr="",
                             stdout=json.dumps({"duration": 1.5, "fingerprint": [4294967295, 1]}))
        with patch.object(asr.subprocess, "run", return_value=ok):
            outs = {o.field: o for o in ext.extract(item)}
        self.assertEqual(outs["audio.fingerprint"].value["array"].tolist(), [-1, 1])
        self.assertEqual(outs["audio.duration_s"].value, 1.5)

    def _asr_module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "asr_models", COMMON.parent / "containers" / "asr" / "models.py")
        asr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(asr)
        return asr

    def test_silent_track_is_unavailable_for_all_audio_models(self):
        # regresja: nagranie ekranu z wyciszoną ścieżką (same zera) dawało status ok,
        # pusty tekst, odcisk ciszy i głos ciszy, które pasowały do każdego niemego nagrania
        asr = self._asr_module()
        self.assertTrue(asr.is_silent(np.zeros(16000, dtype=np.float32)))
        self.assertTrue(asr.is_silent(np.zeros(0, dtype=np.float32)))
        self.assertFalse(asr.is_silent(np.full(16000, 0.01, dtype=np.float32)))
        asr._has_audio_stream = Mock(return_value=True)
        fw = SimpleNamespace(decode_audio=Mock(return_value=np.zeros(32000, dtype=np.float32)))
        item = SimpleNamespace(path="/data/cisza.mp4")
        run = Mock()
        small = next(e for e in asr.EXTRACTORS if e.name == "faster-whisper-small-int8")
        with patch.dict(sys.modules, {"faster_whisper": fw}), patch.object(asr.subprocess, "run", run):
            for ext in (small, asr.Chromaprint(), asr.ECAPA()):
                ext.m = Mock()
                with self.assertRaises(self.extractor.Unavailable) as cm:
                    ext.extract(item)
                self.assertEqual(str(cm.exception), "silent_audio", ext.name)
                ext.m.transcribe.assert_not_called()
            run.assert_not_called()   # fpcalc nie liczy odcisku ciszy
            # cisza w zakresie liczenia cechy (ECAPA: pierwsze 60 s), dźwięk dopiero później
            late = np.zeros(70 * 16000, dtype=np.float32)
            late[65 * 16000:] = 0.2
            fw.decode_audio.return_value = late
            with self.assertRaises(self.extractor.Unavailable) as cm:
                asr.ECAPA().extract(item)
            self.assertEqual(str(cm.exception), "silent_audio")
            self.assertEqual(asr.load_audio(item.path).size, late.size)   # bez limitu: dźwięk jest
            fw.decode_audio.return_value = np.zeros(0, dtype=np.float32)
            with self.assertRaises(self.extractor.Unavailable) as cm:
                asr.load_audio(item.path)
            self.assertEqual(str(cm.exception), "audio_too_short")

    def test_whisper_without_speech_reports_reason(self):
        asr = self._asr_module()
        asr.load_audio = Mock(return_value=np.full(32000, 0.1, dtype=np.float32))
        stages = {e.name: e.stage for e in asr.EXTRACTORS if e.use_case == "asr"}
        self.assertEqual(stages, {"faster-whisper-small-int8": "default", "faster-whisper-base-int8": "on_demand"})
        ext = next(e for e in asr.EXTRACTORS if e.name == "faster-whisper-small-int8")
        ext.m = Mock()
        ext.m.transcribe.return_value = (iter([]), SimpleNamespace(duration=2.0))
        outs = {o.field: o for o in ext.extract(SimpleNamespace(path="/data/muzyka.mp3"))}
        self.assertEqual((outs["asr.text"].value, outs["asr.text"].reason), (None, "no_speech_detected"))
        self.assertEqual(outs["asr.segments"].value, [])

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
