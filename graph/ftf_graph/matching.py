"""Build the reference once and compare uploads against its existing campaigns."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, fields
from functools import lru_cache
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from platform import python_version

import numpy as np

from .card import Card
from .cluster import ClusterResult, cluster
from .report import Campaign, summarize
from .scoring import ENGINE_VERSION, Config, Edge, Scorer

_FAMILIES = ("domeny", "infrastruktura", "śledzenie/skrypty", "kontakty", "tekst", "wygląd", "twarze", "audio")
_MATERIAL = {"phash", "image_ocr", "visual", "text", "face", "voice", "audio_fp", "audio_fp_sim", "audio_text",
             "transcript"}


def config_json(config: Config) -> dict:
    content = asdict(config)
    content["identity_kinds"] = sorted(config.identity_kinds)
    return content


@dataclass(frozen=True)
class MatchResult:
    query_id: str
    reference_fingerprint: str
    data_fingerprint: str
    config: dict
    clustering_backend: str
    status: str
    campaign_id: str | None
    strength: float
    edges: list[Edge]
    exact_copies: list[int]
    candidate_campaigns: list[str]
    comparable: list[str]
    missing: list[str]
    warnings: list[str]
    similar_materials: list[int]
    supporting_edges: list[Edge]


@dataclass(frozen=True)
class Reference:
    cards: list[Card]
    scorer: Scorer
    scores: np.ndarray
    campaign_scores: np.ndarray
    edges: list[Edge]
    clusters: ClusterResult
    campaigns: list[Campaign]
    label_to_id: dict[int, str]
    fingerprint: str
    data_fingerprint: str
    min_cluster_size: int

    @property
    def config(self) -> dict:
        return _run_config(self.scorer.cfg, self.min_cluster_size, self.clusters.backend)

    def match(self, card: Card) -> MatchResult:
        edges, comparable, warnings = self.scorer.score_query(card)
        exact_copies = sorted((i for i, ref in enumerate(self.cards)
                               if card.image_sha256 and card.image_sha256 == ref.image_sha256),
                              key=lambda i: self.cards[i].id)
        display = [edge for edge in edges if edge.score >= self.scorer.cfg.min_edge]
        by_member = {edge.b: edge for edge in edges}
        eligible = []
        support = []
        candidates: dict[str, None] = {}
        for campaign in self.campaigns:
            member_edges = [by_member.get(i) for i in campaign.members]
            if all(edge and edge.campaign_score > 0 and edge.campaign_score >= self.scorer.cfg.min_campaign
                   for edge in member_edges):
                actual = [edge for edge in member_edges if edge is not None]
                eligible.append((campaign.id, min(edge.campaign_score for edge in actual)))
                support.extend(actual)
        for cid, _ in sorted(eligible, key=lambda item: (-item[1], item[0])):
            candidates[cid] = None
        for edge in display:
            if cid := self.label_to_id.get(int(self.clusters.labels[edge.b])):
                candidates[cid] = None
        campaign_id, strength = None, 0.
        if not comparable:
            status = "insufficient_evidence"
        elif len(eligible) == 1:
            status = "probable_match"
            campaign_id, strength = eligible[0]
        elif display or eligible or exact_copies:
            status = "review_needed"
        else:
            status = "no_match"

        present = set(card.signals())
        missing = [f"{family}: {'brak zgodnego pola w referencji' if family in present else 'brak użytecznej obserwacji'}"
                   for family in _FAMILIES if family not in comparable]
        if not self.cards:
            missing.insert(0, "Referencja jest pusta.")
        exact_members = set(exact_copies)
        similar = [edge.b for edge in display if edge.b not in exact_members
                   and any(r.kind in _MATERIAL for r in edge.observations)]
        return MatchResult(card.id, self.fingerprint, self.data_fingerprint, self.config, self.clusters.backend, status, campaign_id,
                           strength, display, exact_copies, list(candidates), sorted(comparable), missing, warnings,
                           similar, support)


def _hash_json(payload) -> str:
    def encode(value):
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return asdict(value)

    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=encode)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _data_fingerprint(cards: list[Card]) -> str:
    # Hash comparison inputs including the effective domain policy result, but
    # exclude raw extraction timestamps and incidental diagnostic messages.
    payload = []
    for card in sorted(cards, key=lambda item: item.id):
        row = {field.name: getattr(card, field.name) for field in fields(card)
               if field.name not in {"artifact_fields", "raw", "warnings"}}
        row["artifact_fields"] = {artifact.key: field for artifact, field in card.artifact_fields.items()}
        row["record_kind"] = card.record_kind
        payload.append(row)
    return _hash_json(payload)


@lru_cache(maxsize=1)
def _dependencies() -> tuple[tuple[str, str], ...]:
    versions = [("python", python_version())]
    for name in ("numpy", "scipy", "scikit-learn", "idna", "publicsuffixlist"):
        try:
            installed = version(name)
        except PackageNotFoundError:
            installed = "unavailable"
        versions.append((name, installed))
    return tuple(versions)


def _run_config(config: Config, min_cluster_size: int, backend: str) -> dict:
    return {**config_json(config), "min_cluster_size": min_cluster_size, "engine": ENGINE_VERSION,
            "clustering_backend": backend, "runtime": dict(_dependencies())}


def build_reference(cards: list[Card], config: Config | None = None, *, min_cluster_size: int = 3,
                    min_samples: int = 2) -> Reference:
    cards = deepcopy(cards)
    scorer = Scorer(cards, deepcopy(config), legacy_queries=False)
    if not 0 <= scorer.cfg.min_edge <= 1:
        raise ValueError("Próg krawędzi musi należeć do przedziału 0–1.")
    scores, campaign_scores, edges = scorer.score_reference()
    result = cluster(campaign_scores, min_cluster_size, min_samples, min_link=scorer.cfg.min_campaign,
                     ids=[c.id for c in cards])
    campaigns, label_to_id = summarize(cards, scores, result, scorer)
    for matrix in (scores, campaign_scores, result.labels, result.strength):
        matrix.setflags(write=False)
    data_fingerprint = _data_fingerprint(cards)
    fingerprint = _hash_json([data_fingerprint, _run_config(scorer.cfg, min_cluster_size, result.backend)])
    return Reference(cards, scorer, scores, campaign_scores, edges, result, campaigns, label_to_id,
                     fingerprint, data_fingerprint, min_cluster_size)
