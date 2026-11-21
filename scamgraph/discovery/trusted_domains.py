"""Exact, operator-maintained DNS names for landing-page filtering."""
from contextlib import closing
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

import idna


def canonical_domain(value):
    try:
        host = idna.encode(value.strip(), uts46=True, std3_rules=True).decode("ascii").removesuffix(".")
    except idna.IDNAError as exc:
        raise ValueError("Oczekiwano pełnej nazwy domeny DNS.") from exc
    if "." not in host or host.rsplit(".", 1)[1].isdigit():
        raise ValueError("Podaj nazwę domeny DNS z co najmniej dwiema etykietami.")
    return host


def match_url(database, url):
    if database is None:
        return None
    try:
        parts = urlsplit(url)
        if (parts.scheme not in {"https", "http"} or parts.username is not None or not parts.hostname
                or parts.port not in {None, 80, 443} or any(ord(ch) < 33 or ch == "\\" for ch in url)):
            return None
        host = canonical_domain(parts.hostname)
    except ValueError:
        return None
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as db:
        row = db.execute("SELECT domain FROM trusted_domains WHERE domain=?", (host,)).fetchone()
    return host if row else None


def skip_reason(host):
    return f"Pominięto pobranie strony. Zaufana domena w bazie: {host}."
