"""Bidirectional cross-verification (closed-loop proof) for legitimate domains."""

from __future__ import annotations

import ipaddress
import json
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VERIFIED_APPS_PATH = PROJECT_ROOT / "data" / "verified_apps.json"
DEFAULT_VERIFIED_ENTITIES_PATH = PROJECT_ROOT / "data" / "verified_entities.json"

USER_AGENT = "ScamGraph-ClosedLoop-Verify/1.0"
_CACHE: dict[str, tuple[str, str] | None] = {}


def _clean_host(url: str) -> str:
    try:
        host = (urlsplit(url).hostname or "").strip(".").lower()
    except ValueError:
        return ""
    if not host:
        return ""
    try:
        ipaddress.ip_address(host)
        return ""
    except ValueError:
        return host


def _normalize_site_host(raw_url: str) -> str:
    val = (raw_url or "").strip()
    if not val:
        return ""
    if "://" not in val:
        val = f"https://{val}"
    try:
        host = (urlsplit(val).hostname or "").strip(".").lower()
    except ValueError:
        return ""
    return host.removeprefix("www.")


def _fetch_text(url: str, timeout: float = 3.0, max_bytes: int = 512 * 1024) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if getattr(resp, "status", 200) >= 400:
                return None
            return resp.read(max_bytes).decode("utf-8", errors="ignore")
    except Exception:
        return None


def _load_json_file(path: Path) -> dict | list | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 1. .well-known & App Association Files (assetlinks.json / apple-app-site-association)
# ---------------------------------------------------------------------------


def _load_verified_apps(path: Path = DEFAULT_VERIFIED_APPS_PATH) -> dict[str, set[str]]:
    """
    Oczekiwany opcjonalny plik `data/verified_apps.json`, np.:
    {
      "android": {
        "pl.mojbank.mobile": ["AA:BB:CC:..."]
      },
      "ios": ["TEAMID.pl.mojbank.mobile"]
    }
    """
    data = _load_json_file(path)
    if not isinstance(data, dict):
        return {"android": {}, "ios": set()}  # type: ignore[return-value]
    android_raw = data.get("android") or {}
    android: dict[str, set[str]] = {}
    if isinstance(android_raw, dict):
        for pkg, fps in android_raw.items():
            if isinstance(fps, list):
                android[pkg.strip()] = {str(fp).strip().upper() for fp in fps if str(fp).strip()}
    ios_raw = data.get("ios") or []
    ios = {str(x).strip() for x in ios_raw if str(x).strip()} if isinstance(ios_raw, list) else set()
    return {"android": android, "ios": ios}  # type: ignore[return-value]


def check_well_known_app_links(
    host: str,
    timeout: float = 3.0,
    verified_apps_path: Path = DEFAULT_VERIFIED_APPS_PATH,
) -> tuple[str, str] | None:
    """
    Pobiera `/.well-known/assetlinks.json` (oraz `apple-app-site-association`) po HTTPS
    i weryfikuje dopasowanie package_name + SHA-256 fingerprint do rejestru wydawców.
    """
    registry = _load_verified_apps(verified_apps_path)
    android_reg: dict[str, set[str]] = registry.get("android", {})  # type: ignore[assignment]
    ios_reg: set[str] = registry.get("ios", set())  # type: ignore[assignment]

    if not android_reg and not ios_reg:
        return None

    # Android Digital Asset Links
    if android_reg:
        raw_assetlinks = _fetch_text(f"https://{host}/.well-known/assetlinks.json", timeout=timeout)
        if raw_assetlinks:
            try:
                entries = json.loads(raw_assetlinks)
            except Exception:
                entries = []
            if isinstance(entries, list):
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    target = entry.get("target") or {}
                    if target.get("namespace") != "android_app":
                        continue
                    pkg = str(target.get("package_name") or "").strip()
                    fps = target.get("sha256_cert_fingerprints") or []
                    if pkg in android_reg and isinstance(fps, list):
                        normalized_fps = {str(fp).strip().upper() for fp in fps}
                        if normalized_fps & android_reg[pkg]:
                            return (
                                "well_known_assetlinks",
                                f"Dwukierunkowo zweryfikowano assetlinks.json ({pkg}) dla {host}.",
                            )

    # Apple Universal Links (AASA)
    if ios_reg:
        raw_aasa = _fetch_text(f"https://{host}/.well-known/apple-app-site-association", timeout=timeout)
        if raw_aasa:
            try:
                aasa = json.loads(raw_aasa)
            except Exception:
                aasa = {}
            details = ((aasa.get("applinks") or {}).get("details") or []) if isinstance(aasa, dict) else []
            if isinstance(details, list):
                for item in details:
                    if not isinstance(item, dict):
                        continue
                    candidates = []
                    if item.get("appID"):
                        candidates.append(str(item["appID"]))
                    if isinstance(item.get("appIDs"), list):
                        candidates.extend(str(x) for x in item["appIDs"])
                    for app_id in candidates:
                        if app_id.strip() in ios_reg:
                            return (
                                "well_known_aasa",
                                f"Dwukierunkowo zweryfikowano apple-app-site-association ({app_id.strip()}) dla {host}.",
                            )

    return None


# ---------------------------------------------------------------------------
# 2. Official Social / Knowledge Graph Loop (rel="me" / schema.org JSON-LD)
# ---------------------------------------------------------------------------


class _IdentityLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rel_me_links: list[str] = []
        self._in_jsonld = False
        self._buf: list[str] = []
        self.jsonld_blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        if tag.lower() in {"a", "link"}:
            rels = set(attr_map.get("rel", "").lower().split())
            href = attr_map.get("href", "").strip()
            if "me" in rels and href:
                self.rel_me_links.append(href)
        elif tag.lower() == "script" and "ld+json" in attr_map.get("type", "").lower():
            self._in_jsonld = True
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._in_jsonld:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_jsonld:
            self._in_jsonld = False
            raw = "".join(self._buf).strip()
            if raw:
                self.jsonld_blocks.append(raw)


def _extract_claimed_references(html: str) -> set[str]:
    parser = _IdentityLinkParser()
    try:
        parser.feed(html)
    except Exception:
        return set()

    refs: set[str] = {link.strip() for link in parser.rel_me_links if link.strip()}

    def _walk(node: object) -> None:
        if isinstance(node, list):
            for item in node:
                _walk(item)
        elif isinstance(node, dict):
            node_type = node.get("@type")
            types = [node_type] if isinstance(node_type, str) else (node_type if isinstance(node_type, list) else [])
            if any("Organization" in str(t) for t in types) or not types:
                for key in ("sameAs", "url", "@id"):
                    val = node.get(key)
                    if isinstance(val, str) and val.strip():
                        refs.add(val.strip())
                    elif isinstance(val, list):
                        for v in val:
                            if isinstance(v, str) and v.strip():
                                refs.add(v.strip())
            for v in node.values():
                if isinstance(v, (dict, list)):
                    _walk(v)

    for block in parser.jsonld_blocks:
        try:
            parsed = json.loads(block)
            _walk(parsed)
        except Exception:
            continue

    return refs


def _wikidata_entity_confirms_host(qid: str, expected_host: str, timeout: float = 3.0) -> bool:
    """Sprawdza w Wikidata (P856 - official website), czy encja QID wskazuje z powrotem na `expected_host`."""
    if not re.fullmatch(r"Q[0-9]+", qid):
        return False
    api_url = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
    raw = _fetch_text(api_url, timeout=timeout, max_bytes=1024 * 1024)
    if not raw:
        return False
    try:
        data = json.loads(raw)
        entity = (data.get("entities") or {}).get(qid) or {}
        claims = (entity.get("claims") or {}).get("P856") or []
        target_norm = expected_host.removeprefix("www.")
        for claim in claims:
            val = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
            if isinstance(val, str) and _normalize_site_host(val) == target_norm:
                return True
    except Exception:
        return False
    return False


def check_knowledge_graph_loop(
    host: str,
    timeout: float = 3.0,
    verified_entities_path: Path = DEFAULT_VERIFIED_ENTITIES_PATH,
) -> tuple[str, str] | None:
    """
    Sprawdza zamkniętą pętlę tożsamości:
    strona główna deklaruje `rel="me"` lub `schema.org` (`Organization`), a zewnętrzny rekord
    (lokalny rejestr `verified_entities.json` lub encja Wikidata P856) wskazuje z powrotem na tę domenę.
    """
    html = _fetch_text(f"https://{host}/", timeout=timeout)
    if not html:
        return None

    refs = _extract_claimed_references(html)
    if not refs:
        return None

    target_norm = host.removeprefix("www.")

    # 1) Lokalny kuratorowany rejestr encji (np. wpis z rejestru spółek / oficjalny profil -> domena)
    local_entities = _load_json_file(verified_entities_path)
    if isinstance(local_entities, dict):
        # Format: {"https://github.com/organizacja": "example.com", ...}
        norm_refs = {r.rstrip("/").lower() for r in refs}
        for ext_id, registered_domain in local_entities.items():
            if ext_id.rstrip("/").lower() in norm_refs and _normalize_site_host(str(registered_domain)) == target_norm:
                return (
                    "closed_loop_registry",
                    f"Dwukierunkowa pętla tożsamości ({ext_id} <-> {host}) potwierdzona.",
                )

    # 2) Pętla z Wikidata (jeśli strona wskazuje na encję Wikidata w JSON-LD / rel="me")
    for ref in refs:
        m = re.search(r"wikidata\.org/(?:wiki|entity)/(Q[0-9]+)", ref, re.IGNORECASE)
        if m:
            qid = m.group(1).upper()
            if _wikidata_entity_confirms_host(qid, target_norm, timeout=timeout):
                return (
                    "closed_loop_wikidata",
                    f"Dwukierunkowa pętla tożsamości z Wikidata ({qid} <-> {host}) potwierdzona.",
                )

    return None


def match_bidirectional_verification(url: str, timeout: float = 3.0) -> tuple[str, str] | None:
    """
    Zwraca (reason_code, reason), jeśli domena przejdzie dwukierunkową weryfikację
    (.well-known app association lub zamknięta pętla Knowledge Graph / rejestru).
    """
    host = _clean_host(url)
    if not host:
        return None
    if host in _CACHE:
        return _CACHE[host]

    result = check_well_known_app_links(host, timeout=timeout)
    if not result:
        result = check_knowledge_graph_loop(host, timeout=timeout)

    _CACHE[host] = result
    return result
