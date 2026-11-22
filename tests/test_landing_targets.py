import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote
import wave

from PIL import Image
from urllib3.exceptions import ReadTimeoutError

from scamgraph.capture import read_json, staging
from scamgraph.discovery.cta import card_cta
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
        preview = f'<a href="{FB}/l.php?u={quote(WEB, safe="")}"><img alt="Offer"></a>'
        nav = '<nav><a href="https://other.example"><img alt="Profile"></a></nav>'
        result = card_cta(Document(preview + nav).root)
        self.assertEqual(result["cta_basis"], "preview")
        self.assertEqual(result["landing_candidates"], [{"url": WEB, "kind": "web", "element": 1, "attribute": "href"}])
        result = card_cta(Document(preview + '<a href="https://example.org/another">Link</a>').root)
        self.assertNotIn("cta_element", result)
        self.assertEqual(len(result["landing_candidates"]), 2)
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
        # Przycisk z zaślepką i adres w treści: adres czeka na potwierdzenie, powód wskazuje ukrycie celu.
        text = card_cta(Document(f'<p><a href="{WEB}">shop.example</a></p><a href="{hidden}"><span>Learn More</span></a>').root)
        self.assertNotIn("cta_element", text)
        self.assertEqual([c["url"] for c in text["landing_candidates"]], [WEB])
        self.assertIn("fb.me", text["landing_missing_reason"])
        # fb.me ze ścieżką nie jest zaślepką.
        short = card_cta(Document('<a href="https://fb.me/abc123">Kup teraz</a>').root)
        self.assertEqual(short["cta_basis"], "label")
        self.assertEqual(card_cta(Document(f'<p><a href="{policy}">Standardy</a></p>').root)["landing_candidates"], [])

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
