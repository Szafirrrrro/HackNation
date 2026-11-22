"""Generate the limited trust list while preserving existing exclusions."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from graph.tools.build_trusted_list import main
from graph.ftf_graph.card import is_trusted, load_trusted


class TrustedListTests(unittest.TestCase):
    def test_default_reads_sources_in_memory_and_refreshes_all_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ranking = root / "tranco_46YVX.csv"
            manual = root / "trusted_manual.txt"
            cert = root / "cert_domains.txt"
            psl = root / "psl.dat"
            ranking.write_text("2710,inside.example\n9999,last.example\n")
            manual.write_text("manual.example\n")
            psl.write_text("// ===BEGIN PRIVATE DOMAINS===\n// ===END PRIVATE DOMAINS===\n")
            with patch("graph.ftf_graph.trusted.DATA", root), patch(
                    "graph.ftf_graph.trusted.default_psl_path", return_value=psl), patch.dict(
                    "os.environ", {"FTF_TRUSTED_DOMAINS": ""}):
                first = load_trusted()
                self.assertEqual(first, {"inside.example", "last.example", "manual.example"})
                self.assertIs(first, load_trusted())
                ranking.write_text(ranking.read_text() + "9998,new.example\n")
                self.assertIn("new.example", load_trusted())
                manual.write_text("manual.example\nother.example\n")
                self.assertIn("other.example", load_trusted())
                cert.write_text("last.example\n")
                self.assertNotIn("last.example", load_trusted())
                psl.write_text("// ===BEGIN PRIVATE DOMAINS===\nuser.new.example\n// ===END PRIVATE DOMAINS===\n")
                # the parent stays; the platform's tenant is evidence through the longest suffix
                self.assertIn("new.example", load_trusted())
                self.assertFalse(is_trusted("oferta.user.new.example", load_trusted()))
                self.assertTrue(is_trusted("user.new.example", load_trusted()))
                psl.write_text("// ===BEGIN PRIVATE DOMAINS===\nnew.example\n// ===END PRIVATE DOMAINS===\n")
                self.assertNotIn("new.example", load_trusted())
                self.assertFalse(is_trusted("oferta.new.example", load_trusted()))
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

    def test_limited_ranking_with_hosting_and_cert_exclusions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tranco.csv").write_text(
                "rank,domain\n1,first.example\n10001,beyond-limit.example\n"
                "22710,mbank.pl\n2710,inside.example\n500,hosting.example\n800,blocked.example\n"
                "9999,last.example\n")
            (root / "manual.txt").write_text("manual.example\nblocked.example\n")
            (root / "cert.txt").write_text("blocked.example\n")
            (root / "psl.dat").write_text(
                "// ===BEGIN PRIVATE DOMAINS===\nhosting.example\n// ===END PRIVATE DOMAINS===\n")
            output = root / "trusted.txt"
            args = ["build_trusted_list", "--tranco", str(root / "tranco.csv"),
                    "--manual", str(root / "manual.txt"), "--cert", str(root / "cert.txt"),
                    "--psl", str(root / "psl.dat"), "--out", str(output)]
            with patch("sys.argv", args):
                self.assertEqual(main(), 0)
            domains = {line for line in output.read_text().splitlines() if line and not line.startswith("#")}
            self.assertEqual(domains, {"first.example", "inside.example",
                                       "last.example", "manual.example"})


class DomainEvidenceTests(unittest.TestCase):
    """Fetching a URL and using its host as linking evidence are separate decisions."""

    SHARED = ["l.facebook.com", "m.facebook.com", "l.instagram.com", "www.google.com", "docs.google.com",
              "sites.google.com", "www.youtube.com", "youtu.be", "bit.ly", "t.co", "t.me", "wa.me", "forms.gle",
              "forms.office.com", "pastebin.com", "fonts.googleapis.com", "ajax.googleapis.com",
              "lh3.googleusercontent.com", "www.weebly.com", "linktr.ee", "netlify.app", "github.io",
              "s3.amazonaws.com",
              # shorteners outside the top 10 000
              "buff.ly", "v.gd", "tiny.pl", "qrco.de", "urlz.fr", "bitly.ws", "dub.sh", "smarturl.it", "lnk.bio",
              # parents of PSL entries, wildcard suffixes and services of the platforms themselves
              "form.typeform.com", "dns10.ovh.net", "fra1.digitaloceanspaces.com", "europe-west1.run.app",
              "eu-west-1.compute.amazonaws.com", "storage.googleapis.com", "raw.githubusercontent.com",
              "1.bp.blogspot.com", "login.windows.net", "sts.amazonaws.com", "s3-accelerate.amazonaws.com",
              "open.substack.com", "miro.medium.com", "static1.squarespace.com",
              "link.medium.com", "help.medium.com", "account.squarespace.com", "login.squarespace.com",
              "support.squarespace.com", "public-api.wordpress.com"]
    TENANTS = ["oferta.weebly.com", "oferta.tilda.ws", "oferta.mystrikingly.com", "oferta.netlify.app",
               "oferta.github.io", "oferta.blogspot.com", "oferta.s3.amazonaws.com", "oferta.sharepoint.com",
               "www.oferta.netlify.app", "filesdl.top",
               "bucket.storage.googleapis.com", "bucket.s3-accelerate.amazonaws.com", "oferta.akamaihd.net",
               "vm.bc.googleusercontent.com", "autor.medium.com", "bucket.fra1.digitaloceanspaces.com",
               "usluga.europe-west1.run.app", "nazwa.eth.limo", "oferta.hostingersite.com",
               "oferta.godaddysites.com", "oferta.webnode.page", "oferta.squarespace.com",
               "canister.raw.icp0.io", "p01--sklep--abc.code.run", "x.localto.net", "x.at.ply.gg",
               "oferta.paywhirl.com", "oferta.devinapps.com", "firma.typeform.com", "firma.my.salesforce.com",
               "vps-1.vps.ovh.net", "bucket.s3.gra.cloud.ovh.net", "oferta.crm.dev",
               "ec2-54-12-34-56.compute-1.amazonaws.com", "ec2-3-1-2-3.eu-west-1.compute.amazonaws.com"]

    def setUp(self):
        env = patch.dict("os.environ", {"FTF_TRUSTED_DOMAINS": ""})
        env.start()
        self.addCleanup(env.stop)
        self.trusted = load_trusted()

    def linked(self, host, field):
        """Score and cluster three otherwise unrelated ads next to the demo corpus."""
        from graph.ftf_graph.card import parse_card
        from graph.ftf_graph.cluster import cluster
        from graph.ftf_graph.scoring import Scorer
        sample = Path(__file__).resolve().parents[1] / "graph/data/sample_cards.jsonl"
        rows = [json.loads(line) for line in sample.read_text(encoding="utf-8").splitlines() if line.strip()]
        for i in range(3):
            final = host if field == "final" else f"unrelated-{i}.example"
            chain = [host, final] if field == "redirect" else []
            rows.append({"ad_id": f"X{i}", "infra": {"final_domain": final, "redirect_chain": chain}})
        scores, _ = Scorer([parse_card(row, self.trusted) for row in rows]).score_all()
        labels = cluster(scores).labels[-3:]
        return float(scores[-1, -2]), bool((labels >= 0).all() and len(set(labels)) == 1)

    def test_shared_host_alone_never_links_unrelated_ads(self):
        for host in self.SHARED:
            for field in ("redirect", "final"):
                with self.subTest(host=host, field=field):
                    self.assertEqual(self.linked(host, field), (0.0, False))

    def test_tenant_host_still_links_its_ads(self):
        for host in self.TENANTS:
            for field in ("redirect", "final"):
                with self.subTest(host=host, field=field):
                    self.assertTrue(self.linked(host, field)[1])

    def test_custom_list_cannot_hide_tenants_or_enable_shared_hosts(self):
        from graph.ftf_graph.card import is_trusted
        custom = frozenset({"weebly.com", "tilda.ws", "netlify.app", "google.com"})
        for host in ("oferta.weebly.com", "oferta.tilda.ws", "oferta.netlify.app"):
            self.assertFalse(is_trusted(host, custom), host)
        for host in ("bit.ly", "BIT.LY.", "l.facebook.com"):
            self.assertTrue(is_trusted(host, frozenset()), host)

    def test_every_private_suffix_keeps_its_tenants(self):
        """Property over the whole PSL, so fixing one platform cannot silently break another."""
        from graph.ftf_graph.card import is_trusted
        from graph.ftf_graph.domain_policy import REGIONAL_WILDCARDS, SHARED_HOSTS
        from graph.ftf_graph.trusted import platform_rules
        hidden = []
        for suffix in sorted(platform_rules()[0] - SHARED_HOSTS):
            host = "najemca." + suffix
            if suffix in REGIONAL_WILDCARDS:
                host = "najemca.region." + suffix
            if is_trusted(host, self.trusted):
                hidden.append(host)
        self.assertEqual(hidden, [])

    def test_registry_suffix_from_ranking_is_not_a_popular_domain(self):
        self.assertNotIn("bank.in", self.trusted)  # ranked, but it is a registry
        self.assertIn("gov.pl", self.trusted)  # manual entry wins

    def test_www_of_a_platform_is_the_platform(self):
        from graph.ftf_graph.card import is_trusted
        for host in ("www.weebly.com", "www.netlify.app"):  # parse_card strips www, so check the rule directly
            self.assertTrue(is_trusted(host, frozenset()), host)

    def test_cert_list_beats_shared_hosts_and_covers_subdomains(self):
        from graph.ftf_graph.card import is_trusted
        from graph.ftf_graph import trusted as sources
        with tempfile.TemporaryDirectory() as tmp:
            cert = Path(tmp) / "cert_domains.txt"
            cert.write_text("bit.ly\nevil.onet.pl\n")
            psl = sources.default_psl_path()
            with patch("graph.ftf_graph.trusted.DATA", Path(tmp)), patch(
                    "graph.ftf_graph.trusted.default_psl_path", return_value=psl):
                for host in ("bit.ly", "evil.onet.pl", "x.evil.onet.pl"):
                    self.assertFalse(is_trusted(host, frozenset({"onet.pl"})), host)

    def test_custom_list_works_without_psl_package(self):
        from graph.ftf_graph.card import is_trusted
        with patch("graph.ftf_graph.trusted.default_psl_path", side_effect=ImportError):
            self.assertTrue(is_trusted("m.own.example", frozenset({"own.example"})))

    def test_shared_nameserver_is_not_evidence(self):
        from graph.ftf_graph.card import parse_card
        card = parse_card({"ad_id": "ns", "infra": {"rdap": {"nameservers": ["dns10.ovh.net", "ns.own.example"]}}},
                          self.trusted)
        self.assertEqual([a.value for a in card.artifacts if a.kind == "nameserver"], ["ns.own.example"])

    def test_host_matching_respects_label_boundaries(self):
        from graph.ftf_graph.card import is_trusted
        for host in ("evilt.co", "bit.ly.evil.example", "google.com.evil.example", "notfacebook.com"):
            self.assertFalse(is_trusted(host, self.trusted), host)

    def test_exclusions_do_not_remove_parents_or_whole_registries(self):
        for domain in ("google.com", "office.com", "bbc.co.uk"):
            self.assertIn(domain, self.trusted)
        self.assertLess(len(self.trusted), 11_000)
        self.assertNotIn("mbank.pl", self.trusted)  # rank 22710 is outside the limit

    def test_every_manual_entry_is_effective(self):
        from graph.ftf_graph.card import is_trusted
        from graph.ftf_graph.trusted import DATA, read_list
        for domain in read_list(DATA / "trusted_manual.txt"):
            self.assertTrue(is_trusted(domain, self.trusted), domain)
