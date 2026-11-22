"""Lookup helpers for traffic ranking corpora with multi-tenant/UGC protection."""

from __future__ import annotations

import csv
import ipaddress
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

# Domyślna ścieżka do listy rankingowej (np. Tranco) w projekcie.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RANKING_LIST_PATH = PROJECT_ROOT / "data" / "tranco_top.csv"
DEFAULT_RANKING_MAX_RANK = 100_000

# Platformy hostingowe / UGC / kreatorzy stron, gdzie wysoka pozycja eTLD+1 w rankingu
# dotyczy samej platformy, a nie pojedynczej strony/subdomeny użytkownika.
MULTI_TENANT_HOSTS = {
    "substack.com",
    "github.io",
    "sites.google.com",
    "vercel.app",
    "myshopify.com",
    "notion.site",
    "webflow.io",
    "pages.dev",
    "herokuapp.com",
    "blogspot.com",
    "wordpress.com",
    "wixsite.com",
    "carrd.co",
    "linktr.ee",
    "beacons.ai",
}

# Prosty fallback wyciągania eTLD+1 z hosta (bez zewnętrznych zależności).
# Jeśli masz zainstalowane `tldextract`, użyjemy go automatycznie.
_MULTI_PART_TLDS = {
    "co.uk",
    "org.uk",
    "ac.uk",
    "gov.uk",
    "com.pl",
    "net.pl",
    "org.pl",
    "gov.pl",
    "edu.pl",
    "com.au",
    "net.au",
    "org.au",
    "gov.au",
    "co.jp",
    "ne.jp",
    "or.jp",
    "go.jp",
}


def extract_etld_plus_1(host: str) -> str:
    clean_host = (host or "").strip(".").lower()
    if not clean_host:
        return ""
    try:
        ipaddress.ip_address(clean_host)
        return ""
    except ValueError:
        pass

    try:
        import tldextract  # type: ignore

        ext = tldextract.extract(clean_host)
        if ext.domain and ext.suffix:
            return f"{ext.domain}.{ext.suffix}".lower()
    except Exception:
        pass

    labels = clean_host.split(".")
    if len(labels) < 2:
        return clean_host
    tail2 = ".".join(labels[-2:])
    if len(labels) >= 3 and tail2 in _MULTI_PART_TLDS:
        return ".".join(labels[-3:])
    return tail2


def _normalize_domain_entry(raw: str) -> str:
    value = (raw or "").strip().lower()
    if not value or value.startswith("#"):
        return ""
    if "://" in value:
        value = (urlsplit(value).hostname or "").strip(".").lower()
    else:
        value = value.split("/", 1)[0].split(":", 1)[0].strip(".")
    return extract_etld_plus_1(value)


def is_multi_tenant_host(
    host: str,
    etld1: str | None = None,
    multi_tenant_hosts: set[str] | None = None,
) -> bool:
    clean_host = (host or "").strip(".").lower()
    clean_etld1 = (etld1 or extract_etld_plus_1(clean_host)).strip(".").lower()
    tenants = {h.strip(".").lower() for h in (multi_tenant_hosts or MULTI_TENANT_HOSTS)}
    if not clean_host and not clean_etld1:
        return False
    if clean_host in tenants or clean_etld1 in tenants:
        return True
    return any(clean_host == t or clean_host.endswith(f".{t}") for t in tenants)


def load_tranco_top(
    path: str | Path | None = DEFAULT_RANKING_LIST_PATH,
    max_rank: int = DEFAULT_RANKING_MAX_RANK,
) -> set[str]:
    """Wczytuje ranking (np. CSV `rank,domain` lub lista) i zachowuje domeny do `max_rank`."""
    if not path or max_rank <= 0:
        return set()
    file_path = Path(path)
    if not file_path.is_file():
        return set()

    domains: set[str] = set()
    with file_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        for idx, row in enumerate(reader, start=1):
            if not row:
                continue
            first = row[0].strip()
            if first.isdigit():
                rank = int(first)
                raw_domain = row[1] if len(row) > 1 else ""
            else:
                rank = idx
                raw_domain = first
            if rank > max_rank:
                break
            norm = _normalize_domain_entry(raw_domain)
            if norm:
                domains.add(norm)
    return domains


def match_authoritative_corpus(
    url: str,
    ranking_list_path: str | Path | None = DEFAULT_RANKING_LIST_PATH,
    ranking_max_rank: int = DEFAULT_RANKING_MAX_RANK,
    has_active_blocklist_hit: Callable[[str, str], bool] | None = None,
) -> tuple[str, str] | None:
    """
    Zwraca (reason_code, reason) gdy eTLD+1 mieści się w rankingu ruchu (np. Tranco),
    nie jest platformą multi-tenant/UGC oraz nie ma aktywnego trafienia na bloklistę.
    """
    try:
        host = (urlsplit(url).hostname or "").strip(".").lower()
    except ValueError:
        return None
    etld1 = extract_etld_plus_1(host)
    if not etld1:
        return None

    if is_multi_tenant_host(host, etld1):
        return None

    ranked_domains = load_tranco_top(ranking_list_path, max_rank=ranking_max_rank)
    if etld1 in ranked_domains:
        blocked = False
        if has_active_blocklist_hit is not None:
            try:
                blocked = bool(has_active_blocklist_hit(host, etld1))
            except Exception:
                blocked = False
        if not blocked:
            return (
                "ranked_corpus",
                f"Domena {etld1} mieści się w rankingu ruchu (top {ranking_max_rank}) bez UGC i aktywnej bloklisty.",
            )

    return None
