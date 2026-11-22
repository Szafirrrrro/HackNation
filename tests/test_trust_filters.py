"""Landing-page skip filters: ranking with PSL private suffixes, never-trusted hosts, no network by default."""
import hashlib
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scamgraph.discovery import authoritive_corpora as corpora
from scamgraph.discovery import bidirectional_verify, verified_entity
from scamgraph.discovery.service import collect_landing


def no_network(*args, **kwargs):
    raise AssertionError("unexpected network access")


class OfflineTestCase(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket.connect", "socket.create_connection", "socket.getaddrinfo"):
            p = patch(target, no_network)
            p.start()
            self.addCleanup(p.stop)


class RankingTests(OfflineTestCase):
    def test_default_list_is_bundled_and_cached(self):
        self.assertTrue(corpora.DEFAULT_RANKING_LIST_PATH.is_file())
        first = corpora.load_tranco_top()
        self.assertIn("google.com", first)
        self.assertIs(first, corpora.load_tranco_top())

    def test_registrable_domain_uses_private_suffixes(self):
        cases = {"xyz.s3.amazonaws.com": "xyz.s3.amazonaws.com", "abc.netlify.app": "abc.netlify.app",
                 "foo.github.io": "foo.github.io", "www.google.com": "google.com",
                 "sklep.com.pl": "sklep.com.pl", "a.b.co.uk": "b.co.uk", "10.0.0.1": "", "github.io": ""}
        for host, expected in cases.items():
            self.assertEqual(corpora.extract_etld_plus_1(host), expected, host)

    def test_hosting_forms_and_shorteners_are_not_trusted_by_rank(self):
        for url in ["https://oferta.s3.amazonaws.com/index.html", "https://abc.netlify.app/", "https://x.web.app/",
                    "https://y.workers.dev/", "https://z.cloudfront.net/a", "https://docs.google.com/forms/d/1/viewform",
                    "https://forms.gle/abc", "https://bit.ly/abc", "https://t.co/x", "https://t.me/kanal",
                    "https://wa.me/48500100200", "https://shop.wixsite.com/x", "https://www.dropbox.com/s/x"]:
            self.assertIsNone(corpora.match_authoritative_corpus(url), url)

    def test_reviewed_user_content_hosts_are_not_trusted_by_rank(self):
        for url in ["https://forms.office.com/r/abc", "https://evil.sharepoint.com/x", "https://1drv.ms/x",
                    "https://lh3.googleusercontent.com/x", "https://evil.z13.web.core.windows.net/",
                    "https://abc.lambda-url.us-east-1.on.aws/", "https://evil.amazonaws.com/",
                    "https://evil.mystrikingly.com/", "https://evil.tilda.ws/", "https://heylink.me/x",
                    "https://www.canva.com/design/x", "https://amzn.to/x", "https://youtu.be/x",
                    "https://m.me/x", "https://chat.whatsapp.com/x", "https://discord.gg/x",
                    "https://www.olx.pl/d/oferta/x", "https://www.tiktok.com/@x", "https://www.instagram.com/x/",
                    "https://pastebin.com/x"]:
            self.assertIsNone(corpora.match_authoritative_corpus(url), url)

    def test_custom_hosts_extend_defaults(self):
        self.assertTrue(corpora.is_multi_tenant_host("bit.ly", multi_tenant_hosts={"example.org"}))
        self.assertTrue(corpora.is_multi_tenant_host("a.example.org", multi_tenant_hosts={"example.org"}))
        self.assertFalse(corpora.is_multi_tenant_host("evilt.co"))

    def test_ranked_domain_is_skipped(self):
        code, reason = corpora.match_authoritative_corpus("https://www.google.com/search")
        self.assertEqual(code, "ranked_corpus")
        self.assertIn("google.com", reason)

    def test_blocklist_error_means_fetch(self):
        def broken(host, etld1):
            raise RuntimeError("blocklist down")
        self.assertIsNone(corpora.match_authoritative_corpus("https://www.google.com/", has_active_blocklist_hit=broken))

    def test_missing_list_trusts_nothing(self):
        self.assertIsNone(corpora.match_authoritative_corpus("https://www.google.com/", ranking_list_path="/nonexistent.csv"))


class CollectLandingOrderTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.db = self.root / "trust.sqlite3"
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("CREATE TABLE trusted_domains(domain TEXT PRIMARY KEY NOT NULL COLLATE NOCASE)")
            db.execute("INSERT INTO trusted_domains VALUES ('sklep-zaufany.pl')")
        for name in ("match_verified_entity",):
            p = patch.object(verified_entity, name, side_effect=AssertionError("network filter called"))
            self.verified = p.start()
            self.addCleanup(p.stop)
        p = patch.object(bidirectional_verify, "match_bidirectional_verification",
                         side_effect=AssertionError("network filter called"))
        self.closed_loop = p.start()
        self.addCleanup(p.stop)

    def finding(self, url):
        html = f'<div><a href="{url}">Kup teraz</a></div>'.encode()
        path = self.root / "card.html"
        path.write_bytes(html)
        card = {"cta_element": 2, "cta_attribute": "href", "cta": "Kup teraz"}
        return SimpleNamespace(card=card, original=path, source_sha256=hashlib.sha256(html).hexdigest(),
                               locator="element:1")

    def collect(self, url, **options):
        return collect_landing(self.root, {"mode": "live", "domain_db": str(self.db), **options},
                               self.finding(url), defer=True)

    def test_trusted_database_short_circuits_everything(self):
        with patch.object(corpora, "match_authoritative_corpus", side_effect=AssertionError("ranking called")):
            out = self.collect("https://sklep-zaufany.pl/oferta")
        self.assertEqual(out["reason_code"], "trusted_domain")

    def test_ranking_skips_without_network_filters(self):
        out = self.collect("https://www.google.com/")
        self.assertEqual(out["reason_code"], "ranked_corpus")
        self.verified.assert_not_called()

    def test_facebook_targets_are_never_skipped_by_ranking(self):
        for url in ["https://www.facebook.com/marketplace/item/123/", "https://www.facebook.com/strona/posts/123",
                    "https://fb.watch/abc"]:
            with patch.object(corpora, "match_authoritative_corpus", side_effect=AssertionError("ranking called")):
                self.assertEqual(self.collect(url)["reason_code"], "queued", url)

    def test_unknown_host_is_queued_without_network_filters_by_default(self):
        out = self.collect("https://oferta.s3.amazonaws.com/index.html")
        self.assertEqual(out["reason_code"], "queued")
        self.verified.assert_not_called()
        self.closed_loop.assert_not_called()

    def test_verified_entity_keeps_precedence_over_ranking(self):
        self.verified.side_effect = None
        self.verified.return_value = ("ov_ev_tls", "OV")
        with patch.object(corpora, "match_authoritative_corpus", side_effect=AssertionError("ranking called")):
            out = self.collect("https://www.google.com/", network_trust_checks=True)
        self.assertEqual(out["reason_code"], "ov_ev_tls")
        self.closed_loop.assert_not_called()

    def test_closed_loop_runs_last_and_only_when_enabled(self):
        self.verified.side_effect = None
        self.verified.return_value = None
        self.closed_loop.side_effect = None
        self.closed_loop.return_value = ("closed_loop_wikidata", "Q1")
        out = self.collect("https://nieznana-firma.pl/", network_trust_checks=True)
        self.assertEqual(out["reason_code"], "closed_loop_wikidata")
        self.closed_loop.reset_mock()
        self.assertEqual(self.collect("https://www.google.com/", network_trust_checks=True)["reason_code"],
                         "ranked_corpus")
        self.closed_loop.assert_not_called()

    def test_network_filters_only_when_enabled_in_live(self):
        self.verified.side_effect = None
        self.verified.return_value = ("ov_ev_tls", "OV")
        out = self.collect("https://nieznana-firma.pl/", network_trust_checks=True)
        self.assertEqual(out["reason_code"], "ov_ev_tls")
        self.closed_loop.assert_not_called()
        self.verified.reset_mock()
        out = self.collect("https://nieznana-firma.pl/", network_trust_checks=True, mode="replay")
        self.assertEqual(out["reason_code"], "queued")
        self.verified.assert_not_called()


if __name__ == "__main__":
    unittest.main()
