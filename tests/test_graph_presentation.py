"""Regression for page navigation flooding a graph node's hover tooltip."""
import unittest

from graph.ftf_graph.card import parse_card
from graph.ftf_graph.presentation import card_tooltip


class GraphPresentationTests(unittest.TestCase):
    def test_page_tooltip_uses_content_and_keeps_source_unchanged(self):
        raw = {
            "ad_id": "page:fixture", "provenance": {"record_kind": "page_capture",
                "fetched_at": "2026-11-22T10:00:00Z"},
            "infra": {"final_domain": "own.example"},
            "text": {"ad_text": "Home\nLogin\n" + "Language\n" * 1000},
            "extensions": {"page_observation": {"pages": [{
                "titles": [{"value": "Own offer A & B <img src=x onerror=alert(1)>"}],
                "reading_text": [{"section": "interface", "value": "Home Login Language"},
                                 {"section": "content", "value": "Useful offer " * 1000}]}]}}}
        card = parse_card(raw, trusted=frozenset())
        tooltip = card_tooltip(card, "bez kampanii")
        self.assertIn("Own offer", tooltip)
        self.assertIn("Useful offer", tooltip)
        self.assertIn("domena: own.example", tooltip)
        self.assertIn("sygnały:", tooltip)
        self.assertIn("pozyskano:", tooltip)
        self.assertNotIn("Language", tooltip)
        self.assertIn("A & B <img", tooltip)
        self.assertNotIn("&amp;", tooltip)
        self.assertLess(len(tooltip), 600)
        self.assertTrue(all(len(line) <= 64 for line in tooltip.splitlines()))
        self.assertEqual(card.ad_text, raw["text"]["ad_text"])

    def test_old_page_without_reading_text_uses_heading_instead_of_menu(self):
        card = parse_card({"ad_id": "page:old", "provenance": {"record_kind": "page_capture"},
                           "text": {"ad_text": "Home\nLogin\nLanguage\n" * 1000},
                           "extensions": {"page_observation": {"pages": [{
                               "headings": [{"value": "Offer heading"}]}]}}}, trusted=frozenset())
        tooltip = card_tooltip(card, "bez kampanii")
        self.assertIn("Offer heading", tooltip)
        self.assertNotIn("Language", tooltip)

    def test_ad_summary_preserves_short_text_and_bounds_long_text(self):
        raw = {"ad_id": "C03", "text": {"ad_text": "Bot AI zarabia 800 zł dziennie"},
               "infra": {"final_domain": "krypto-bot.test"},
               "status": "alive", "first_seen": "2026-11-13T10:00:00Z"}
        tooltip = card_tooltip(parse_card(raw, trusted=frozenset()), "CMP-3")
        self.assertIn(raw["text"]["ad_text"], tooltip)
        self.assertIn("status: alive   od 2026-11-13", tooltip)
        raw["text"]["ad_text"] = "OneLine" * 10000
        self.assertLess(len(card_tooltip(parse_card(raw, trusted=frozenset()), "CMP-3")), 400)
