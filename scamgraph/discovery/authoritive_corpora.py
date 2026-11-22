"""Lookup helpers for traffic ranking corpora with multi-tenant/UGC protection."""

from __future__ import annotations

import csv
import functools
import ipaddress
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

import tldextract

# Lista rankingowa (Tranco top-100k) dołączona do pakietu discovery.
DEFAULT_RANKING_LIST_PATH = Path(__file__).resolve().parent / "data" / "top-100k.csv"
DEFAULT_RANKING_MAX_RANK = 5_000

# Public Suffix List z sekcją prywatną, z migawki dołączonej do tldextract: bez sieci i bez cache na dysku.
# Dzięki sekcji prywatnej xyz.s3.amazonaws.com, abc.netlify.app czy x.web.app są własną domeną użytkownika,
# a nie domeną platformy z rankingu.
_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True)

from graph.ftf_graph.domain_policy import MULTI_TENANT_HOSTS, NEVER_TRUST_BY_RANK

def extract_etld_plus_1(host: str) -> str:
    """Domena rejestrowalna według PSL z sekcją prywatną; pusty napis dla IP, sufiksu lub nieznanego TLD."""
    clean_host = (host or "").strip(".").lower()
    if not clean_host:
        return ""
    try:
        ipaddress.ip_address(clean_host)
        return ""
    except ValueError:
        pass
    ext = _EXTRACT(clean_host)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}".lower()
    return ""


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
    # Własna lista uzupełnia domyślne wykluczenia, nigdy ich nie zastępuje.
    tenants = {h.strip(".").lower() for h in MULTI_TENANT_HOSTS | NEVER_TRUST_BY_RANK | set(multi_tenant_hosts or ())}
    if not clean_host and not clean_etld1:
        return False
    if clean_host in tenants or clean_etld1 in tenants:
        return True
    return any(clean_host == t or clean_host.endswith(f".{t}") for t in tenants)


def load_tranco_top(
    path: str | Path | None = DEFAULT_RANKING_LIST_PATH,
    max_rank: int = DEFAULT_RANKING_MAX_RANK,
) -> frozenset[str]:
    """Wczytuje ranking (np. CSV `rank,domain` lub lista) i zachowuje domeny do `max_rank`.

    Brak pliku daje pusty zbiór, czyli brak pominięć na podstawie rankingu (strona zostanie pobrana).
    Wynik jest zapamiętywany w procesie dla pary (ścieżka, max_rank)."""
    if not path or max_rank <= 0:
        return frozenset()
    return _load_ranking(str(Path(path).resolve()), max_rank)


@functools.lru_cache(maxsize=8)
def _load_ranking(path: str, max_rank: int) -> frozenset[str]:
    file_path = Path(path)
    if not file_path.is_file():
        return frozenset()

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
    return frozenset(domains)


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
                blocked = True  # niepewność oznacza pobranie strony, a nie zaufanie
        if not blocked:
            return (
                "ranked_corpus",
                f"Domena {etld1} mieści się w rankingu ruchu (top {ranking_max_rank}), a host nie jest na liście "
                "wykluczeń. Ranking nie ocenia treści strony.",
            )

    return None
