"""dom-shingle-minhash-v1: page-local template fingerprint and its hand-off to the graph card."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scamgraph.capture import staging
from scamgraph.discovery.graph_feed import projection
from scamgraph.landing import (TEMPLATE_METHOD, TEMPLATE_PERM, Document, landing, structure_tokens,
                               template_minhash, template_similarity)
from scamgraph.sources import digest

# Own synthetic layout: header, menu, article, comments, order form, footer.
LAYOUT = """<!doctype html><html><head><title>{title}</title><meta charset="utf-8"></head><body>
<header><nav><ul><li><a href="/">Start</a></li><li><a href="/news">News</a></li><li><a href="/sport">Sport</a></li></ul></nav></header>
<main><article><h1>{title}</h1>{body}</article>
<section class="comments"><div class="comment"><span>Ala</span><p>Super.</p></div>
<div class="comment"><span>Ola</span><p>Polecam.</p></div></section>
<form action="/order" method="post"><label>Imię<input name="n"></label><label>Telefon<input name="p"></label>
<button type="submit">Zamów</button></form></main>
<footer><p>Stopka</p><a href="/privacy">Prywatność</a><a href="/terms">Regulamin</a></footer></body></html>"""
TWIN_A = LAYOUT.format(title="Napaść na Jana", body="<p>Akapit 1.</p><img src=a.png><p>Akapit 2.</p>")
TWIN_B = LAYOUT.format(title="Napaść na Piotra", body="<p>Akapit 1.</p><h2>Śródtytuł</h2><img src=b.png><p>Akapit 2.</p>")
OTHER = ("<html><body><div><table>" + "<tr><td><b>x</b></td><td><i>y</i></td></tr>" * 6
         + "</table><dl><dt>a</dt><dd>b</dd></dl></div></body></html>")


def sig(html):
    value, reason = template_minhash(Document(html))
    return value, reason


class TemplateMinhashTests(unittest.TestCase):
    def test_tokens_follow_document_order_and_skip_void_closings(self):
        self.assertEqual(structure_tokens(Document("<div><p>a<br>b</p><img src=x></div>")),
                         ["<div", "<p", "<br", "</p", "<img", "</div"])

    def test_deterministic_and_identical_html_is_one(self):
        a, _ = sig(TWIN_A)
        b, _ = sig(TWIN_A)
        self.assertEqual(a, b)
        self.assertEqual(a["method"], TEMPLATE_METHOD)
        self.assertEqual(len(a["signature"]), TEMPLATE_PERM)
        self.assertTrue(all(0 <= v < 2 ** 32 for v in a["signature"]))
        self.assertEqual(template_similarity(a, b), 1.0)

    def test_text_and_attributes_do_not_change_fingerprint(self):
        a, _ = sig(TWIN_A)
        b, _ = sig(TWIN_A.replace("Akapit", "Inny tekst").replace('href="/news"', 'href="/x" class="y"'))
        self.assertEqual(a["signature"], b["signature"])

    def test_near_template_scores_above_unrelated_page(self):
        a, b, c = sig(TWIN_A)[0], sig(TWIN_B)[0], sig(OTHER)[0]
        near, far = template_similarity(a, b), template_similarity(a, c)
        self.assertLess(near, 1.0)
        self.assertGreater(near, 0.5)
        self.assertLess(far, 0.1)

    def test_short_document_has_reason_instead_of_fingerprint(self):
        value, reason = sig("<p>x</p>")
        self.assertIsNone(value)
        self.assertIn("Za mało tagów", reason)

    def test_oversized_document_has_reason_instead_of_fingerprint(self):
        with patch("scamgraph.landing.TEMPLATE_MAX_TOKENS", 20):
            value, reason = sig(TWIN_A)
        self.assertIsNone(value)
        self.assertIn("Za dużo tagów", reason)

    def test_incomparable_fingerprints(self):
        a, _ = sig(TWIN_A)
        self.assertIsNone(template_similarity(a, None))
        self.assertIsNone(template_similarity(a, {**a, "k": 5}))
        self.assertIsNone(template_similarity(a, {**a, "signature": a["signature"][:10]}))

    def test_landing_adds_field_only_for_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "page.html"
            page.write_text(TWIN_A, encoding="utf-8")
            item = {"path": "page.html", "sha256": digest(page), "role": "html"}
            self.assertEqual(landing(page, item)["dom_template_minhash"], sig(TWIN_A)[0])
            self.assertNotIn("dom_template_minhash", landing(page, item, ad_card=True))
            page.write_text("<p>x</p>", encoding="utf-8")
            short = landing(page, {**item, "sha256": digest(page)})
            self.assertIsNone(short["dom_template_minhash"])
            self.assertIn("dom_template_unavailable", short)


class GraphFeedTests(unittest.TestCase):
    def setUp(self):
        directory = staging(Path(tempfile.gettempdir()))
        self.tmp = directory.__enter__()
        self.addCleanup(directory.__exit__, None, None, None)

    def package(self, pages, linked=True):
        folder = self.tmp / "cap1"
        folder.mkdir(exist_ok=True)
        nav = {"file": "landing/network.har", "origin_id": "o1", "entry": 0}
        result = {"ad": {"ad_id": "meta-ad-library/1", "text": ""}, "pixels": [], "pages": pages,
                  "networks": [{"evidence": {"file": "landing/network.har", "origin_id": "o1"}, "pixels": [],
                                "entries": [{"evidence": nav, "status": 200,
                                             "address": {"host": "shop.example", "path": "/offer"}}]}],
                  "ad_page_links": [{"capture_id": "cap1", "ad_id": "meta-ad-library/1",
                                     "final_url": "https://shop.example/offer", "navigation_evidence": nav}]
                  if linked else []}
        (folder / "extracted.json").write_text(json.dumps(result), encoding="utf-8")
        manifest = {"capture_id": "cap1", "artifacts": [],
                    "result": {"path": "extracted.json", "sha256": digest(folder / "extracted.json")}}
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return folder

    def test_single_fingerprint_reaches_card(self):
        fp = sig(TWIN_A)[0]
        card = projection(self.package([{"pixels": [], "dom_template_minhash": fp}]))
        self.assertEqual(card["infra"]["final_domain"], "shop.example")
        self.assertEqual(card["page"]["dom_template_minhash"], fp)

    def test_conflicting_or_unlinked_pages_leave_card_empty(self):
        a, b = sig(TWIN_A)[0], sig(OTHER)[0]
        card = projection(self.package([{"pixels": [], "dom_template_minhash": a},
                                        {"pixels": [], "dom_template_minhash": b}]))
        self.assertNotIn("dom_template_minhash", card["page"])
        card = projection(self.package([{"pixels": [], "dom_template_minhash": a}], linked=False))
        self.assertEqual(card["page"], {})


if __name__ == "__main__":
    unittest.main()
