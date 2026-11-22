"""Karta reklamy: wczytanie z JSON i wyciągnięcie artefaktów (przyszłych węzłów grafu).

Artefakt = dyskretna wartość, która MOŻE się powtórzyć w innej reklamie (piksel, domena,
favicon...). W grafie staje się węzłem współdzielonym przez reklamy (ślad twardy).
Wektory (tekst, CLIP, twarze, głos) nie są węzłami — porównujemy je podobieństwem (ślad miękki).

Puste pola (null, "", brak klucza) NIGDY nie tworzą śladu: brak artefaktu = brak węzła, brak wektora
= brak porównania. Dwie reklamy bez twarzy nie są przez to ani podobne, ani "różne" — po prostu
nic o sobie nie mówią.

Wspólne hosty (skracacze, Facebook, CDN) i popularne domeny nie tworzą artefaktów: wspólne przejście
przez YouTube niczego nie dowodzi. To nie ocena bezpieczeństwa. Trafienia zostają w karcie (trusted_hits).
Subdomena użytkownika platformy (oferta.weebly.com) jest śladem.

Szablon strony: dom_template_hash (identyczny szablon) to artefakt; dom_template_minhash (sygnatura MinHash
shingli DOM) służy do śladu miękkiego "podobny szablon" — ten sam zestaw do budowy stron z drobnymi zmianami.

Audio (opcjonalne pole "audio"): odcisk audio i transkrypcja to artefakty (węzły :AudioFingerprint,
:Transcript); embedding głosu, embedding transkrypcji i sam odcisk (porównanie przybliżone) to ślady miękkie.
"""
from __future__ import annotations

import hashlib
import ipaddress
import math
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit

import idna

from .domain_policy import SHARED_HOSTS, TENANT_PARENTS
from .trusted import cert_blocked, load_trusted, platform_rules


@dataclass(frozen=True, order=True)
class Artifact:
    kind: str   # np. "tracking_id", "domain_hop", "favicon"
    value: str  # np. "PX-771001"

    @property
    def key(self) -> str:
        return f"{self.kind}|{self.value}"


@dataclass(frozen=True)
class FeatureSource:
    origin: str = ""
    method: str = ""
    source_ref: Any = None


@dataclass
class Face:
    person: str            # etykieta z bazy referencyjnej ("" gdy nierozpoznana)
    similarity: float
    quality: float         # 0..1 (MagFace albo proxy: det_score, rozmiar, ostrość)
    deepfake: float
    embedding: list[float]
    source: FeatureSource = field(default_factory=FeatureSource)


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
    image_sha256: str = ""
    image_origin: str = ""
    image_text: str = ""
    image_text_origin: str = ""
    faces: list[Face] = field(default_factory=list)
    # --- audio ---
    audio_transcript: str = ""
    audio_text_emb: list[float] = field(default_factory=list)
    speaker_emb: list[float] = field(default_factory=list)
    audio_fp: list[int] = field(default_factory=list)  # odcisk audio (np. Chromaprint), wartości jako uint32
    audio_duration: float | None = None
    # --- szablon strony: MinHash shingli DOM (podobny, nie identyczny szablon) ---
    template_minhash: list[int] = field(default_factory=list)
    template_minhash_scheme: str = ""  # "metoda|k|num_perm" — porównujemy tylko sygnatury tego samego schematu
    page_text_emb: list[float] = field(default_factory=list)
    feature_sources: dict[str, FeatureSource] = field(default_factory=dict)
    artifact_fields: dict[Artifact, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    trusted_hits: list[str] = field(default_factory=list)  # wspólne lub popularne hosty, pominięte jako ślady
    artifacts: list[Artifact] = field(default_factory=list)  # posortowane, bez duplikatów
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def record_kind(self) -> str:
        return _s(_d(self.raw, "provenance"), "record_kind")

    def signals(self) -> list[str]:
        """Które rodzaje sygnałów karta w ogóle ma. Mało sygnałów = brak kampanii może wynikać
        z braku danych, a nie z tego, że reklama jest unikalna."""
        kinds = {a.kind for a in self.artifacts}
        checks = {
            "domeny": bool(kinds & {"domain_hop", "domain_final"}),
            "infrastruktura": bool(kinds & {"ip", "cert", "nameserver", "favicon"}),
            "śledzenie/skrypty": bool(kinds & {"tracking_id", "script", "form_endpoint", "template", "hidden_text"})
                                 or bool(self.template_minhash),
            "kontakty": bool(kinds & {"phone", "telegram", "crypto"}),
            "tekst": bool(self.text_emb or self.image_text or self.page_text_emb),
            "wygląd": bool(self.clip_emb or self.image_sha256) or self.phash is not None,
            "twarze": any(f.embedding for f in self.faces),
            "audio": bool(self.audio_fp or self.speaker_emb or self.audio_text_emb or self.audio_transcript),
        }
        return [k for k, ok in checks.items() if ok]


SIGNAL_KINDS = 8  # liczba rodzajów w Card.signals()

def is_trusted(host: str, trusted: frozenset[str]) -> bool:
    """Czy host jest zbyt wspólny, żeby być śladem. NIE mówi, czy treść jest bezpieczna ani czy ją pobierać.

    Blokada CERT wygrywa zawsze. Dalej rozstrzyga najdłuższy pasujący sufiks: platforma (sama lub z www)
    jest wspólna, jej subdomena należy do użytkownika; host wspólny i domena z listy obejmują swoje subdomeny (m.youtube.com -> youtube.com).
    """
    parts = normalize_domain(host).split(".")
    suffixes = [".".join(parts[k:]) for k in range(len(parts))]
    blocked = cert_blocked()
    if any(suffix in blocked for suffix in suffixes):
        return False
    platforms, wildcards = platform_rules()
    for k, suffix in enumerate(suffixes[:-1]):
        platform_itself = k == 0 or parts[:k] == ["www"]
        if suffix in TENANT_PARENTS:
            return platform_itself
        if suffix in SHARED_HOSTS:
            return True
        if suffix in platforms or suffixes[k + 1] in wildcards:
            return platform_itself
        if suffix in trusted:
            return True
    return False


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


def _vec(obj: dict, key: str, warnings: list[str], field_name: str) -> list[float]:
    """Wektor liczb. Jeśli zawiera cokolwiek innego (np. skrót "..." z plików podglądowych),
    jest traktowany jako brak wektora — inaczej powstałby krótszy wektor o złym wymiarze."""
    v = obj.get(key)
    if v is None or v == []:
        return []
    if isinstance(v, list) and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
        try:
            numbers = [float(x) for x in v]
        except OverflowError:
            numbers = []
        if numbers and all(map(math.isfinite, numbers)) and any(numbers):
            return numbers
    warnings.append(f"{field_name}: pominięto nieprawidłowy lub zerowy wektor.")
    return []


def _num(obj: dict, key: str, default: float = 0.0) -> float:
    v = obj.get(key)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        try:
            if math.isfinite(v):
                return float(v)
        except OverflowError:
            pass
    return default


def parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize_domain(s: str) -> str:
    """Normalize a DNS name or URL authority before applying host policy."""
    value = s.strip()
    if not value or any(character.isspace() or character == "\\" for character in value):
        return ""
    try:
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            pass
        parsed = urlsplit(value if value.startswith("//") or "://" in value else f"//{value}")
        host = (parsed.hostname or "").rstrip(".")
        if not host:
            return ""
        try:
            return str(ipaddress.ip_address(host))
        except ValueError:
            pass
        host = idna.encode(host, uts46=True, std3_rules=True).decode("ascii").removesuffix(".")
        return host.removeprefix("www.")
    except (ValueError, UnicodeError):
        return ""


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


def parse_card(j: dict, trusted: frozenset[str] | None = None) -> Card:
    prov, infra, page = _d(j, "provenance"), _d(j, "infra"), _d(j, "page")
    rdap, dns, cert, fav = _d(infra, "rdap"), _d(infra, "dns"), _d(infra, "cert"), _d(infra, "favicon")
    trk, contacts = _d(page, "tracking_ids"), _d(page, "contacts")
    text, visual = _d(j, "text"), _d(j, "visual")
    audio, page_text = _d(j, "audio"), _d(page, "text")

    c = Card(
        id=_s(j, "ad_id"), source=_s(prov, "source"), url=_s(prov, "url"),
        fetched_at=_s(prov, "fetched_at"), first_seen=_s(j, "first_seen"),
        last_seen=_s(j, "last_seen"), status=_s(j, "status"), raw=j,
    )
    arts: set[Artifact] = set()
    trusted = load_trusted() if trusted is None else trusted
    hits: set[str] = set()
    extraction = _d(j, "extraction")
    c.warnings.extend(_strs(extraction, "warnings"))
    evidence_rows = extraction.get("evidence")
    evidence = {e["field"]: e for e in (evidence_rows if isinstance(evidence_rows, list) else [])
                if isinstance(e, dict) and isinstance(e.get("field"), str)}

    image_origin = (_s(visual, "origin_id") or _s(j, "image_origin")
                    or next((_s(evidence.get(name, {}), "origin_id") for name in
                             ("visual.sha256", "visual.phash", "visual.clip_embedding")
                             if _s(evidence.get(name, {}), "origin_id")), ""))
    image_present = bool(visual.get("sha256") or visual.get("phash") or visual.get("clip_embedding")
                         or j.get("faces") or text.get("ocr_text"))
    audio_origin = _s(audio, "origin_id") or _s(j, "audio_origin") or "legacy:audio"
    page_origin = _s(page, "origin_id") or _s(infra, "origin_id") or _s(j, "url_origin") or "legacy:page"
    image_origin = image_origin or "legacy:image"

    def source(field_name: str, obj: dict, fallback: str, *, method: str = "",
               origin: str = "") -> FeatureSource:
        info = evidence.get(field_name, {})
        name = field_name.rsplit(".", 1)[-1]
        refs = obj.get("source_refs")
        if isinstance(refs, dict):
            relative = field_name.split(".", 1)[-1]
            refs = refs.get(field_name) or refs.get(relative) or refs.get(relative.split(".", 1)[0])
        result = FeatureSource(
            _s(info, "origin_id") or origin or _s(obj, "origin_id") or fallback,
            _s(info, "method_version") or _s(info, "method") or _s(obj, f"{name}_method")
            or _s(_d(obj, "methods"), name) or method,
            info.get("source_ref") or refs or obj.get("source_ref"),
        )
        c.feature_sources[field_name] = result
        return result

    def page_source(field_name: str, obj: dict, *, method: str = "") -> None:
        origins = _d(infra if field_name.startswith("infra.") else page, "origins")
        origin = _s(origins, field_name) or _s(origins, field_name.split(".", 1)[1])
        source(field_name, obj, page_origin, method=method, origin=origin)

    def untrusted(host: str) -> bool:
        if host and is_trusted(host, trusted):
            hits.add(host)
            return False
        return bool(host)

    def add(kind: str, value: Any, field_name: str) -> None:
        if value not in (None, ""):
            artifact = Artifact(kind, str(value))
            arts.add(artifact)
            c.artifact_fields.setdefault(artifact, field_name)
            if field_name not in c.feature_sources:
                page_source(field_name, infra if field_name.startswith("infra.") else page)

    # --- infrastruktura ---
    c.redirect_chain = [host for d in _strs(infra, "redirect_chain") if (host := normalize_domain(d))]
    c.final_domain = normalize_domain(_s(infra, "final_domain")) or (c.redirect_chain[-1] if c.redirect_chain else "")
    for d in c.redirect_chain:
        if d != c.final_domain and untrusted(d):
            add("domain_hop", d, "infra.redirect_chain")
    if untrusted(c.final_domain):
        add("domain_final", c.final_domain, "infra.final_domain")
    c.registrar = _s(rdap, "registrar")
    c.registered = parse_iso(_s(rdap, "registered"))
    add("registrar", c.registrar, "infra.rdap.registrar")
    page_source("infra.rdap.registered", rdap)
    for ns in _strs(rdap, "nameservers"):
        if untrusted(ns_host := normalize_domain(ns)):
            add("nameserver", ns_host, "infra.rdap.nameservers")
    add("ip", _s(dns, "ip"), "infra.dns.ip")
    add("asn", _s(dns, "asn"), "infra.dns.asn")
    c.cert_id = _s(cert, "id")
    add("cert", c.cert_id, "infra.cert.id")
    for value in _strs(cert, "san"):
        if host := normalize_domain(value.removeprefix("*.")):
            c.cert_san.append(f"*.{host}" if value.startswith("*.") else host)
            untrusted(host)
    if isinstance(fav.get("mmh3"), int):
        add("favicon", fav["mmh3"], "infra.favicon.mmh3")

    # --- strona ---
    add("tracking_id", _s(trk, "meta_pixel"), "page.tracking_ids.meta_pixel")
    add("tracking_id", _s(trk, "ga"), "page.tracking_ids.ga")
    for s in _strs(page, "script_hashes"):
        add("script", s, "page.script_hashes")
    add("form_endpoint", normalize_endpoint(_s(page, "form_endpoint")), "page.form_endpoint")
    for v in _strs(contacts, "phones"):
        add("phone", normalize_phone(v), "page.contacts.phones")
    for v in _strs(contacts, "telegram"):
        add("telegram", normalize_telegram(v), "page.contacts.telegram")
    for v in _strs(contacts, "crypto"):
        add("crypto", v, "page.contacts.crypto")
    add("template", _s(page, "dom_template_hash"), "page.dom_template_hash")
    mh = _d(page, "dom_template_minhash")
    sig = mh.get("signature")
    if isinstance(sig, list) and sig and all(isinstance(x, int) and not isinstance(x, bool) for x in sig):
        num_perm = mh.get("num_perm")
        if not isinstance(num_perm, int) or num_perm == len(sig):
            c.template_minhash = [x & 0xFFFFFFFF for x in sig]
            c.template_minhash_scheme = f"{_s(mh, 'method')}|{mh.get('k')}|{len(sig)}"
    page_source("page.dom_template_minhash", mh, method=_s(mh, "method"))
    page_source("page.text.embedding", page_text, method=_s(page_text, "method"))
    c.page_text_emb = _vec(page_text, "embedding", c.warnings, "page.text.embedding")
    add("hidden_text", _s(page, "hidden_text_hash"), "page.hidden_text_hash")

    # --- treść i obraz ---
    c.ad_text = _s(text, "ad_text")
    text_origin = _s(text, "origin_id") or _s(j, "text_origin") or (image_origin if image_present else "legacy:text")
    c.image_text_origin = _s(text, "ocr_origin_id") or image_origin
    source("text.embedding", text, text_origin, method=_s(text, "method"))
    source("text.keywords", text, text_origin)
    source("text.ocr_text", text, image_origin, origin=c.image_text_origin)
    source("visual.clip_embedding", visual, image_origin, method=_s(visual, "method"))
    source("visual.phash", visual, image_origin, method=_s(visual, "method"))
    source("visual.sha256", visual, image_origin, method="sha256")
    for k in _strs(text, "keywords"):
        add("keyword", k.lower(), "text.keywords")
    c.text_emb = _vec(text, "embedding", c.warnings, "text.embedding")
    c.clip_emb = _vec(visual, "clip_embedding", c.warnings, "visual.clip_embedding")
    if sha := visual.get("sha256"):
        if isinstance(sha, str) and re.fullmatch(r"[0-9a-fA-F]{64}", sha):
            c.image_sha256 = sha.lower()
        else:
            c.warnings.append("visual.sha256: nieprawidłowa suma SHA-256 obrazu.")
    c.image_origin = c.feature_sources["visual.phash"].origin
    c.image_text = _s(text, "ocr_text")
    c.image_text_origin = c.feature_sources["text.ocr_text"].origin
    if ph := _s(visual, "phash"):
        if re.fullmatch(r"[0-9a-fA-F]{1,16}", ph):
            c.phash = int(ph, 16)
        else:
            c.warnings.append("visual.phash: nieprawidłowy pHash64.")

    # --- twarze ---
    faces = j.get("faces")
    for index, f in enumerate(faces if isinstance(faces, list) else []):
        if not isinstance(f, dict):
            continue
        # brak jakości (null) = 0.5 "nie wiadomo"; inaczej twarz byłaby całkowicie ignorowana (waga × 0)
        name = f"faces[{index}].embedding"
        face_source = source(name, f, image_origin, method=_s(f, "method") or _s(j, "face_method"))
        face = Face(_s(f, "person"), _num(f, "similarity"), min(1., max(0., _num(f, "quality", 0.5))),
                    _num(f, "deepfake_score"), _vec(f, "embedding", c.warnings, name), face_source)
        c.faces.append(face)
        add("person", face.person, name)

    # --- audio ---
    c.audio_transcript = _s(audio, "transcript")
    fp = _d(audio, "fingerprint")
    source("audio.transcript", audio, audio_origin, method=_s(audio, "asr_method"))
    source("audio.text_embedding", audio, audio_origin, method=_s(audio, "method"))
    source("audio.speaker_embedding", audio, audio_origin, method=_s(audio, "method"))
    source("audio.fingerprint", fp, audio_origin, method=_s(fp, "method") or _s(audio, "fingerprint_method"))
    c.audio_text_emb = _vec(audio, "text_embedding", c.warnings, "audio.text_embedding")
    c.speaker_emb = _vec(audio, "speaker_embedding", c.warnings, "audio.speaker_embedding")
    c.audio_duration = _num(audio, "duration_s", 0.0) or None
    if t := normalize_transcript(c.audio_transcript):
        add("transcript", t if len(t) <= 300 else "sha1:" + hashlib.sha1(t.encode()).hexdigest()[:16],
            "audio.transcript")
    arr = fp.get("array")
    if isinstance(arr, list) and arr and all(isinstance(x, int) and not isinstance(x, bool) for x in arr):
        c.audio_fp = [x & 0xFFFFFFFF for x in arr]  # int32 ze znakiem -> uint32 (do porównań bitowych)
        add("audio_fp", fingerprint_id(c.audio_fp), "audio.fingerprint")

    c.trusted_hits = sorted(hits)
    c.artifacts = sorted(arts)
    return c


def load_cards(path: str, trusted: frozenset[str] | None = None) -> Iterator[Card]:
    cards, errors, duplicates = read_cards(path, trusted)
    for record in errors + duplicates:
        print(f"linia {record['line']}: pomijam ({record.get('error') or record.get('reason')})", file=sys.stderr)
    yield from cards


def read_cards(path: str, trusted: frozenset[str] | None = None) -> tuple[list[Card], list[dict], list[dict]]:
    # `python -m ftf_graph` launched from graph/ is a supported entry point.
    if __package__ == "ftf_graph":
        root = str(Path(__file__).resolve().parents[2])
        if root not in sys.path:
            sys.path.append(root)
    from models.common.import_rows import deduplicate_rows, read_jsonl

    errors: list[dict] = []
    rows, duplicates = deduplicate_rows(read_jsonl(Path(path), errors), str(Path(path).resolve()), str(path), errors)
    return [parse_card(row, trusted) for _, row in rows], errors, duplicates
