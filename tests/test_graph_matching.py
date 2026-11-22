import unittest
from copy import deepcopy
from unittest.mock import patch

import numpy as np

from graph.ftf_graph.card import normalize_domain, parse_card
from graph.ftf_graph.cluster import cluster
from graph.ftf_graph.matching import build_reference
from graph.ftf_graph.report import edge_json
from graph.ftf_graph.scoring import Config


def card(ad_id, *, pixel="", ga="", **fields):
    if pixel or ga:
        fields["page"] = {**fields.get("page", {}), "tracking_ids": {"meta_pixel": pixel, "ga": ga}}
    return parse_card({"ad_id": ad_id, **fields}, trusted=frozenset())


def groups(reference):
    return {c.id: [reference.cards[i].id for i in c.members] for c in reference.campaigns}


class FrozenMatchingTests(unittest.TestCase):
    def test_single_trio_needs_no_competing_cluster(self):
        rows = [card(c, pixel="one") for c in "abc"] + [card(c, pixel=c) for c in "def"]
        reference = build_reference(rows)
        self.assertEqual(groups(reference), {"CMP-1": ["a", "b", "c"]})
        self.assertEqual(groups(build_reference(list(reversed(rows)))), groups(reference))
        self.assertEqual(build_reference(list(reversed(rows))).fingerprint, reference.fingerprint)

    def test_zero_score_chain_cannot_join_campaign(self):
        rows = [card("a", pixel="p"), card("b", pixel="p", ga="q"), card("c", ga="q")]
        rows.extend(card(c, pixel="trio") for c in "def")
        reference = build_reference(rows)
        self.assertEqual(reference.scores[0, 2], 0)
        self.assertEqual(groups(reference), {"CMP-1": ["d", "e", "f"]})
        self.assertTrue(all(label < 0 for label in cluster(np.eye(5), min_link=0).labels))

    def test_query_never_scores_historical_pairs_or_changes_reference(self):
        cards = [card(c, pixel="camp" if c in "abc" else c,
                      infra={"final_domain": "rare.test" if c in "ab" else f"{c}.test"}) for c in "abcdef"]
        reference = build_reference(cards)
        before = reference.scores.copy(), reference.campaign_scores.copy(), deepcopy(reference.edges), groups(reference)
        self.assertEqual(reference.scorer.rarity_of("domain_final|rare.test"), 0)
        with patch.object(reference.scorer, "_pair", wraps=reference.scorer._pair) as pair:
            first = reference.match(card("known", pixel="camp"))
            self.assertEqual(pair.call_count, len(cards))
            self.assertTrue(all(call.kwargs["query"] for call in pair.call_args_list))
        self.assertEqual(first.status, "probable_match")
        self.assertEqual(first.campaign_id, "CMP-1")
        self.assertAlmostEqual(first.strength, .9)
        self.assertEqual(reference.match(card("unknown", pixel="unknown")).status, "no_match")
        self.assertEqual(reference.match(card("known", pixel="camp")), first)
        np.testing.assert_array_equal(reference.scores, before[0])
        np.testing.assert_array_equal(reference.campaign_scores, before[1])
        self.assertEqual((reference.edges, groups(reference)), before[2:])
        self.assertEqual(reference.scorer.df("tracking_id|camp"), 3)

    def test_coverage_partial_and_ambiguous_qualification(self):
        rows = [card(c, pixel="p") for c in "abc"] + [card(c, pixel="q") for c in "def"]
        reference = build_reference(rows)
        unknown = reference.match(card("blank", text={"ad_text": "tekst bez wektora"}))
        self.assertEqual(unknown.status, "insufficient_evidence")
        self.assertEqual(unknown.comparable, [])
        self.assertTrue(unknown.missing)
        ambiguous = reference.match(card("ambiguous", pixel="p", ga="q"))
        self.assertEqual(ambiguous.status, "review_needed")
        self.assertEqual(ambiguous.candidate_campaigns, ["CMP-1", "CMP-2"])
        self.assertIsNone(ambiguous.campaign_id)
        reference = build_reference([card("a", pixel="p"), card("b", pixel="p", ga="q"), card("c", pixel="p")])
        partial = reference.match(card("q", ga="q"))
        self.assertEqual(partial.status, "review_needed")
        self.assertEqual(partial.candidate_campaigns, ["CMP-1"])
        self.assertEqual([reference.cards[e.b].id for e in partial.edges], ["b"])

    def test_exact_file_is_independent_of_campaign_status(self):
        visual = {"sha256": "1" * 64, "phash": "1234567890abcdef", "origin_id": "same-image"}
        reference = build_reference([card(c, pixel="p", visual=visual) for c in "abc"])
        result = reference.match(card("copy", visual=visual))
        self.assertEqual(result.status, "review_needed")
        self.assertEqual(result.exact_copies, [0, 1, 2])
        self.assertTrue(all(edge.score == .95 and edge.campaign_score == .60 for edge in result.edges))
        alternative = reference.match(card("variant", visual={**visual, "sha256": "2" * 64}))
        self.assertEqual(alternative.status, "review_needed")
        self.assertEqual(alternative.exact_copies, [])
        self.assertEqual(alternative.similar_materials, [0, 1, 2])

    def test_standalone_pages_have_comparison_edges_without_campaign_membership(self):
        pages = [card(c, pixel="same", provenance={"record_kind": "page_capture"}) for c in "def"]
        reference = build_reference([card(c, pixel="same") for c in "abc"] + pages)
        self.assertEqual(groups(reference), {"CMP-1": ["a", "b", "c"]})
        self.assertGreater(reference.scores[0, 3], 0)
        self.assertEqual(reference.campaign_scores[0, 3], 0)
        query = card("page:query", pixel="same", provenance={"record_kind": "page_capture"})
        result = reference.match(query)
        self.assertEqual(result.status, "review_needed")
        self.assertEqual(result.candidate_campaigns, ["CMP-1"])
        self.assertEqual(len(result.edges), 6)

    def test_single_template_reference_can_support_review(self):
        template = {"method": "dom-v1", "k": 8, "num_perm": 4, "signature": [1, 2, 3, 4]}
        base = card("ad", page={"dom_template_minhash": template})
        query = card("page:query", page={"dom_template_minhash": template},
                     provenance={"record_kind": "page_capture"})
        match = build_reference([base]).match(query)
        self.assertEqual(match.status, "review_needed")
        self.assertEqual(match.edges[0].reasons[0].kind, "template_sim")

    def test_reference_fingerprint_uses_method_config_and_evidence(self):
        def row(extracted_at, pixels):
            return [card("a", pixel=pixels, provenance={"extracted_at": extracted_at})]

        reference = build_reference(row("2026-01-01Z", "one"))
        self.assertEqual(reference.fingerprint, build_reference(row("2026-02-01Z", "one")).fingerprint)
        edited_config = build_reference(row("2026-01-01Z", "one"), Config(min_campaign=.70))
        self.assertEqual(reference.data_fingerprint, edited_config.data_fingerprint)
        self.assertNotEqual(reference.fingerprint, edited_config.fingerprint)
        self.assertNotEqual(reference.data_fingerprint, build_reference(row("2026-01-01Z", "two")).data_fingerprint)


class PairEvidenceTests(unittest.TestCase):
    def test_one_sided_duplicate_origin_uses_only_the_strongest_observation(self):
        visual = {"phash": "c461f6dea2a035ee", "clip_embedding": [1, 0], "origin_id": "image"}
        text = {"embedding": [1, 0], "origin_id": "image", "ocr_origin_id": "image",
                "ocr_text": "Oferta materiału z identycznym długim napisem"}
        first = card("a", visual=visual, text=text)
        second = card("b", visual=visual, text={**text, "origin_id": "caption", "ocr_origin_id": "caption"})
        reference = build_reference([first, second])
        edge = reference.edges[0]
        self.assertAlmostEqual(edge.score, .60)
        self.assertCountEqual([r.kind for r in edge.observations], ["text", "image_ocr", "phash", "visual"])
        self.assertEqual(len(edge.reasons), 1)
        inverted = build_reference([second, first]).edges[0]
        self.assertAlmostEqual(edge.score, inverted.score)

    def test_page_and_image_sources_can_support_one_another(self):
        fields = {"visual": {"phash": "1234567890abcdef", "origin_id": "image",
                             "phash_method": "phash/v1"},
                  "page": {"origin_id": "page", "script_hashes": ["script"],
                           "text": {"embedding": [1, 0], "method": "hash/v1", "source_refs": ["page.html"]}}}
        first, second = (card(c, **fields) for c in "ab")
        reference = build_reference([first, second, *(card(c) for c in "12345")])
        edge = reference.edges[0]
        self.assertAlmostEqual(edge.score, .84)
        self.assertTrue({"script", "page_text"} <= {r.kind for r in edge.observations})
        self.assertEqual({r.origin_a for r in edge.reasons}, {"image", "page"})
        exported = edge_json(edge, reference.cards)
        exact = next(r for r in exported["reasons"] if r["kind"] == "script")
        self.assertEqual((exact["field_a"], exact["metric"], exact["value"]), ("page.script_hashes", "equality", 1))
        page_text = next(r for r in exported["observations"] if r["kind"] == "page_text")
        self.assertEqual(page_text["source_ref_a"], ["page.html"])
        self.assertEqual(page_text["method_a"], "hash/v1")

    def test_mixed_shapes_and_methods_preserve_compatible_comparisons(self):
        def vectors(version, data):
            return dict(text={"embedding": data, "method": version, "origin_id": "caption"},
                        visual={"clip_embedding": data, "clip_embedding_method": version},
                        audio={"speaker_embedding": data, "speaker_embedding_method": version,
                               "text_embedding": data, "text_embedding_method": version},
                        faces=[{"embedding": data, "method": version, "quality": 1}])

        same = vectors("m1", [1, 0])
        rows = [card("a", **same), card("b", **same), card("different_method", **vectors("m2", [1, 0])),
                card("different_dimension", **vectors("m1", [1, 0, 0]))]
        reference = build_reference(rows)
        self.assertEqual(len(reference.edges), 1)
        self.assertEqual({r.kind for r in reference.edges[0].observations}, {"text", "visual", "voice", "audio_text", "face"})
        self.assertEqual(len(reference.scorer.warnings), 5)
        incompatible = reference.match(card("query", **vectors("m3", [1, 0])))
        self.assertEqual(incompatible.status, "insufficient_evidence")
        self.assertEqual(len(incompatible.warnings), 5)
        broken = reference.match(card("broken", **vectors("m1", [float("nan"), 0])))
        self.assertEqual(broken.status, "insufficient_evidence")
        self.assertEqual(len(broken.warnings), 5)

    def test_visual_section_method_remains_effective_with_phash_present(self):
        fields = {"phash": "c461f6dea2a035ee", "phash_method": "phash/v1", "clip_embedding": [1, 0]}
        first = card("ref", visual={**fields, "method": "clip/v1"})
        query = card("query", visual={**fields, "method": "clip/v2"})
        result = build_reference([first]).match(query)
        self.assertEqual([reason.kind for reason in result.edges[0].observations], ["phash"])
        self.assertTrue(any("visual.clip_embedding" in warning for warning in result.warnings))

    def test_port_and_url_forms_cannot_bypass_domain_policy(self):
        entries = ["bit.ly:443", "https://WWW.BIT.LY.:8443/t?x=1", "//bit.ly:80/a"]
        self.assertEqual([normalize_domain(host) for host in entries], ["bit.ly"] * 3)
        self.assertEqual(normalize_domain("https://www.faß.example:443/"), "xn--fa-hia.example")
        rows = [card(str(i), infra={"redirect_chain": [host], "rdap": {"nameservers": [host]}})
                for i, host in enumerate(entries)]
        rows.extend(card(c, pixel="operator") for c in "abc")
        rows.extend(card(c, pixel=c) for c in "defgh")
        reference = build_reference(rows)
        self.assertEqual(groups(reference), {"CMP-1": ["a", "b", "c"]})
        for item in reference.cards[:3]:
            self.assertEqual(item.trusted_hits, ["bit.ly"])
            self.assertFalse(item.artifacts)


if __name__ == "__main__":
    unittest.main()
