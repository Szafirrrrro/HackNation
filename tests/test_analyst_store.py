"""Analyst evidence must not modify source or tracked fixtures."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scamgraph.analyst_store import PRIVATE_ROOT, append_private_card, private_corpus_path


class PrivateStoreTests(unittest.TestCase):
    def test_default_destination_is_ignored_and_untracked(self):
        root = Path(__file__).resolve().parents[1]
        target = private_corpus_path(root / "graph/data/sample_cards.jsonl")
        self.assertTrue(target.is_relative_to(PRIVATE_ROOT))
        relative = str(target.relative_to(root))
        subprocess.run(["git", "check-ignore", "-q", relative], cwd=root, check=True)
        tracked = subprocess.run(["git", "ls-files", "--", relative], cwd=root,
                                 capture_output=True, text=True, check=True)
        self.assertEqual(tracked.stdout, "")

    def test_private_append_preserves_source_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
                "scamgraph.analyst_store.PRIVATE_ROOT", Path(tmp) / "private"):
            source = Path(tmp) / "sample_cards.jsonl"
            source.write_bytes(b'{"ad_id":"synthetic"}\n')
            original = source.read_bytes()
            for kind in ("page_capture", "image_reference"):
                card = {"ad_id": kind, "text": {"ocr_text": "private evidence"},
                        "provenance": {"record_kind": kind, "image_path": str(source)}}
                target = append_private_card(source, card)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(len(target.read_text().splitlines()), 2)
            self.assertEqual(json.loads(target.read_text().splitlines()[1]), card)
            other = Path(tmp) / "other.jsonl"
            self.assertNotEqual(private_corpus_path(other), target)

    def test_symlink_cannot_redirect_write_to_source(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
                "scamgraph.analyst_store.PRIVATE_ROOT", Path(tmp) / "private"):
            source = Path(tmp) / "source.jsonl"
            source.write_text("original\n")
            target = private_corpus_path(source)
            target.parent.mkdir()
            target.symlink_to(source)
            with self.assertRaises(ValueError):
                append_private_card(source, {"text": "secret"})
            self.assertEqual(source.read_text(), "original\n")
