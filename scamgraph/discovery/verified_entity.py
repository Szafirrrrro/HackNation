"""Best-effort checks for verified/institutional domains to skip landing visits."""

from __future__ import annotations

import ipaddress
import re
import socket
import ssl
import urllib.request
from urllib.parse import urlsplit

# Domyślnie restrykcyjne / instytucjonalne końcówki TLD / eTLD.
# Dopasuj do swojego kontekstu (np. .gov.pl, .edu.pl itd., jeśli chcesz).
GATED_TLDS = {
    "gov",
    "edu",
    "mil",
    "bank",
    "insurance",
    "gov.pl",
    "edu.pl",
}

# OID-y z reguły OV/EV (jurisdiction / serialNumber / EV policy)
OV_EV_OIDS = {
    "2.5.4.5",  # serialNumber
    "1.3.6.1.4.1.311.60.2.1.1",  # evJurisdictionLocalityName
    "1.3.6.1.4.1.311.60.2.1.2",  # evJurisdictionStateOrProvinceName
    "1.3.6.1.4.1.311.60.2.1.3",  # evJurisdictionCountryName
}

_CACHE: dict[str, tuple[str, str] | None] = {}


def _hostname_from_url(url: str) -> str:
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


def _dns_resolves(host: str, timeout: float = 2.0) -> bool:
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        socket.getaddrinfo(host, None)
        return True
    except OSError:
        return False
    finally:
        socket.setdefaulttimeout(old_timeout)


def check_gated_tld(host: str, gated_tlds: set[str] | None = None, timeout: float = 2.0) -> tuple[str, str] | None:
    """Jeśli końcówka domeny należy do gated_tlds i host rozwiązuje się w DNS, zwróć (code, reason)."""
    allowed = {t.lstrip(".").lower() for t in (gated_tlds or GATED_TLDS)}
    parts = host.split(".")
    if len(parts) < 2:
        return None
    matched_tld = None
    for i in range(1, len(parts)):
        candidate = ".".join(parts[i:])
        if candidate in allowed:
            matched_tld = candidate
            break
    if not matched_tld:
        return None
    if not _dns_resolves(host, timeout=timeout):
        return None
    return ("gated_tld", f"Zweryfikowana końcówka rejestru (.{matched_tld}) dla hosta {host}.")


def _extract_subject_fields(cert: dict) -> dict[str, str]:
    fields: dict[str, str] = {}
    for rdn in cert.get("subject", ()):
        for key, val in rdn:
            fields[str(key)] = str(val)
    return fields


def check_ov_ev_tls(host: str, port: int = 443, timeout: float = 3.0) -> tuple[str, str] | None:
    """Sprawdza certyfikat TLS serwera pod kątem pola Organization (O) i cech OV/EV."""
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls_sock:
                cert = tls_sock.getpeercert()
    except Exception:
        return None

    if not cert:
        return None

    subject = _extract_subject_fields(cert)
    org = subject.get("organizationName") or subject.get("O")
    has_ov_ev_oid = any(oid in subject for oid in OV_EV_OIDS)

    if org and (has_ov_ev_oid or len(org.strip()) > 0):
        detail = f"Certyfikat TLS z organizacją '{org.strip()}'"
        if has_ov_ev_oid:
            detail += " oraz polami OV/EV"
        return ("ov_ev_tls", f"{detail} dla hosta {host}.")
    return None


def _dns_txt_records(name: str, timeout: float = 2.0) -> list[str]:
    """Lekkie pobranie rekordów TXT bez zewnętrznych paczek (przez dnspython jeśli jest, albo fallback)."""
    try:
        import dns.resolver  # type: ignore

        resolver = dns.resolver.Resolver()
        resolver.lifetime = timeout
        answers = resolver.resolve(name, "TXT")
        out: list[str] = []
        for rdata in answers:
            chunks = [
                b.decode("utf-8", errors="ignore") if isinstance(b, bytes) else str(b)
                for b in getattr(rdata, "strings", [])
            ]
            if chunks:
                out.append("".join(chunks))
            else:
                out.append(rdata.to_text().strip('"'))
        return out
    except Exception:
        return []


def check_vmc_bimi(host: str, timeout: float = 3.0) -> tuple[str, str] | None:
    """Sprawdza DMARC (p=quarantine/reject), default._bimi.<host> oraz dostępność VMC PEM z a=."""
    parts = host.split(".")
    base_domain = ".".join(parts[-2:]) if len(parts) >= 2 else host

    dmarc_records = _dns_txt_records(f"_dmarc.{base_domain}", timeout=timeout)
    has_strict_dmarc = False
    for rec in dmarc_records:
        if "v=dmarc1" in rec.lower() and re.search(r"\bp\s*=\s*(quarantine|reject)\b", rec, re.IGNORECASE):
            has_strict_dmarc = True
            break
    if not has_strict_dmarc:
        return None

    bimi_records = _dns_txt_records(f"default._bimi.{base_domain}", timeout=timeout)
    pem_url = None
    for rec in bimi_records:
        if "v=bimi1" in rec.lower():
            m = re.search(r"\ba\s*=\s*([^\s;]+)", rec, re.IGNORECASE)
            if m and m.group(1).lower().startswith("https://"):
                pem_url = m.group(1)
                break
    if not pem_url:
        return None

    # Pobranie pliku VMC PEM w celu potwierdzenia, że a= wskazuje na certyfikat PEM.
    try:
        req = urllib.request.Request(pem_url, headers={"User-Agent": "ScamGraph-VMC-Check/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(256 * 1024).decode("utf-8", errors="ignore")
        if "BEGIN CERTIFICATE" in body:
            return ("vmc_bimi", f"Wykryto DMARC enforcement + BIMI VMC PEM dla {base_domain}.")
    except Exception:
        return None

    return None


def match_verified_entity(url: str, options: dict | None = None) -> tuple[str, str] | None:
    """
    Zwraca (reason_code, reason) jeśli host pasuje do włączonych reguł weryfikacji podmiotu,
    w przeciwnym razie None.
    """
    host = _hostname_from_url(url)
    if not host:
        return None

    opts = options or {}
    cache_key = host
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    checks = []
    if opts.get("check_gated_tld", True):
        checks.append(lambda: check_gated_tld(host, opts.get("gated_tlds")))
    if opts.get("check_ov_ev_tls", True):
        checks.append(lambda: check_ov_ev_tls(host))
    if opts.get("check_vmc_bimi", False):
        checks.append(lambda: check_vmc_bimi(host))

    result: tuple[str, str] | None = None
    for fn in checks:
        try:
            hit = fn()
        except Exception:
            hit = None
        if hit:
            result = hit
            break

    _CACHE[cache_key] = result
    return result
