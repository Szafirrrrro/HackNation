"""Analyst evidence must not modify source or tracked fixtures."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scamgraph.analyst_store import PRIVATE_ROOT, append_private_card, private_corpus_path


class PrivateStoreTests(unittest.TestCase):
    @unittest.skipUnless((Path(__file__).resolve().parents[1] / ".git").exists(), "Requires a Git checkout")
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
            try:
                target.symlink_to(source)
            except OSError as exc:
                if getattr(exc, "winerror", None) == 1314:
                    self.skipTest("Windows user lacks permission to create a symbolic link")
                raise
            with self.assertRaises(ValueError):
                append_private_card(source, {"text": "secret"})
            self.assertEqual(source.read_text(), "original\n")

    def test_append_after_truncated_line_keeps_new_record_readable(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
                "scamgraph.analyst_store.PRIVATE_ROOT", Path(tmp) / "private"):
            source = Path(tmp) / "source.jsonl"
            target = private_corpus_path(source)
            target.parent.mkdir()
            target.write_bytes(b'{"ad_id": "cut')
            append_private_card(source, {"ad_id": "next"})
            self.assertEqual(json.loads(target.read_bytes().splitlines()[-1]), {"ad_id": "next"})

    def test_reader_skips_and_counts_broken_lines(self):
        from scamgraph.analyst_store import read_private_cards
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "private.jsonl"
            path.write_bytes(b'{"ad_id":"a"}\n{"broken\n[1]\n{"text":{}}\n\xff\xfe\n\n{"ad_id":"b"}\n')
            self.assertEqual(read_private_cards(path), ([{"ad_id": "a"}, {"ad_id": "b"}], 4))

    def test_reader_survives_deep_nesting_bom_and_wrong_shapes(self):
        from scamgraph.analyst_store import read_private_cards
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "private.jsonl"
            path.write_bytes(b'\xef\xbb\xbf{"ad_id":"a"}\n' + b"[" * 200000 + b"]" * 200000
                             + b'\n{"ad_id":"p","provenance":"x"}\n')
            self.assertEqual(read_private_cards(path), ([{"ad_id": "a"}], 2))

    def test_hardlink_cannot_redirect_write_to_source(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
                "scamgraph.analyst_store.PRIVATE_ROOT", Path(tmp) / "private"):
            source = Path(tmp) / "source.jsonl"
            source.write_bytes(b"original\n")
            target = private_corpus_path(source)
            target.parent.mkdir()
            os.link(source, target)
            with self.assertRaises(ValueError):
                append_private_card(source, {"ad_id": "secret"})
            self.assertEqual(source.read_bytes(), b"original\n")
