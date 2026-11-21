import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scamgraph.capture import capture, read_json, staging, verified, write_json
from scamgraph.catalog import preview
from scamgraph.discovery.engine import SCHEMA
from scamgraph.discovery.reanalyze import reanalyze_run
from scamgraph.sources import digest


HTML = """<main><nav><a>Odchudzanie</a></nav>
<section class="product-tile"><h3>Produkt testowy</h3><p><span>12,50 zł</span></p>
<div class="aggregate-rating"><span itemprop="ratingValue">4.5</span><span itemprop="reviewCount">9</span></div></section>
<div class="cart-total"><span class="price">0 , 00 zł</span></div>
<div class="review_box"><p class="first_p">Produkt testowy</p><svg class="rating"><use href="#stars-full-star"/></svg>
<p class="second_pp">Podpis (zweryfikowany klient)</p><div class="review-text">Tekst testowej opinii.</div></div>
<div role="dialog">Używamy ciasteczek</div></main>
<footer><small>Porcja pomaga obniżyć poziom cholesterolu o 5% w miesiąc.</small></footer>"""


class LandingReanalysisTests(unittest.TestCase):
    def test_original_response_recovers_only_document_text_and_links_its_parts(self):
        with staging(Path(tempfile.gettempdir())) as root:
            source = root/"input"
            raw = source/"landing/original/response.html"
            raw.parent.mkdir(parents=True)
            raw.write_text('<article><h1>Oprawa</h1>' + '<div>'*1200 +
                           '<p>Pro<b>dukt</b> <i>kosztuje</i> 49,<b>99</b> zł.</p>' + '</div>'*1200 +
                           '<input value="PRIVATE"><script>const secret="HIDDEN";</script></article>', encoding="utf8")
            (source/"landing/index.html").write_text('<div role="dialog">Cookies <button>OK</button></div>', encoding="utf8")
            folder = capture(source, root/"captures")
            meta = read_json(folder/"manifest.json")
            page, = read_json(folder/"extracted.json")["pages"]
            self.assertEqual(page["reading_source"]["file"], "landing/original/response.html")
            row = page["reading_text"][-1]
            self.assertEqual(preview(folder, meta, row["evidence"]), ("text", "Produkt kosztuje 49,99 zł."))
            item, = meta["derived_files"]
            txt = (folder/item["path"]).read_text(encoding="utf8")
            self.assertIn(row["value"], txt)
            self.assertNotIn("HIDDEN", txt)
            self.assertNotIn("PRIVATE", txt)
            verified(folder, meta)

    def test_newsletter_and_cookie_policy_are_not_offer_or_dialog(self):
        with staging(Path(tempfile.gettempdir())) as root:
            src = root/"page.html"
            src.write_text('<footer role="region"><p>Polityka cookies.</p>'
                           '<p>Podaj adres e-mail, aby otrzymywać newsletter.</p></footer>', encoding="utf8")
            data = read_json(capture(src, root/"captures")/"extracted.json")
            self.assertTrue(data["signals"])
            self.assertIsNone(data["landing_summary"]["offer"])
            self.assertIsNone(data["landing_summary"]["dialog"])

    def test_source_context_and_evidence(self):
        with staging(Path(tempfile.gettempdir())) as root:
            source = root / "oferta.html"
            source.write_text(HTML, encoding="utf8")
            folder = capture(source, root/"captures")
            result = read_json(folder/"extracted.json")
            meta = read_json(folder/"manifest.json")
            page, = result["pages"]
            opinion, = result["opinions"]
            self.assertEqual((opinion["text"], opinion["product"], opinion["rating"], opinion["purchase_verified"]),
                             ("Tekst testowej opinii.", "Produkt testowy", "1/1", None))
            self.assertEqual(page["rating_badges"][0]["count"], 9)
            self.assertEqual(preview(folder, meta, opinion["rating_evidence"])[1],
                             {"rating": "1/1", "icons": ["stars-full-star"]})
            price, = page["prices"]
            self.assertEqual(price["product"], "Produkt testowy")
            self.assertEqual(preview(folder, meta, price["evidence"])[1], "12,50 zł")
            self.assertEqual(page["cart_balances"][0]["value"]["amount"], "0,00")
            signal, = result["signals"]
            self.assertIn("o 5% w miesiąc", preview(folder, meta, signal["evidence"])[1])
            self.assertTrue(result["landing_summary"]["dialog"])

    def test_offline_rendition_keeps_sources_and_atomic_run_selection(self):
        with staging(Path(tempfile.gettempdir())) as root:
            src = root/"page.html"
            src.write_text(HTML, encoding="utf8")
            old = capture(src, root/"captures")
            m = read_json(old/"manifest.json")
            x = read_json(old/"extracted.json")
            del x["landing_analysis_version"]
            x["opinions"] = []
            write_json(old/"extracted.json", x)
            m["result"]["sha256"] = digest(old/"extracted.json")
            write_json(old/"manifest.json", m)
            db = sqlite3.connect(root/"discovery.sqlite3")
            self.addCleanup(db.close)
            db.executescript(SCHEMA)
            db.execute("insert into runs(run_id,source_id,trigger,mode,started,deadline,status) values('r','a','cli','live',1,2,'success')")
            sql = """insert into observations(run_id,source_id,mode,provider,ad_ref,phrase,country,reason,card,
                     capture_id,found_at,locator,missing) values('r','a','live','p','1',?,'PL','x','{}',?,1,'x',0)"""
            db.executemany(sql, [("a",old.name),("a","missing"),("b",old.name)])
            db.commit()
            cfg = {"state_dir": root}
            with patch("socket.socket", side_effect=AssertionError("network")):
                with self.assertRaises(FileNotFoundError):
                    reanalyze_run(cfg, "r", "a")
                self.assertEqual(db.execute("select capture_id from observations order by seq limit 1").fetchone()[0],old.name)
                db.execute("delete from observations where capture_id='missing'")
                db.commit()
                new_id = reanalyze_run(cfg, "r", "a")[old.name]
                self.assertEqual(reanalyze_run(cfg, "r", "a"), {new_id:new_id})
            folder = old.parent/new_id
            meta = read_json(folder/"manifest.json")
            verified(old, m)
            verified(folder, meta)
            self.assertEqual(meta["observation_id"], m["observation_id"])
            self.assertEqual(meta["artifacts"], m["artifacts"])
            self.assertEqual(db.execute("select capture_id from observations where phrase='b'").fetchone()[0],old.name)
            db.close()
