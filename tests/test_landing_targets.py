import io
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote
import wave

from PIL import Image
from urllib3.exceptions import ReadTimeoutError

from scamgraph.capture import read_json, staging
from scamgraph.discovery.cta import HIDDEN_REASON, caption_url, card_cta
from scamgraph.discovery.landing_visit import gather
from scamgraph.landing import Document


WEB = "https://shop.example/diet"
FB = "https://www.facebook.com"


def response(body, mime="text/html", status=200):
    return status, mime, body, None, {}


class LandingTargets(unittest.TestCase):
    def setUp(self):
        context = staging(Path(tempfile.gettempdir()))
        self.root = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)

    def gather(self, name, url, *replies):
        folder = self.root / name
        with patch("scamgraph.discovery.landing_fetch.read_public", side_effect=replies) as http, patch(
                "scamgraph.discovery.landing_visit.render", side_effect=RuntimeError("Chrome unavailable")) as render:
            result = gather(folder, url)
        return result, folder, http, render

    def test_unlabelled_preview_and_ambiguous_targets(self):
        web = "https://shop.example.com/diet"
        preview = f'<a href="{FB}/l.php?u={quote(web, safe="")}"><img alt="Offer"></a>'
        nav = '<nav><a href="https://other.example"><img alt="Profile"></a></nav>'
        result = card_cta(Document(preview + nav).root)
        self.assertEqual(result["cta_basis"], "preview")
        self.assertEqual(result["landing_candidates"], [{"url": web, "kind": "web", "element": 1, "attribute": "href"}])
        result = card_cta(Document(preview + '<a href="https://example.org/another">Link</a>').root)
        self.assertNotIn("cta_element", result)
        self.assertEqual(len(result["landing_candidates"]), 2)
        result = card_cta(Document(preview + f'<a href="{web}/other">Link</a>').root)
        self.assertEqual((result["cta_basis"], result["cta_element"]), ("dominant_domain", 1))
        self.assertEqual(card_cta(Document(f'<footer><a href="{WEB}">Kup teraz</a></footer>').root)["cta_basis"], "label")
        self.assertNotIn("cta_element", card_cta(Document(f'<a href="{WEB}"><img alt="Logotyp profilu"></a>').root))

    def test_meta_hidden_target_and_information_links_are_not_destinations(self):
        hidden = "https://l.facebook.com/l.php?u=http%3A%2F%2Ffb.me%2F&h=AU"
        policy = "https://l.facebook.com/l.php?u=https%3A%2F%2Ftransparency.meta.com%2Fpolicies%2Fad-standards%2F"
        result = card_cta(Document(f'<div><a href="{hidden}"><div role="button">Learn More</div></a></div>').root)
        self.assertNotIn("cta_element", result)
        self.assertEqual(result["landing_candidates"], [])
        self.assertEqual(result["cta"], "Learn More")
        self.assertIn("fb.me", result["landing_missing_reason"])
        preview = card_cta(Document(f'<a href="{hidden}"><img alt="Oferta"></a>').root)
        self.assertEqual((preview["landing_candidates"], "cta_element" in preview), ([], False))
        self.assertIn("fb.me", preview["landing_missing_reason"])
        # Prawdziwy adres obok zaślepki pozostaje celem.
        mixed = card_cta(Document(f'<a href="{hidden}"><img alt="Oferta"></a><a href="{WEB}">Kup teraz</a>').root)
        self.assertEqual((mixed["cta_basis"], mixed["landing_candidates"][0]["url"]), ("label", WEB))
        # Przycisk z zaślepką i adres w treści: adres zostaje celem wybranym regułą.
        text = card_cta(Document(f'<p><a href="{WEB}">shop.example</a></p><a href="{hidden}"><span>Learn More</span></a>').root)
        self.assertEqual((text["cta_basis"], text["cta_element"]), ("single_link", 2))
        self.assertEqual([c["url"] for c in text["landing_candidates"]], [WEB])
        # auto_target=false: dawne zachowanie i dawny powód.
        manual = card_cta(Document(f'<p><a href="{WEB}">shop.example</a></p><a href="{hidden}"><span>Learn More</span></a>').root,
                          auto=False)
        self.assertNotIn("cta_element", manual)
        self.assertEqual((manual["cta"], manual["landing_missing_reason"]), ("Learn More", HIDDEN_REASON))
        # fb.me ze ścieżką nie jest zaślepką.
        short = card_cta(Document('<a href="https://fb.me/abc123">Kup teraz</a>').root)
        self.assertEqual(short["cta_basis"], "label")
        self.assertEqual(card_cta(Document(f'<p><a href="{policy}">Standardy</a></p>').root)["landing_candidates"], [])

    def test_rule_based_targets(self):
        hidden = "https://l.facebook.com/l.php?u=http%3A%2F%2Ffb.me%2F&h=AU"
        # Jedyny odnośnik do strony; profil platformy i kanał kontaktu nie są celem.
        one = card_cta(Document(f'<p>Oferta</p><a href="{WEB}">Sklep</a><a href="https://wa.me/48500">WhatsApp</a>'
                                '<a href="https://www.instagram.com/shop">IG</a>').root)
        self.assertEqual((one["cta_basis"], one["cta"], one["cta_element"]), ("single_link", "Jedyny odnośnik na karcie", 2))
        self.assertNotIn("cta_element", card_cta(Document('<a href="https://wa.me/48500">WhatsApp</a>').root))
        # Podpis domeny przy zaślepce fb.me jest celem; dowodem jest tekst elementu karty.
        caption = card_cta(Document(f'<a href="{hidden}"><div>INWESTYCJA.Example.PL/oferta</div>'
                                    '<div role="button">Learn More</div></a>').root)
        self.assertEqual((caption["cta_basis"], caption["cta_attribute"], caption["cta"]), ("caption", "text", "Learn More"))
        self.assertEqual(caption["cta_caption"], "INWESTYCJA.Example.PL/oferta")
        self.assertEqual(caption_url(caption["cta_caption"]), "https://inwestycja.example.pl/oferta")
        for text in ("FB.ME", "FB.COM", "photo.jpg", "0:00 / 0:00", "facebook.com", "Kup teraz!", "instagram.com/shop",
                     "Dr.Oetker", "Kup.Teraz", "Jan.Kowalski", "PLAY.GOOGLE.COM", "youtu.be/abc", "github.io"):
            self.assertIsNone(caption_url(text), text)
        # Podpis wskazuje jeden z kilku różnych celów.
        many = card_cta(Document('<a href="https://a.example/x">A</a><a href="https://shop-b.pl/y">B</a>'
                                 '<span>SHOP-B.PL</span>').root)
        self.assertEqual((many["cta_basis"], many["cta_element"]), ("caption", 2))
        # Kilka różnych domen bez podpisu: brak zgadywania.
        self.assertNotIn("cta_element", card_cta(Document('<a href="https://a.example/x">A</a>'
                                                          '<a href="https://b.example/y">B</a>').root))

    def test_rule_based_target_regressions(self):
        # Regresja z bench-500: link w treści reklamy, którego tekstem jest adres (youtu.be), nie jest podpisem.
        body = card_cta(Document('<p>Zobacz film: <a href="https://l.facebook.com/l.php?u=https%3A%2F%2Fyoutu.be%2Fx">'
                                 'youtu.be/x</a></p><a href="https://shop.pl/"><img alt=""></a>'
                                 '<a href="https://other.pl/">Inny</a>').root)
        self.assertNotIn("cta_caption", body)
        self.assertNotIn("cta_element", body)
        # Nazwa strony prowadząca do profilu FB nie jest podpisem domeny.
        page = card_cta(Document('<a href="https://www.facebook.com/oliviahome/">OliviaHome.com</a>'
                                 '<a href="https://l.facebook.com/l.php?u=http%3A%2F%2Ffb.me%2F">Learn More</a>').root)
        self.assertNotIn("cta_element", page)
        self.assertNotIn("cta_caption", page)
        # Regresja z bench-500: nazwa strony w role=button wewnątrz linku do profilu FB.
        nested = card_cta(Document('<a href="https://www.facebook.com/247379405663467"><div role="button">'
                                   '<span>SugarCubes.pl</span></div></a>').root)
        self.assertNotIn("cta_caption", nested)
        # Podpis w stopce podglądu prowadzącej do prawdziwego celu pozostaje podpisem.
        footer = card_cta(Document('<a href="https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.shop.pl%2F"><div role="button">'
                                   '<div>WWW.SHOP.PL</div></div><div role="button">Kup teraz</div></a>').root)
        self.assertEqual((footer["cta_caption"], footer["cta_basis"]), ("WWW.SHOP.PL", "label"))
        # Hosting wielu najemców i skracacze: wspólny host nie oznacza wspólnego reklamodawcy.
        for first, second in (("https://foo.github.io/a", "https://bar.github.io/b"),
                              ("https://bit.ly/a", "https://bit.ly/b")):
            mixed = card_cta(Document(f'<a href="{first}">A</a><a href="{second}">B</a>').root)
            self.assertNotIn("cta_element", mixed, first)
        same = card_cta(Document('<a href="https://foo.github.io/a">A</a><a href="https://foo.github.io/b">B</a>').root)
        self.assertEqual(same["cta_basis"], "dominant_domain")

    def test_polish_meta_button_labels(self):
        for label in ("Więcej informacji", "Zapisz się", "Wyślij wiadomość", "Uzyskaj ofertę", "Zainstaluj teraz"):
            result = card_cta(Document(f'<a href="{WEB}"><span>{label}</span></a><a href="https://other.example">x</a>').root)
            self.assertEqual((result.get("cta_basis"), result.get("cta")), ("label", label))

    def test_document_attempts_and_preservation_before_chrome(self):
        body = b"<main><p>Da sie odczytac opis oferty.</p></main>"
        for i, failure in enumerate((ReadTimeoutError(None, WEB, "timeout"), response(b"busy", status=503))):
            with self.subTest(failure=failure):
                result, folder, http, render = self.gather(f"retry-{i}", WEB, failure, response(body))
                self.assertEqual((result["content_status"], result["document_attempts"], result["document_entry"]), ("usable", 2, 1))
                self.assertEqual(http.call_count, 2)
                self.assertEqual(http.call_args.args[1], 8 * 1024 * 1024)
                self.assertEqual(render.call_count, 1)
                self.assertEqual((folder / "original/response.html").read_bytes(), body)
                self.assertEqual(len(read_json(folder / "network.har")["log"]["entries"]), 2)

    def test_missing_domain_is_unavailable_not_worker_error(self):
        with patch("scamgraph.discovery.landing_visit.resolver_works", return_value=True):
            dead, *_ = self.gather("nxdomain", WEB, socket.gaierror(socket.EAI_NONAME, "not known"))
            redirect = (302, "text/plain", b"", "https://gone.example/x", {})
            moved, *_ = self.gather("nxdomain-redirect", WEB, redirect, socket.gaierror(socket.EAI_NONAME, "not known"))
        self.assertEqual((dead["content_status"], dead["reason_code"]), ("unavailable", "dead_domain"))
        self.assertEqual(dead["reason"], "Domena celu nie istnieje w DNS (shop.example).")
        self.assertEqual(moved["reason"], "Domena przekierowania nie istnieje w DNS (gone.example).")
        # Bez działającego resolvera (np. brak sieci) NXDOMAIN nie jest dowodem martwej domeny.
        with patch("scamgraph.discovery.landing_visit.resolver_works", return_value=False):
            offline, *_ = self.gather("offline", WEB, socket.gaierror(socket.EAI_NONAME, "not known"))
        self.assertEqual(offline["reason_code"], "worker_error")
        self.assertNotIn("Nie ukończono renderowania (gaierror).", dead["issues"])
        # Przejściowy błąd resolvera nie jest dowodem martwej domeny.
        with patch("scamgraph.discovery.landing_visit.resolver_works", side_effect=AssertionError("no probe")):
            transient, *_ = self.gather("eai-again", WEB, socket.gaierror(socket.EAI_AGAIN, "try again"))
        self.assertEqual((transient["content_status"], transient["reason_code"]), ("error", "worker_error"))

    def test_access_screens_and_refusal(self):
        for code in (200, 403):
            result, folder, http, render = self.gather(str(code), WEB, response(b"<h1>Access denied</h1>", status=code))
            self.assertEqual(result["content_status"], "blocked")
            self.assertTrue((folder / "original/response.html").is_file())
            self.assertEqual(http.call_count, 1)
            self.assertTrue(render.call_args.kwargs["document_only"])
        for name, body, reason in (
            ("cookie", b'<main><div role="dialog"><p>We use cookies and other tracking technologies.</p></div></main>', "content_missing"),
            ("gateway", b"<title>Bad Gateway</title><main><p>The upstream server failed.</p></main>", "error_screen"),
        ):
            result, *_ = self.gather(name, WEB, response(body))
            self.assertEqual(result["reason_code"], reason)
        target = FB + "/marketplace/item/123"
        redirect = (302, "text/plain", b"", FB + "/unsupportedbrowser", {})
        state, _, http, render = self.gather("facebook-client", target, redirect, response(b"<title>Update your browser</title>"))
        self.assertEqual((state["target_kind"], state["content_status"], state["reason_code"]),
                         ("facebook_marketplace", "blocked", "client_unsupported"))
        self.assertEqual(http.call_count, 2)
        self.assertTrue(render.call_args.kwargs["document_only"])

    def test_native_objects_require_matching_identity_and_content(self):
        for path, expected in (("/marketplace/item/123", "facebook_marketplace"),
                               ("/seller/posts/123", "facebook_post"), ("/watch/?v=123", "facebook_video")):
            target = FB + path
            card = card_cta(Document(f'<a href="{target}">Watch more</a>').root)
            self.assertEqual(card["landing_candidates"][0]["kind"], expected)
            body = (f'<link rel="canonical" href="{target}">'
                    '<meta property="og:description" content="Offer at https://store.example/item?token=private">')
            saved, *_ = self.gather(expected, target, response(body.encode()))
            self.assertEqual((saved["target_kind"], saved["content_status"]), (expected, "usable"))
            self.assertTrue(saved["content_evidence"]["identity_element"])
            self.assertNotIn("private", saved["content_evidence"]["text"])
            conflict = body + f'<meta property="og:url" content="{target.replace("123", "456")}">'
            mismatch, *_ = self.gather(expected + "-mismatch", target, response(conflict.encode()))
            self.assertEqual(mismatch["reason_code"], "target_mismatch")
        target = FB + "/marketplace/item/123"
        base = '<link rel="canonical" href="/marketplace/item/123">'
        generic = base + '<meta property="og:title" content="Facebook | Facebook"><meta property="og:description" content="See posts, photos and more on Facebook.">'
        shell, *_ = self.gather("facebook-shell", target, response(generic.encode()))
        self.assertEqual(shell["reason_code"], "unverified_facebook_object")
        empty, *_ = self.gather("facebook-empty-id", target, response(b'<link rel="canonical" href="#"><h1>Tytul ogloszenia</h1>'))
        self.assertEqual(empty["reason_code"], "unverified_facebook_object")
        post, *_ = self.gather("facebook-visible", target, response((base + '<article><p>Description of the listed item.</p></article>').encode()))
        self.assertEqual(post["content_status"], "usable")
        for name, message, reason in (("missing", "This content isn't available right now.", "unavailable_screen"),
                                      ("failure", "Something went wrong while loading this content.", "error_screen")):
            state, *_ = self.gather("facebook-" + name, target, response((base + f"<article><p>{message}</p></article>").encode()))
            self.assertEqual(state["reason_code"], reason)

    def test_direct_files_and_incomplete_downloads(self):
        png, pdf, wav = io.BytesIO(), io.BytesIO(), io.BytesIO()
        image = Image.new("RGB", (1, 1))
        image.save(png, "PNG")
        image.save(pdf, "PDF")
        with wave.open(wav, "wb") as stream:
            stream.setparams((1, 1, 8000, 0, "NONE", "not compressed"))
            stream.writeframes(b"\x80" * 16)
        def box(kind, payload):
            return (8 + len(payload)).to_bytes(4, "big") + kind + payload

        sample = png.getvalue()
        entries = box(b"stsd", bytes(4) + bytes.fromhex("00000001") + box(b"png ", bytes(80)))
        sizes = box(b"stsz", bytes(4) + len(sample).to_bytes(4, "big") + bytes.fromhex("00000001"))
        media = box(b"hdlr", bytes(8) + b"vide" + bytes(12)) + box(b"minf", box(b"stbl", entries + sizes))
        movie = box(b"moov", box(b"trak", box(b"mdia", media)))
        mp4 = box(b"ftyp", b"isom" + bytes(4) + b"isom") + movie + box(b"mdat", sample)
        for kind, ext, mime, body in (("pdf", "pdf", "application/pdf", pdf.getvalue()),
                                     ("image", "png", "image/png", png.getvalue()),
                                     ("audio", "wav", "audio/wav", wav.getvalue()),
                                     ("video", "mp4", "video/mp4", mp4)):
            url = WEB + "." + ext
            result, folder, _, render = self.gather(kind, url, response(body, mime))
            render.assert_not_called()
            self.assertEqual((result["target_kind"], result["content_status"]), (kind, "usable"))
            self.assertEqual((folder / f"original/response.{ext}").read_bytes(), body)
            invalid, *_ = self.gather(kind + "-invalid", url, response(b"<html>invalid file</html>", mime))
            self.assertEqual(invalid["reason_code"], "invalid_file")
            partial, *_ = self.gather(kind + "-partial", url, response(body, mime, 206))
            self.assertEqual(partial["reason_code"], "incomplete_response")
        redirect = (302, "text/plain", b"", WEB + ".pdf", {})
        result, *_ = self.gather("unknown-url", WEB, redirect, response(pdf.getvalue(), "application/octet-stream"))
        self.assertEqual((result["target_kind"], result["content_status"]), ("pdf", "usable"))
        for ext, mime, body in (("pdf", "application/pdf", b"%PDF-1.4\n%%EOF\n"),
                                ("mp4", "video/mp4", b"\0\0\0\x10ftypisomvide")):
            result, *_ = self.gather(ext + "-truncated", WEB + "." + ext, response(body, mime))
            self.assertEqual(result["reason_code"], "invalid_file")
