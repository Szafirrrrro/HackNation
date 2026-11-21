"""Karta reklamy: wczytanie z JSON i wyciągnięcie artefaktów (przyszłych węzłów grafu).

Artefakt = dyskretna wartość, która MOŻE się powtórzyć w innej reklamie (piksel, domena, favicon...). W grafie staje się węzłem współdzielonym przez reklamy (ślad twardy).
Wektory (tekst, CLIP, twarze) nie są węzłami — porównujemy je podobieństwem (ślad miękki).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterator


@dataclass(frozen=True, order=True)
class Artifact:
    kind: str   
    value: str 

    @property
    def key(self) -> str:
        return f"{self.kind}|{self.value}" 


@dataclass
class Face:
    person: str      
    similarity: float
    quality: float     
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
    artifacts: list[Artifact] = field(default_factory=list)  # posortowane, bez duplikatów
    audio: dict[str, Any] = field(default_factory=dict)  # handoff only; scorer has no calibrated audio thresholds
    raw: dict[str, Any] = field(default_factory=dict)


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


def parse_card(j: dict) -> Card:
    prov, infra, page = _d(j, "provenance"), _d(j, "infra"), _d(j, "page")
    rdap, dns, cert, fav = _d(infra, "rdap"), _d(infra, "dns"), _d(infra, "cert"), _d(infra, "favicon")
    trk, contacts = _d(page, "tracking_ids"), _d(page, "contacts")
    text, visual = _d(j, "text"), _d(j, "visual")

    c = Card(
        id=_s(j, "ad_id"), source=_s(prov, "source"), url=_s(prov, "url"),
        fetched_at=_s(prov, "fetched_at"), first_seen=_s(j, "first_seen"),
        last_seen=_s(j, "last_seen"), status=_s(j, "status"), audio=_d(j, "audio"), raw=j,
    )
    arts: set[Artifact] = set()

    def add(kind: str, value: Any) -> None:
        if value not in (None, ""):
            arts.add(Artifact(kind, str(value)))

    c.redirect_chain = [normalize_domain(d) for d in _strs(infra, "redirect_chain")]
    c.final_domain = normalize_domain(_s(infra, "final_domain")) or (c.redirect_chain[-1] if c.redirect_chain else "")
    for d in c.redirect_chain:
        if d != c.final_domain:
            add("domain_hop", d)         
    add("domain_final", c.final_domain)
    c.registrar = _s(rdap, "registrar")
    c.registered = parse_iso(_s(rdap, "registered"))
    add("registrar", c.registrar)
    for ns in _strs(rdap, "nameservers"):
        add("nameserver", normalize_domain(ns))
    if not any("HAR connection IP" in str(e.get("method", "")) for e in j.get("extraction", {}).get("evidence", {}).get("infra.dns.ip", [])):
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
    common_scripts = {s.get("sha256") for s in j.get("extensions", {}).get("scripts", []) if s.get("common_library")}
    for s in _strs(page, "script_hashes"):
        if s not in common_scripts:
            add("script", s)
    add("form_endpoint", normalize_endpoint(_s(page, "form_endpoint")))
    for kind, key in (("phone", "phones"), ("telegram", "telegram"), ("crypto", "crypto")):
        for v in _strs(contacts, key):
            add(kind, v)
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

    c.artifacts = sorted(arts)
    return c


def load_cards(path: str) -> Iterator[Card]:
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    try:
        value = json.loads(content)
    except json.JSONDecodeError:
        for ln, line in enumerate(content.splitlines(), 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError('card must be an object')
                yield parse_card(value)
            except (json.JSONDecodeError, ValueError) as e:
                print(f"linia {ln}: pomijam ({e})")
    else:
        if not isinstance(value, dict):
            raise ValueError('card must be an object')
        yield parse_card(value)
