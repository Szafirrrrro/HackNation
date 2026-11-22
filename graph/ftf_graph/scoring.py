"""Evidence-based pair scores using frequencies fitted on the reference set."""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

import numpy as np

from .card import Artifact, Card, FeatureSource

ENGINE_VERSION = "reference-match/v1"

KIND_LABEL_PL = {
    "tracking_id": "wspólny identyfikator śledzący (piksel/GA)",
    "form_endpoint": "formularz wysyła dane pod ten sam adres",
    "crypto": "ten sam adres krypto",
    "phone": "ten sam numer telefonu",
    "telegram": "ten sam kontakt Telegram",
    "cert": "wspólny certyfikat TLS",
    "domain_final": "ta sama strona docelowa",
    "domain_hop": "wspólna domena w łańcuchu przekierowań",
    "hidden_text": "ten sam ukryty tekst na stronie",
    "favicon": "ta sama favicona",
    "template": "ten sam szablon strony (DOM)",
    "script": "ten sam skrypt",
    "ip": "ten sam serwer (IP)",
    "nameserver": "ten sam serwer nazw",
    "keyword": "wspólne słowo kluczowe",
    "asn": "ta sama sieć (ASN)",
    "registrar": "ten sam rejestrator",
    "audio_fp": "identyczne nagranie audio (odcisk)",
    "transcript": "identyczny tekst lektora",
}

# Kilka śladów z jednej grupy to JEDEN dowód (np. 3 domeny z tego samego łańcucha).
# "text" łączy narrację z tekstu reklamy i z lektora (to ta sama informacja: o czym mówi reklama).
GROUP = {"domain_hop": "domain", "domain_final": "domain",
         "phone": "contact", "telegram": "contact", "crypto": "contact",
         "transcript": "text", "audio_text": "text", "image_ocr": "text", "page_text": "text",
         "template": "template", "template_sim": "template"}


@dataclass
class Config:
    # Bazowa siła wspólnego artefaktu danego rodzaju (zanim uwzględnimy rzadkość).
    base: dict[str, float] = field(default_factory=lambda: {
        "tracking_id": 0.90, "form_endpoint": 0.90, "crypto": 0.90,
        "phone": 0.85, "telegram": 0.85, "cert": 0.80,
        "domain_final": 0.75, "hidden_text": 0.70, "domain_hop": 0.65,
        "favicon": 0.60, "template": 0.60, "script": 0.60,
        "ip": 0.40, "nameserver": 0.30, "keyword": 0.15,
        "asn": 0.10, "registrar": 0.05,
        "audio_fp": 0.85,    # to samo nagranie (ten sam plik lektora/muzyki)
        "transcript": 0.55,  # słowo w słowo ten sam skrypt lektora
        "person": 0.0,  # osoba łączy się MIĘKKO przez embedding twarzy (z wagą jakości)
    })
    max_df_frac: float = 0.30  # artefakt w >30% reklam to "hub" (Cloudflare, Google Fonts) -> ignoruj
    # Ślady tożsamościowe należą do jednego operatora bez względu na to, w ilu reklamach występują:
    # nie podlegają karze za popularność ani progowi huba (rzadkość = 1, gdy df >= 2).
    identity_kinds: frozenset[str] = frozenset(
        {"tracking_id", "form_endpoint", "phone", "telegram", "crypto", "audio_fp"})

    # ramp(x, lo, hi) = 0 poniżej lo, 1 powyżej hi, liniowo pomiędzy
    w_text: float = 0.60; text_lo: float = 0.75; text_hi: float = 0.95
    w_visual: float = 0.50; vis_lo: float = 0.80; vis_hi: float = 0.97
    w_phash: float = 0.60; phash_good: int = 4; phash_bad: int = 12     # bity różnicy z 64
    w_face: float = 0.50; face_lo: float = 0.45; face_hi: float = 0.85  # × min(jakość) -> twarz sama ≤ 0.5
    w_regburst: float = 0.50; regburst_window_h: float = 2.0            # hurtowa rejestracja domen
    # podobny szablon strony: szacowany Jaccard z sygnatur MinHash (odsetek zgodnych pozycji)
    w_template_sim: float = 0.55; tmpl_lo: float = 0.50; tmpl_hi: float = 0.90
    # audio
    w_audio_text: float = 0.60                                           # progi jak dla tekstu (text_lo/hi)
    w_voice: float = 0.45; voice_lo: float = 0.55; voice_hi: float = 0.80  # głos sam ≤ 0.45 (klony głosu celebrytów)
    w_audio_fp: float = 0.80; fp_lo: float = 0.65; fp_hi: float = 0.85     # 1 - odsetek różnych bitów odcisku
    fp_max_shift: int = 8                                                # przesunięcie odcisków (w ramkach)

    min_edge: float = 0.25  # próg krawędzi do prezentacji
    min_campaign: float = 0.65  # próg wszystkich par w kampanii


@dataclass
class Reason:
    group: str
    kind: str
    hard: bool
    strength: float
    detail: str
    field_a: str = ""
    field_b: str = ""
    origin_a: str = ""
    origin_b: str = ""
    method_a: str = ""
    method_b: str = ""
    source_ref_a: Any = None
    source_ref_b: Any = None
    method: str = ""
    metric: str = ""
    value: float | None = None
    threshold: float | None = None


@dataclass
class Edge:
    a: int
    b: int
    score: float
    reasons: list[Reason]  # malejąco wg siły
    campaign_score: float = 0.0
    campaign_reasons: list[Reason] = field(default_factory=list)
    observations: list[Reason] = field(default_factory=list)

    @property
    def has_hard(self) -> bool:
        return any(r.hard for r in self.reasons)


def ramp(x: float, lo: float, hi: float) -> float:
    return max(0., min(1., (x - lo) / (hi - lo)))


_POPCOUNT8 = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)


def fingerprint_similarity(a: np.ndarray, b: np.ndarray, max_shift: int) -> float:
    """Podobieństwo odcisków audio (uint32 na ramkę, jak Chromaprint): 1 - odsetek różnych bitów,
    najlepsze z przesunięć o -max_shift..max_shift ramek (nagranie mogło zacząć się chwilę później)."""
    best_ber = 1.0
    min_overlap = max(1, min(len(a), len(b)) // 2)
    for off in range(-max_shift, max_shift + 1):
        x, y = (a[off:], b) if off >= 0 else (a, b[-off:])
        n = min(len(x), len(y))
        if n < min_overlap:
            continue
        diff = _POPCOUNT8[(x[:n] ^ y[:n]).view(np.uint8)].sum()
        best_ber = min(best_ber, float(diff) / (32 * n))
    return 1.0 - best_ber


# Field names retain the source locators expected by feature adapters.
_VECTOR_RULES = (
    ("text.embedding", "text_emb", "text", "tekst", "w_text", "text_lo", "text_hi", "tekst reklamy"),
    ("visual.clip_embedding", "clip_emb", "visual", "wygląd", "w_visual", "vis_lo", "vis_hi", "wygląd reklamy (CLIP)"),
    ("audio.text_embedding", "audio_text_emb", "audio_text", "audio", "w_audio_text", "text_lo", "text_hi",
     "narracja lektora"),
    ("audio.speaker_embedding", "speaker_emb", "voice", "audio", "w_voice", "voice_lo", "voice_hi", "głos lektora"),
    ("page.text.embedding", "page_text_emb", "page_text", "tekst", "w_text", "text_lo", "text_hi", "tekst strony"),
)

_COPY_SIGNALS = {"image_sha256", "audio_fp", "audio_fp_sim"}
_ARTIFACT_FAMILIES = {
    "domain_hop": "domeny", "domain_final": "domeny",
    "ip": "infrastruktura", "cert": "infrastruktura", "nameserver": "infrastruktura",
    "favicon": "infrastruktura", "asn": "infrastruktura", "registrar": "infrastruktura",
    "tracking_id": "śledzenie/skrypty", "script": "śledzenie/skrypty", "template": "śledzenie/skrypty",
    "form_endpoint": "śledzenie/skrypty", "hidden_text": "śledzenie/skrypty",
    "phone": "kontakty", "telegram": "kontakty", "crypto": "kontakty",
    "keyword": "tekst", "transcript": "audio", "audio_fp": "audio",
}


def _source(card: Card, name: str) -> FeatureSource:
    if name in card.feature_sources:
        return card.feature_sources[name]
    if name.startswith("faces["):
        face = card.faces[int(name.partition("[")[2].partition("]")[0])]
        if face.source.origin or face.source.method:
            return face.source
        return FeatureSource(card.image_origin or "legacy:image")
    if name.startswith("visual."):
        return FeatureSource(card.image_origin or "legacy:image")
    if name.startswith("audio.") or name in {"audio_fp", "transcript"}:
        return FeatureSource("legacy:audio")
    if name == "text.ocr_text":
        return FeatureSource(card.image_text_origin or card.image_origin or "legacy:image")
    if name.startswith("text.") or name == "keyword":
        image_present = card.image_origin or card.phash is not None or card.clip_emb or card.faces or card.image_sha256
        return FeatureSource((card.image_origin or "legacy:image") if image_present else "legacy:text")
    return FeatureSource("legacy:page")


def _normalize(vector: list[float]) -> np.ndarray | None:
    if not vector:
        return None
    value = np.asarray(vector, dtype=float)
    scale = float(np.abs(value).max())
    if not math.isfinite(scale) or not scale:
        return None
    scaled = value / scale
    return scaled / np.linalg.norm(scaled)


@dataclass
class _Prepared:
    card: Card
    by_kind: dict[str, set[Artifact]]
    vectors: dict[str, tuple[FeatureSource, np.ndarray]]
    faces: list[tuple[str, FeatureSource, np.ndarray, float]]
    fingerprint: np.ndarray
    template: np.ndarray
    ocr: Any


def _key(reason: Reason) -> tuple:
    endpoints = sorted(((reason.field_a, reason.origin_a), (reason.field_b, reason.origin_b)))
    return -reason.strength, not reason.hard, reason.kind, endpoints, reason.detail


def _independent(reasons: list[Reason]) -> list[Reason]:
    """Keep strongest reasons with distinct groups and origins on both sides."""
    used: set[tuple[str, str]] = set()
    chosen = []
    for reason in reasons:
        keys = {("group", reason.group), ("a", reason.origin_a), ("b", reason.origin_b)}
        if used.isdisjoint(keys):
            chosen.append(reason)
            used.update(keys)
    return chosen


def _score(reasons: list[Reason]) -> float:
    return 1.0 - math.prod(1.0 - r.strength for r in reasons)


class Scorer:
    def __init__(self, cards: list[Card], cfg: Config | None = None, *, legacy_queries: bool = True):
        self.cards, self.cfg = cards, cfg or Config()
        # Maintain compatibility for callers that passed legacy image uploads and references in one list.
        self.reference = [not legacy_queries or c.record_kind != "image_query" for c in cards]
        self.n = sum(self.reference)
        self.index: dict[str, list[int]] = defaultdict(list)
        for i, card in enumerate(cards):
            if self.reference[i]:
                for artifact in card.artifacts:
                    self.index[artifact.key].append(i)

        self._tfidf = None
        training = [c.image_text for c, ref in zip(cards, self.reference) if ref and c.image_text.strip()]
        if training:
            from sklearn.feature_extraction.text import TfidfVectorizer

            vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5))
            try:
                vectorizer.fit(training)
            except ValueError:  # empty vocabulary
                pass
            else:
                self._tfidf = vectorizer

        self._prepared = [self._prepare(card) for card in cards]
        self._template_refs: dict[str, list[np.ndarray]] = defaultdict(list)
        for item, ref in zip(self._prepared, self.reference):
            if ref and item.template.size:
                self._template_refs[item.card.template_minhash_scheme].append(item.template)
        self._template_hub = [self._is_template_hub(item, ref) for item, ref in zip(self._prepared, self.reference)]
        self.warnings = self._vector_warnings()

    def _prepare(self, card: Card) -> _Prepared:
        by_kind: dict[str, set[Artifact]] = defaultdict(set)
        for artifact in card.artifacts:
            by_kind[artifact.kind].add(artifact)
        vectors = {}
        for name, attr, *_ in _VECTOR_RULES:
            if (unit := _normalize(getattr(card, attr))) is not None:
                vectors[name] = (_source(card, name), unit)
        faces = []
        for index, face in enumerate(card.faces):
            if (unit := _normalize(face.embedding)) is not None:
                name = f"faces[{index}].embedding"
                faces.append((name, _source(card, name), unit, face.quality))
        ocr = self._tfidf.transform([card.image_text]) if self._tfidf is not None and card.image_text.strip() else None
        return _Prepared(card, dict(by_kind), vectors, faces, np.asarray(card.audio_fp, dtype=np.uint32),
                         np.asarray(card.template_minhash, dtype=np.uint32), ocr)

    def _vector_warnings(self) -> list[str]:
        shapes: dict[str, set[tuple[str, int]]] = defaultdict(set)
        for item, ref in zip(self._prepared, self.reference):
            if ref:
                for name, (source, vector) in item.vectors.items():
                    shapes[name].add((source.method, vector.size))
                for _, source, vector, _ in item.faces:
                    shapes["faces.embedding"].add((source.method, vector.size))
        result = []
        for name, values in sorted(shapes.items()):
            if len(values) > 1:
                schemes = ", ".join(f"{method or 'legacy'} / {size}" for method, size in sorted(values))
                result.append(f"{name}: pominięto porównania między różnymi metodami lub wymiarami ({schemes}).")
        return result

    def df(self, key: str) -> int:
        return len(self.index.get(key, ()))

    def rarity_of(self, key: str, *, query: bool = False) -> float:
        kind = key.split("|", 1)[0]
        df = self.df(key)
        if kind in self.cfg.identity_kinds:
            return 1.0 if df >= (1 if query else 2) else 0.0
        return self.rarity(df, query=query)

    def rarity(self, df: int, *, query: bool = False) -> float:
        n = self.n
        if df < (1 if query else 2) or n <= 2 or df > self.cfg.max_df_frac * n:
            return 0.0
        return min(1.0, math.log(n / df) / math.log(n / 2))

    def _is_template_hub(self, item: _Prepared, is_reference: bool) -> bool:
        if not item.template.size:
            return False
        same_scheme = self._template_refs.get(item.card.template_minhash_scheme, ())
        near = sum(np.mean(item.template == value) >= self.cfg.tmpl_hi for value in same_scheme
                   if item.template.shape == value.shape)
        return near - int(is_reference) > max(1., self.cfg.max_df_frac * self.n)

    def _pair(self, a: int, b: int, left: _Prepared, right: _Prepared, *, query: bool,
              hub_a: bool, hub_b: bool, comparable: set[str] | None = None,
              warnings: set[str] | None = None) -> Edge | None:
        cfg = self.cfg
        c, d = left.card, right.card
        reasons: list[Reason] = []

        def mark(family: str) -> None:
            if comparable is not None:
                comparable.add(family)

        def warn(name: str) -> None:
            if warnings is not None:
                warnings.add(f"{name}: pominięto niezgodne metody lub wymiary.")

        def add(kind: str, field_a: str, field_b: str, strength: float, detail: str, *,
                hard: bool = False, method: str, metric: str, value: float, threshold: float) -> None:
            if strength <= 0:
                return
            source_a = _source(c, field_a)
            source_b = _source(d, field_b)
            reasons.append(Reason(GROUP.get(kind, kind), kind, hard, min(1.0, strength), detail,
                                  field_a, field_b, source_a.origin, source_b.origin, source_a.method,
                                  source_b.method, source_a.source_ref, source_b.source_ref, method,
                                  metric, value, threshold))

        for kind in left.by_kind.keys() & right.by_kind.keys():
            if cfg.base.get(kind, .20) <= 0:
                continue
            values_a, values_b = left.by_kind[kind], right.by_kind[kind]
            common = values_a & values_b
            if kind != "audio_fp" and (values_a != values_b or any(self.rarity_of(v.key, query=query) for v in common)):
                mark(_ARTIFACT_FAMILIES.get(kind, "infrastruktura"))
            for artifact in common:
                name_a = c.artifact_fields.get(artifact, kind)
                name_b = d.artifact_fields.get(artifact, kind)
                if kind == "audio_fp" and _source(c, name_a).method != _source(d, name_b).method:
                    warn(name_a)
                    continue
                df = self.df(artifact.key)
                strength = cfg.base.get(kind, .20) * self.rarity_of(artifact.key, query=query)
                add(kind, name_a, name_b, strength,
                    f"{KIND_LABEL_PL.get(kind, kind)}: {artifact.value} (liczba kart w referencji: {df})",
                    hard=True, method="normalized-equality", metric="equality", value=1., threshold=1.)

        for name, _, kind, family, weight, lower, upper, label in _VECTOR_RULES:
            if name not in left.vectors or name not in right.vectors or getattr(cfg, weight) <= 0:
                continue
            source_a, vector_a = left.vectors[name]
            source_b, vector_b = right.vectors[name]
            if source_a.method != source_b.method or vector_a.shape != vector_b.shape:
                warn(name)
                continue
            mark(family)
            similarity = max(-1., min(1., float(vector_a @ vector_b)))
            lo, hi = getattr(cfg, lower), getattr(cfg, upper)
            if similarity > lo:
                add(kind, name, name, getattr(cfg, weight) * ramp(similarity, lo, hi),
                    f"podobieństwo: {label} (cos={similarity:.2f})", method="cosine", metric="cosine",
                    value=similarity, threshold=lo)

        if c.image_sha256 and d.image_sha256:
            mark("wygląd")
            if c.image_sha256 == d.image_sha256:
                add("image_sha256", "visual.sha256", "visual.sha256", .95,
                    f"identyczny plik obrazu (SHA-256: {c.image_sha256})", hard=True,
                    method="sha256", metric="equality", value=1., threshold=1.)

        if c.phash is not None and d.phash is not None and cfg.w_phash > 0:
            name = "visual.phash"
            if _source(c, name).method != _source(d, name).method:
                warn(name)
            else:
                mark("wygląd")
                distance = (c.phash ^ d.phash).bit_count()
                if distance < cfg.phash_bad:
                    add("phash", name, name, cfg.w_phash * (1 - ramp(distance, cfg.phash_good, cfg.phash_bad)),
                        f"podobna grafika (pHash: {distance}/64 bitów różnicy)", method="phash64", metric="hamming",
                        value=distance, threshold=cfg.phash_bad)

        if left.ocr is not None and right.ocr is not None and cfg.w_text > 0:
            # A zero transformed query can still be compared: it has no reference n-grams.
            mark("tekst")
            similarity = float(left.ocr.multiply(right.ocr).sum())
            if similarity > cfg.text_lo:
                add("image_ocr", "text.ocr_text", "text.ocr_text",
                    cfg.w_text * ramp(similarity, cfg.text_lo, cfg.text_hi),
                    f"podobny tekst obrazu (TF-IDF char_wb 3–5, cos={similarity:.2f})",
                    method="tfidf-char-wb-3-5", metric="cosine", value=similarity, threshold=cfg.text_lo)

        if left.fingerprint.size and right.fingerprint.size:
            name = "audio.fingerprint"
            if _source(c, name).method != _source(d, name).method:
                warn(name)
            else:
                mark("audio")
                if cfg.w_audio_fp > 0:
                    similarity = fingerprint_similarity(left.fingerprint, right.fingerprint, cfg.fp_max_shift)
                    if similarity > cfg.fp_lo:
                        add("audio_fp_sim", name, name, cfg.w_audio_fp * ramp(similarity, cfg.fp_lo, cfg.fp_hi),
                            f"podobne nagranie audio ({(1 - similarity) * 100:.0f}% różnych bitów odcisku)",
                            method="shifted-fingerprint", metric="bit-agreement", value=similarity, threshold=cfg.fp_lo)

        if cfg.w_face > 0:
            for name_a, source_a, vector_a, quality_a in left.faces:
                for name_b, source_b, vector_b, quality_b in right.faces:
                    if source_a.method != source_b.method or vector_a.shape != vector_b.shape:
                        warn("faces.embedding")
                        continue
                    quality = min(quality_a, quality_b)
                    if not quality:
                        continue
                    mark("twarze")
                    similarity = max(-1., min(1., float(vector_a @ vector_b)))
                    if similarity > cfg.face_lo:
                        add("face", name_a, name_b,
                            cfg.w_face * ramp(similarity, cfg.face_lo, cfg.face_hi) * quality,
                            f"podobna twarz (cos={similarity:.2f}, jakość min={quality:.2f})",
                            method="cosine", metric="cosine", value=similarity, threshold=cfg.face_lo)

        if left.template.size and right.template.size and cfg.w_template_sim > 0:
            name = "page.dom_template_minhash"
            if (c.template_minhash_scheme != d.template_minhash_scheme or left.template.shape != right.template.shape):
                warn(name)
            elif not (hub_a or hub_b):
                mark("śledzenie/skrypty")
                similarity = float(np.mean(left.template == right.template))
                if similarity > cfg.tmpl_lo:
                    add("template_sim", name, name, cfg.w_template_sim * ramp(similarity, cfg.tmpl_lo, cfg.tmpl_hi),
                        f"podobny szablon strony (MinHash, Jaccard≈{similarity:.2f})",
                        method=c.template_minhash_scheme, metric="estimated-jaccard", value=similarity,
                        threshold=cfg.tmpl_lo)

        if c.registrar and c.registrar == d.registrar and c.registered and d.registered and cfg.w_regburst > 0:
            if (c.registered.utcoffset() is None) == (d.registered.utcoffset() is None):
                name = "infra.rdap.registered"
                hours = abs((c.registered - d.registered).total_seconds()) / 3600
                mark("infrastruktura")
                if hours < cfg.regburst_window_h:
                    add("regburst", name, name, cfg.w_regburst * (1 - hours / cfg.regburst_window_h),
                        f"domeny zarejestrowane w odstępie {hours * 60:.0f} min u {c.registrar}",
                        method="same-registrar-and-time", metric="hours", value=hours, threshold=cfg.regburst_window_h)

        if not reasons:
            return None
        reasons.sort(key=_key)
        independent = _independent(reasons)
        grouping = (_independent([r for r in reasons if r.kind not in _COPY_SIGNALS])
                    if c.record_kind != "page_capture" and d.record_kind != "page_capture" else [])
        return Edge(a, b, _score(independent), independent, _score(grouping), grouping, reasons)

    def score_reference(self) -> tuple[np.ndarray, np.ndarray, list[Edge]]:
        """Return similarity scores, campaign scores and the display edges."""
        scores = np.eye(len(self.cards))
        grouping = np.eye(len(self.cards))
        edges = []
        for (a, left), (b, right) in combinations(enumerate(self._prepared), 2):
            edge = self._pair(a, b, left, right, query=not (self.reference[a] and self.reference[b]),
                              hub_a=self._template_hub[a], hub_b=self._template_hub[b])
            if edge is not None:
                scores[a, b] = scores[b, a] = edge.score
                grouping[a, b] = grouping[b, a] = edge.campaign_score
                if edge.score >= self.cfg.min_edge:
                    edges.append(edge)
        edges.sort(key=lambda e: (-e.score, *sorted((self.cards[e.a].id, self.cards[e.b].id))))
        return scores, grouping, edges

    def score_all(self) -> tuple[np.ndarray, list[Edge]]:
        """Compatibility entry point for similarity scores and display edges."""
        scores, _, edges = self.score_reference()
        return scores, edges

    def score_query(self, card: Card) -> tuple[list[Edge], set[str], list[str]]:
        """Score only pairs between an upload and the existing reference."""
        item = self._prepare(card)
        hub = self._is_template_hub(item, False)
        comparable: set[str] = set()
        warnings: set[str] = set(card.warnings)
        edges = []
        for i, prepared in enumerate(self._prepared):
            if not self.reference[i]:
                continue
            edge = self._pair(len(self.cards), i, item, prepared, query=True, hub_a=hub, hub_b=self._template_hub[i],
                              comparable=comparable, warnings=warnings)
            if edge is not None:
                edges.append(edge)
        edges.sort(key=lambda edge: (-edge.score, self.cards[edge.b].id))
        return edges, comparable, sorted(warnings)
