"""Generate the full trust list while preserving existing exclusions."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from graph.tools.build_trusted_list import main
from graph.ftf_graph.card import load_trusted


class TrustedListTests(unittest.TestCase):
    def test_default_reads_sources_in_memory_and_refreshes_all_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ranking = root / "tranco_46YVX.csv"
            manual = root / "trusted_manual.txt"
            cert = root / "cert_domains.txt"
            psl = root / "psl.dat"
            ranking.write_text("22710,mbank.pl\n1000001,last.example\n")
            manual.write_text("manual.example\n")
            psl.write_text("// ===BEGIN PRIVATE DOMAINS===\n// ===END PRIVATE DOMAINS===\n")
            with patch("graph.ftf_graph.trusted.DATA", root), patch(
                    "graph.ftf_graph.trusted.default_psl_path", return_value=psl), patch.dict(
                    "os.environ", {"FTF_TRUSTED_DOMAINS": ""}):
                first = load_trusted()
                self.assertEqual(first, {"mbank.pl", "last.example", "manual.example"})
                self.assertIs(first, load_trusted())
                ranking.write_text(ranking.read_text() + "2000000,new.example\n")
                self.assertIn("new.example", load_trusted())
                manual.write_text("manual.example\nother.example\n")
                self.assertIn("other.example", load_trusted())
                cert.write_text("last.example\n")
                self.assertNotIn("last.example", load_trusted())
                psl.write_text("// ===BEGIN PRIVATE DOMAINS===\nuser.new.example\n// ===END PRIVATE DOMAINS===\n")
                self.assertNotIn("new.example", load_trusted())
                psl.unlink()
                with self.assertRaises(RuntimeError):
                    load_trusted()
            self.assertFalse((root / "trusted_domains.txt").exists())

    def test_cached_list_refreshes_after_regeneration_and_path_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trusted.txt"
            path.write_text("first.example\n")
            first = load_trusted(str(path))
            self.assertIs(first, load_trusted(str(path)))
            path.write_text("first.example\nmbank.pl\n")
            self.assertIn("mbank.pl", load_trusted(str(path)))
            with patch.dict("os.environ", {"FTF_TRUSTED_DOMAINS": str(path)}):
                self.assertIn("mbank.pl", load_trusted())

    def test_entire_ranking_with_hosting_and_cert_exclusions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tranco.csv").write_text(
                "rank,domain\n1,first.example\n10001,beyond-limit.example\n"
                "22710,mbank.pl\n50000,hosting.example\n80000,blocked.example\n"
                "1000001,last.example\n")
            (root / "manual.txt").write_text("manual.example\nblocked.example\n")
            (root / "cert.txt").write_text("blocked.example\n")
            (root / "psl.dat").write_text(
                "// ===BEGIN PRIVATE DOMAINS===\nuser.hosting.example\n// ===END PRIVATE DOMAINS===\n")
            output = root / "trusted.txt"
            args = ["build_trusted_list", "--tranco", str(root / "tranco.csv"),
                    "--manual", str(root / "manual.txt"), "--cert", str(root / "cert.txt"),
                    "--psl", str(root / "psl.dat"), "--out", str(output)]
            with patch("sys.argv", args):
                self.assertEqual(main(), 0)
            domains = {line for line in output.read_text().splitlines() if line and not line.startswith("#")}
            self.assertEqual(domains, {"first.example", "beyond-limit.example", "mbank.pl",
                                       "last.example", "manual.example"})
