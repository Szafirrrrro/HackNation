"""Wynik podobieństwa par reklam z uzasadnieniem.

Intuicja: każdy wspólny ślad to niezależna "szansa", że dwie reklamy mają wspólne źródło.
Łączymy je jak niezależne zdarzenia (noisy-OR):   score = 1 - Π (1 - s_i)
  * jeden słaby ślad (0.3)            -> 0.30
  * dwa średnie (0.5, 0.5)            -> 0.75
  * cokolwiek + wspólny piksel (0.9)  -> >= 0.90
Wynik jest zawsze w [0, 1], a każdy składnik s_i trafia do listy uzasadnień krawędzi.

Ślad TWARDY  = ta sama wartość (wspólny węzeł-artefakt). Siła = waga rodzaju × rzadkość.
Ślad MIĘKKI  = podobieństwo w stopniu 0..1 (wektory, pHash, MinHash szablonu, bliskość dat rejestracji,
               głos lektora, przybliżone porównanie odcisku audio).

Pary-kandydaci są wybierane wektorowo (numpy): wspólny nie-hubowy artefakt (indeks odwrotny)
albo podobieństwo wektorów powyżej progu. Nie liczymy w Pythonie pętli po wszystkich N² parach.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from .card import Card

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
         "transcript": "text", "audio_text": "text",
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

    min_edge: float = 0.25  # słabsze krawędzie nie trafiają do grafu (do klastrowania liczą się wszystkie)


@dataclass
class Reason:
    group: str
    kind: str
    hard: bool
    strength: float
    detail: str


@dataclass
class Edge:
    a: int
    b: int
    score: float
    reasons: list[Reason]  # malejąco wg siły

    @property
    def has_hard(self) -> bool:
        return any(r.hard for r in self.reasons)


def ramp(x, lo, hi):
    return np.clip((np.asarray(x, dtype=float) - lo) / (hi - lo), 0.0, 1.0)


def _unit_matrix(vectors: list[list[float]]) -> np.ndarray | None:
    """Macierz N×d znormalizowanych wektorów; brakujące wektory = wiersz zer (cos = 0)."""
    dims = {len(v) for v in vectors if v}
    if not dims:
        return None
    if len(dims) > 1:
        raise ValueError(f"embeddingi mają różne wymiary: {sorted(dims)}")
    d = dims.pop()
    m = np.zeros((len(vectors), d), dtype=np.float32)
    for i, v in enumerate(vectors):
        if v:
            m[i] = v
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return np.divide(m, norms, out=np.zeros_like(m), where=norms > 0)


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


class Scorer:
    def __init__(self, cards: list[Card], cfg: Config | None = None):
        self.cards, self.cfg = cards, cfg or Config()
        self.n = len(cards)
        self.index: dict[str, list[int]] = defaultdict(list)  # artefakt -> reklamy
        for i, c in enumerate(cards):
            for a in c.artifacts:
                self.index[a.key].append(i)

    # ---------- rzadkość ----------
    def df(self, key: str) -> int:
        return len(self.index.get(key, ()))

    def rarity_of(self, key: str) -> float:
        """Rzadkość artefaktu o danym kluczu "rodzaj|wartość" z uwzględnieniem śladów tożsamościowych."""
        kind = key.split("|", 1)[0]
        df = self.df(key)
        if kind in self.cfg.identity_kinds:
            return 1.0 if df >= 2 else 0.0
        return self.rarity(df)

    def rarity(self, df: int) -> float:
        """0..1: artefakt w 2 reklamach ≈ 1, hub albo unikat = 0 (dla rodzajów nie-tożsamościowych)."""
        n = self.n
        if df <= 1 or n <= 2 or df > self.cfg.max_df_frac * n:
            return 0.0
        return math.log(n / df) / math.log(n / 2)

    # ---------- główna funkcja ----------
    def score_all(self) -> tuple[np.ndarray, list[Edge]]:
        """Zwraca (macierz score N×N, lista krawędzi >= min_edge z uzasadnieniem)."""
        cfg, n = self.cfg, self.n
        reasons: dict[tuple[int, int], list[Reason]] = defaultdict(list)

        # --- TWARDE: indeks odwrotny, tylko artefakty nie-hubowe ---
        for key, ads in self.index.items():
            kind, value = key.split("|", 1)
            s = cfg.base.get(kind, 0.2) * self.rarity_of(key)
            if s <= 0.005:
                continue
            det = f"{KIND_LABEL_PL.get(kind, kind)}: {value} (występuje w {len(ads)} reklamach)"
            for x in range(len(ads)):
                for y in range(x + 1, len(ads)):
                    reasons[(ads[x], ads[y])].append(Reason(GROUP.get(kind, kind), kind, True, s, det))

        # --- MIĘKKIE: macierze podobieństwa ---
        iu = np.triu_indices(n, k=1)

        def soft_from_matrix(sim: np.ndarray, lo: float, hi: float, w: float, group: str, fmt,
                             kind: str | None = None) -> None:
            vals = sim[iu]
            for k in np.nonzero(vals > lo)[0]:
                i, j, c = int(iu[0][k]), int(iu[1][k]), float(vals[k])
                reasons[(i, j)].append(Reason(group, kind or group, False, w * float(ramp(c, lo, hi)), fmt(c)))

        if (T := _unit_matrix([c.text_emb for c in self.cards])) is not None:
            soft_from_matrix(T @ T.T, cfg.text_lo, cfg.text_hi, cfg.w_text, "text",
                             lambda c: f"podobna narracja tekstu (cos={c:.2f})")
        if (V := _unit_matrix([c.clip_emb for c in self.cards])) is not None:
            soft_from_matrix(V @ V.T, cfg.vis_lo, cfg.vis_hi, cfg.w_visual, "visual",
                             lambda c: f"podobny wygląd reklamy (CLIP cos={c:.2f})")

        # Image upload path: fit the vocabulary on reference text only. SHA is a
        # duplicate-file signal even in a two-card corpus, never a rarity/hub test.
        def image_group(a: Card, b: Card) -> str:
            same_source = (a.image_origin and b.image_origin
                           and a.image_text_origin == a.image_origin
                           and b.image_text_origin == b.image_origin)
            return "phash" if same_source else "text"

        by_sha: dict[str, list[int]] = defaultdict(list)
        for i, card in enumerate(self.cards):
            if card.image_sha256:
                by_sha[card.image_sha256].append(i)
        for sha, owners in by_sha.items():
            for x, i in enumerate(owners):
                for j in owners[x + 1:]:
                    reasons[(i, j)].append(Reason("phash", "image_sha256", True, 0.95,
                        f"identyczny plik obrazu (SHA-256: {sha}); to nie potwierdza wspólnej kampanii"))

        reference = [i for i, c in enumerate(self.cards) if c.image_text.strip()
                     and c.raw.get("provenance", {}).get("record_kind") != "image_query"]
        if reference:
            from sklearn.feature_extraction.text import TfidfVectorizer
            vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5))
            try:
                vectorizer.fit([self.cards[i].image_text for i in reference])
            except ValueError:  # empty vocabulary (e.g. whitespace-only material)
                pass
            else:
                matrix = vectorizer.transform([c.image_text for c in self.cards])
                similarities = (matrix @ matrix.T).tocoo()
                for i, j, sim in zip(similarities.row, similarities.col, similarities.data):
                    if i < j and sim > cfg.text_lo:
                        reasons[(int(i), int(j))].append(Reason(
                            image_group(self.cards[i], self.cards[j]), "image_ocr", False,
                            cfg.w_text * float(ramp(sim, cfg.text_lo, cfg.text_hi)),
                            f"podobny tekst obrazu (TF-IDF char_wb 3–5, cos={sim:.2f})"))

        # --- audio ---
        if (A := _unit_matrix([c.audio_text_emb for c in self.cards])) is not None:
            soft_from_matrix(A @ A.T, cfg.text_lo, cfg.text_hi, cfg.w_audio_text, "text",
                             lambda c: f"podobna narracja lektora (cos={c:.2f})", kind="audio_text")
        if (P := _unit_matrix([c.speaker_emb for c in self.cards])) is not None:
            soft_from_matrix(P @ P.T, cfg.voice_lo, cfg.voice_hi, cfg.w_voice, "voice",
                             lambda c: f"ten sam głos lektora (cos={c:.2f})")
        fps = [(i, np.array(c.audio_fp, dtype=np.uint32)) for i, c in enumerate(self.cards) if c.audio_fp]
        for x in range(len(fps)):
            for y in range(x + 1, len(fps)):
                (i, fa), (j, fb) = fps[x], fps[y]
                sim = fingerprint_similarity(fa, fb, cfg.fp_max_shift)
                if sim > cfg.fp_lo:
                    reasons[(i, j)].append(Reason(
                        "audio_fp", "audio_fp_sim", False, cfg.w_audio_fp * float(ramp(sim, cfg.fp_lo, cfg.fp_hi)),
                        f"bardzo podobne nagranie audio ({(1 - sim) * 100:.0f}% różnych bitów odcisku)"))

        # pHash: odległość Hamminga przez XOR i popcount bajtów
        has_ph = np.array([c.phash is not None for c in self.cards])
        if has_ph.sum() > 1:
            ph = np.array([c.phash or 0 for c in self.cards], dtype=np.uint64)
            ham = _POPCOUNT8[(ph[:, None] ^ ph[None, :]).view(np.uint8).reshape(n, n, 8)].sum(-1)
            ok = has_ph[:, None] & has_ph[None, :]
            for i, j in zip(*np.nonzero(np.triu(ok & (ham < cfg.phash_bad), k=1))):
                h = int(ham[i, j])
                s = cfg.w_phash * (1 - float(ramp(h, cfg.phash_good, cfg.phash_bad)))
                reasons[(int(i), int(j))].append(
                    Reason("phash", "phash", False, s, f"niemal identyczna grafika (pHash: {h}/64 bitów różnicy)"))

        # twarze: wszystkie twarze w jednej macierzy; para reklam bierze najlepszą parę twarzy,
        # ważoną GORSZĄ z dwóch jakości
        owners, quals, persons, embs = [], [], [], []
        for i, c in enumerate(self.cards):
            for f in c.faces:
                if f.embedding:
                    owners.append(i); quals.append(f.quality); persons.append(f.person); embs.append(f.embedding)
        if len(embs) > 1:
            F = _unit_matrix(embs)
            S = F @ F.T
            q = np.minimum.outer(np.array(quals), np.array(quals))
            strength = cfg.w_face * ramp(S, cfg.face_lo, cfg.face_hi) * q
            best: dict[tuple[int, int], tuple[float, str]] = {}
            for x, y in zip(*np.nonzero(np.triu(strength > 0.005, k=1))):
                a, b = owners[x], owners[y]
                if a == b:
                    continue
                pair = (min(a, b), max(a, b))
                s = float(strength[x, y])
                if s > best.get(pair, (0.0, ""))[0]:
                    who = f" ({persons[x]})" if persons[x] else ""
                    best[pair] = (s, f"ta sama twarz{who}, cos={S[x, y]:.2f}, jakość min={q[x, y]:.2f}")
            for pair, (s, det) in best.items():
                reasons[pair].append(Reason("face", "face", False, s, det))

        # podobny szablon strony (MinHash): Jaccard ≈ odsetek zgodnych pozycji sygnatury.
        # "Hubowy" szablon (prawie identyczny z ponad max_df_frac korpusu, np. domyślny motyw kreatora
        # stron) nie jest dowodem — tak jak hubowy artefakt.
        by_scheme: dict[str, list[int]] = defaultdict(list)
        for i, c in enumerate(self.cards):
            if c.template_minhash:
                by_scheme[c.template_minhash_scheme].append(i)
        for ads in by_scheme.values():
            if len(ads) < 2:
                continue
            M = np.array([self.cards[i].template_minhash for i in ads], dtype=np.uint32)
            J = np.zeros((len(ads), len(ads)))
            for x in range(len(ads)):  # wiersz po wierszu, żeby nie budować tablicy F×F×num_perm
                J[x] = (M == M[x]).mean(axis=1)
            near_copies = (J >= cfg.tmpl_hi).sum(axis=1) - 1
            hub = near_copies > cfg.max_df_frac * n
            for x, y in zip(*np.nonzero(np.triu(J > cfg.tmpl_lo, k=1))):
                if hub[x] or hub[y]:
                    continue
                i, j = ads[x], ads[y]
                reasons[(i, j)].append(Reason(
                    "template", "template_sim", False, cfg.w_template_sim * float(ramp(J[x, y], cfg.tmpl_lo, cfg.tmpl_hi)),
                    f"podobny szablon strony (MinHash, Jaccard≈{J[x, y]:.2f})"))

        # hurtowa rejestracja: ten sam rejestrator i bliskie daty
        by_reg: dict[str, list[int]] = defaultdict(list)
        for i, c in enumerate(self.cards):
            if c.registrar and c.registered:
                by_reg[c.registrar].append(i)
        for reg, ads in by_reg.items():
            ads.sort(key=lambda i: self.cards[i].registered)
            for x in range(len(ads)):
                for y in range(x + 1, len(ads)):
                    i, j = ads[x], ads[y]
                    dh = (self.cards[j].registered - self.cards[i].registered).total_seconds() / 3600
                    if dh >= cfg.regburst_window_h:
                        break
                    reasons[(min(i, j), max(i, j))].append(Reason(
                        "regburst", "regburst", False, cfg.w_regburst * (1 - dh / cfg.regburst_window_h),
                        f"domeny zarejestrowane w odstępie {dh * 60:.0f} min u {reg}"))

        # --- max na grupę, potem noisy-OR ---
        scores = np.zeros((n, n), dtype=np.float64)
        edges: list[Edge] = []
        for (i, j), rs in reasons.items():
            best_g: dict[str, Reason] = {}
            count: dict[str, int] = defaultdict(int)
            for r in rs:
                count[r.group] += 1
                if r.group not in best_g or r.strength > best_g[r.group].strength:
                    best_g[r.group] = r
            final = []
            for g, r in best_g.items():
                extra = count[g] - 1
                det = r.detail + (f" [+{extra} podobnych śladów w tej grupie]" if extra else "")
                final.append(Reason(r.group, r.kind, r.hard, r.strength, det))
            final.sort(key=lambda r: -r.strength)
            score = 1.0 - math.prod(1.0 - r.strength for r in final)
            scores[i, j] = scores[j, i] = score
            if score >= cfg.min_edge:
                edges.append(Edge(i, j, score, final))
        np.fill_diagonal(scores, 1.0)
        edges.sort(key=lambda e: -e.score)
        return scores, edges
