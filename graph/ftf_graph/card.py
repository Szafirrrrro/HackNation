"""Karta reklamy: wczytanie z JSON i wyciągnięcie artefaktów (przyszłych węzłów grafu).

Artefakt = dyskretna wartość, która MOŻE się powtórzyć w innej reklamie (piksel, domena,
favicon...). W grafie staje się węzłem współdzielonym przez reklamy (ślad twardy).
Wektory (tekst, CLIP, twarze, głos) nie są węzłami — porównujemy je podobieństwem (ślad miękki).

Audio (opcjonalne pole "audio"): odcisk audio i transkrypcja to artefakty (węzły :AudioFingerprint,
:Transcript); embedding głosu, embedding transkrypcji i sam odcisk (porównanie przybliżone) to ślady miękkie.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterator


@dataclass(frozen=True, order=True)
class Artifact:
    kind: str   # np. "tracking_id", "domain_hop", "favicon"
    value: str  # np. "PX-771001"

    @property
    def key(self) -> str:
        return f"{self.kind}|{self.value}"


@dataclass
class Face:
    person: str            # etykieta z bazy referencyjnej ("" gdy nierozpoznana)
    similarity: float
    quality: float         # 0..1 (MagFace albo proxy: det_score, rozmiar, ostrość)
    deepfake: float
    embedding: list[float]


@dataclass
class Card:
    id: str
    source: str = ""
    url: str = ""
    fetched_at: str = ""
    first_seen: str = ""
    last_seen: str = ""
    status: str = ""
    redirect_chain: list[str] = field(default_factory=list)
    final_domain: str = ""
    registrar: str = ""
    registered: datetime | None = None
    cert_id: str = ""
    cert_san: list[str] = field(default_factory=list)
    ad_text: str = ""
    text_emb: list[float] = field(default_factory=list)
    clip_emb: list[float] = field(default_factory=list)
    phash: int | None = None
    faces: list[Face] = field(default_factory=list)
    # --- audio ---
    audio_transcript: str = ""
    audio_text_emb: list[float] = field(default_factory=list)
    speaker_emb: list[float] = field(default_factory=list)
    audio_fp: list[int] = field(default_factory=list)  # odcisk audio (np. Chromaprint), wartości jako uint32
    audio_duration: float | None = None
    artifacts: list[Artifact] = field(default_factory=list)  # posortowane, bez duplikatów
    raw: dict[str, Any] = field(default_factory=dict)


# ---------- pomocnicze ----------
def _d(obj: Any, key: str) -> dict:
    v = obj.get(key) if isinstance(obj, dict) else None
    return v if isinstance(v, dict) else {}


def _s(obj: dict, key: str) -> str:
    v = obj.get(key)
    return v if isinstance(v, str) else ""


def _strs(obj: dict, key: str) -> list[str]:
    v = obj.get(key)
    return [x for x in v if isinstance(x, str) and x] if isinstance(v, list) else []


def _vec(obj: dict, key: str) -> list[float]:
    v = obj.get(key)
    return [float(x) for x in v if isinstance(x, (int, float))] if isinstance(v, list) else []


def _num(obj: dict, key: str, default: float = 0.0) -> float:
    v = obj.get(key)
    return float(v) if isinstance(v, (int, float)) else default


def parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize_domain(s: str) -> str:
    """Węzłem jest domena, nie pełny URL — pełne linki mają unikalne parametry śledzące
    i nigdy by się nie powtórzyły."""
    if "://" in s:
        s = s.split("://", 1)[1]
    for sep in "/?#":
        s = s.split(sep, 1)[0]
    s = s.lower()
    return s[4:] if s.startswith("www.") else s


def normalize_endpoint(s: str) -> str:
    """Endpoint formularza: host + ścieżka, bez parametrów."""
    if "://" in s:
        s = s.split("://", 1)[1]
    for sep in "?#":
        s = s.split(sep, 1)[0]
    return s


def normalize_phone(s: str) -> str:
    """"+48 123-456-789" i "+48123456789" to ten sam numer."""
    return ("+" if s.strip().startswith("+") else "") + re.sub(r"\D", "", s)


def normalize_telegram(s: str) -> str:
    """"https://t.me/demo_operator", "t.me/demo_operator" i "@demo_operator" -> "@demo_operator"."""
    s = s.strip()
    s = re.sub(r"^(https?://)?(www\.)?(t\.me|telegram\.me)/", "", s, flags=re.I)
    s = s.split("?", 1)[0].strip("/").lstrip("@").lower()
    return f"@{s}" if s else ""


def normalize_transcript(s: str) -> str:
    """Małe litery, bez interpunkcji i nadmiarowych spacji — ten sam skrypt lektora = ta sama wartość."""
    return " ".join(re.sub(r"[^\w\s]", " ", s.lower()).split())


def fingerprint_id(fp: list[int]) -> str:
    return "sha1:" + hashlib.sha1(",".join(map(str, fp)).encode()).hexdigest()[:16]


def parse_card(j: dict) -> Card:
    prov, infra, page = _d(j, "provenance"), _d(j, "infra"), _d(j, "page")
    rdap, dns, cert, fav = _d(infra, "rdap"), _d(infra, "dns"), _d(infra, "cert"), _d(infra, "favicon")
    trk, contacts = _d(page, "tracking_ids"), _d(page, "contacts")
    text, visual = _d(j, "text"), _d(j, "visual")

    c = Card(
        id=_s(j, "ad_id"), source=_s(prov, "source"), url=_s(prov, "url"),
        fetched_at=_s(prov, "fetched_at"), first_seen=_s(j, "first_seen"),
        last_seen=_s(j, "last_seen"), status=_s(j, "status"), raw=j,
    )
    arts: set[Artifact] = set()

    def add(kind: str, value: Any) -> None:
        if value not in (None, ""):
            arts.add(Artifact(kind, str(value)))

    # --- infrastruktura ---
    c.redirect_chain = [normalize_domain(d) for d in _strs(infra, "redirect_chain")]
    c.final_domain = normalize_domain(_s(infra, "final_domain")) or (c.redirect_chain[-1] if c.redirect_chain else "")
    for d in c.redirect_chain:
        if d != c.final_domain:
            add("domain_hop", d)          # domeny frontowe i pośrednicy
    add("domain_final", c.final_domain)
    c.registrar = _s(rdap, "registrar")
    c.registered = parse_iso(_s(rdap, "registered"))
    add("registrar", c.registrar)
    for ns in _strs(rdap, "nameservers"):
        add("nameserver", normalize_domain(ns))
    add("ip", _s(dns, "ip"))
    add("asn", _s(dns, "asn"))
    c.cert_id = _s(cert, "id")
    add("cert", c.cert_id)
    c.cert_san = [normalize_domain(d) for d in _strs(cert, "san")]
    if isinstance(fav.get("mmh3"), int):
        add("favicon", fav["mmh3"])

    # --- strona ---
    add("tracking_id", _s(trk, "meta_pixel"))
    add("tracking_id", _s(trk, "ga"))
    for s in _strs(page, "script_hashes"):
        add("script", s)
    add("form_endpoint", normalize_endpoint(_s(page, "form_endpoint")))
    for v in _strs(contacts, "phones"):
        add("phone", normalize_phone(v))
    for v in _strs(contacts, "telegram"):
        add("telegram", normalize_telegram(v))
    for v in _strs(contacts, "crypto"):
        add("crypto", v)
    add("template", _s(page, "dom_template_hash"))
    add("hidden_text", _s(page, "hidden_text_hash"))

    # --- treść i obraz ---
    c.ad_text = _s(text, "ad_text")
    for k in _strs(text, "keywords"):
        add("keyword", k.lower())
    c.text_emb = _vec(text, "embedding")
    c.clip_emb = _vec(visual, "clip_embedding")
    if ph := _s(visual, "phash"):
        c.phash = int(ph, 16)

    # --- twarze ---
    for f in j.get("faces") or []:
        if not isinstance(f, dict):
            continue
        face = Face(_s(f, "person"), _num(f, "similarity"), _num(f, "quality"),
                    _num(f, "deepfake_score"), _vec(f, "embedding"))
        c.faces.append(face)
        add("person", face.person)

    # --- audio ---
    audio = _d(j, "audio")
    c.audio_transcript = _s(audio, "transcript")
    c.audio_text_emb = _vec(audio, "text_embedding")
    c.speaker_emb = _vec(audio, "speaker_embedding")
    c.audio_duration = _num(audio, "duration_s", 0.0) or None
    if t := normalize_transcript(c.audio_transcript):
        add("transcript", t if len(t) <= 300 else "sha1:" + hashlib.sha1(t.encode()).hexdigest()[:16])
    arr = _d(audio, "fingerprint").get("array")
    if isinstance(arr, list) and arr and all(isinstance(x, int) and not isinstance(x, bool) for x in arr):
        c.audio_fp = [x & 0xFFFFFFFF for x in arr]  # int32 ze znakiem -> uint32 (do porównań bitowych)
        add("audio_fp", fingerprint_id(c.audio_fp))

    c.artifacts = sorted(arts)
    return c


def load_cards(path: str) -> Iterator[Card]:
    with open(path, encoding="utf-8") as fh:
        for ln, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                yield parse_card(json.loads(line))
            except (json.JSONDecodeError, ValueError) as e:
                print(f"linia {ln}: pomijam ({e})")
