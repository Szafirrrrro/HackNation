"""Ewaluacja decyzji (wymaga numpy; TF-IDF także scikit-learn) - uruchamiaj w tm-text."""
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

try:
    import numpy as np
except ImportError:
    np = None
try:
    import sklearn  # noqa: F401
except ImportError:
    sklearn = None

LAB = Path(__file__).resolve().parent.parent


@unittest.skipIf(np is None, "brak numpy")
class EvaluateTest(unittest.TestCase):
    def setUp(self):
        sys.path[:0] = [str(LAB / "common"), str(LAB / "scripts")]
        import evaluate
        self.ev = evaluate

    def tearDown(self):
        for p in (str(LAB / "common"), str(LAB / "scripts")):
            sys.path.remove(p)

    def test_rank_metrics_counts_wrong_group_top1(self):
        S = np.array([[1, .9, .2], [.9, 1, .95], [.2, .95, 1]])
        r = self.ev.rank_metrics(S, ["a", "a", "b"])
        self.assertEqual((r["queries"], r["hit@1"], r["top1_wrong_group"]), (2, "1/2 (50%)", "1/2 (50%)"))

    def test_image_ties_count_against_method(self):
        # wariant ma identyczny wynik dla prawdziwego i obcego oryginału -> nie jest top-1
        fs = Mock()
        variants = [{"ad_id": "x~crop", "variant_of": "a", "kind": "crop"}]
        S = np.array([[5.0, 5.0]])
        with patch.object(self.ev, "image_scores",
                          side_effect=lambda f, q, c: {"m": S if len(q) == 1 else np.eye(2)}):
            r = self.ev.eval_images(fs, variants, {"a": "g1", "b": "g2"}, {})["m"]
        self.assertEqual(r["top1"], "0/1 (0%)")
        self.assertEqual(r["top3"], "1/1 (100%)")

    def test_cer_and_levenshtein(self):
        self.assertEqual(self.ev.levenshtein("kot", "kat"), 1)
        self.assertEqual(self.ev.norm_text("  Ala\nMA "), "ala ma")

    @unittest.skipIf(sklearn is None, "brak scikit-learn")
    def test_tfidf_similarity_default_method(self):
        from features_lib import tfidf_similarity
        keys, S, vec = tfidf_similarity({"a": "Dopłata 2500 zł", "b": "dopłata 2500 zł!", "c": "mecz ligi"})
        self.assertEqual(keys, ["a", "b", "c"])
        self.assertGreater(S[0, 1], S[0, 2])
        self.assertEqual(vec.transform(["nowe zapytanie"]).shape[1], len(vec.vocabulary_))


if __name__ == "__main__":
    unittest.main()
