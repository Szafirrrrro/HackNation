"""Trusted domains derived in memory from the limited local Tranco ranking."""
from __future__ import annotations

import csv
import os
from functools import lru_cache
from pathlib import Path

from .domain_policy import MULTI_TENANT_HOSTS, NEVER_TRUST_BY_RANK, REGIONAL_WILDCARDS

MAX_RANK = 10_000

DATA = Path(__file__).resolve().parent.parent / "data"


def read_list(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = (ln.split("#", 1)[0].strip().lower() for ln in path.read_text(encoding="utf-8").splitlines())
    return [ln for ln in lines if ln]


def read_tranco(path: Path) -> list[str]:
    out = []
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.reader(fh):
            if len(row) < 2 or not row[0].strip().isdigit():
                continue  # nagłówek albo pusty wiersz
            if 0 < int(row[0]) <= MAX_RANK:
                out.append(row[1].strip().lower())
    return out


def psl_private(path: Path | None) -> set[str]:
    """Wpisy z sekcji PRIVATE DOMAINS listy Public Suffix List (bez '*.' i '!')."""
    if path is None:
        try:
            path = default_psl_path()
        except ImportError as exc:
            raise RuntimeError("Brak publicsuffixlist. Zainstaluj graph/requirements-app.txt.") from exc
    if path is None or not path.exists():
        raise RuntimeError("Brak Public Suffix List: pip install publicsuffixlist albo podaj --psl public_suffix_list.dat")
    out, inside = set(), False
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if "===BEGIN PRIVATE DOMAINS===" in ln:
            inside = True
        elif "===END PRIVATE DOMAINS===" in ln:
            break
        elif inside and ln and not ln.startswith("//"):
            out.add(ln.lstrip("*.!").lower())
    return out


def icann_suffixes(path: Path | None) -> set[str]:
    """Sufiksy rejestrów (co.uk, bank.in): sam sufiks nigdy nie jest domeną z rankingu."""
    path = path or default_psl_path()
    out = set()
    for ln in path.read_text(encoding="utf-8").splitlines():
        if "===BEGIN PRIVATE DOMAINS===" in ln:
            break
        if ln.strip() and not ln.startswith("//"):
            out.add(ln.strip().lstrip("*.!").lower())
    return out


def build_trusted(tranco: Path, manual: Path, cert: Path, psl: Path | None = None) -> frozenset[str]:
    platforms = psl_private(psl)  # zgłasza też brak pliku PSL
    # Sufiks rejestru odpada tylko z rankingu; ręczny wpis (gov.pl) jest świadomą decyzją.
    candidates = (set(read_tranco(tranco)) - icann_suffixes(psl)) | set(read_list(manual))
    # Wykluczenia są dokładne: ani docs.google.com, ani wpis PSL pro.typeform.com nie usuwa rodzica.
    # Najemcę pod zaufanym rodzicem chroni najdłuższy sufiks w card.is_trusted.
    # Tylko blokada CERT obejmuje także subdomeny.
    excluded = platforms | MULTI_TENANT_HOSTS | NEVER_TRUST_BY_RANK
    blocked = set(read_list(cert))
    return frozenset(d for d in candidates - excluded if not any(
        ".".join(d.split(".")[k:]) in blocked for k in range(len(d.split(".")) - 1)))


def _stamp(path: Path):
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_mtime_ns, stat.st_size


@lru_cache(maxsize=1)
def _load_override(path: str, stamp) -> frozenset[str]:
    return frozenset(read_list(Path(path)))


@lru_cache(maxsize=1)
def _load_sources(paths: tuple[str, ...], stamps: tuple) -> frozenset[str]:
    return build_trusted(*(Path(p) for p in paths))


@lru_cache(maxsize=1)
def default_psl_path() -> Path:
    import publicsuffixlist
    paths = sorted(Path(publicsuffixlist.__file__).parent.glob("*.dat"))
    if not paths:
        raise RuntimeError("Brak Public Suffix List w pakiecie publicsuffixlist.")
    return paths[0]


@lru_cache(maxsize=2)
def _load_rules(path: str, stamp) -> tuple[frozenset[str], frozenset[str]]:
    exact, wildcard, inside = set(), set(), False
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if "===BEGIN PRIVATE DOMAINS===" in ln:
            inside = True
        elif "===END PRIVATE DOMAINS===" in ln:
            break
        elif inside and ln and not ln.startswith(("//", "!")):
            if ln.startswith("*."):
                wildcard.add(ln[2:].lower())
            else:
                exact.add(ln.lower())
    return frozenset(exact | wildcard), frozenset(wildcard & REGIONAL_WILDCARDS)


def platform_rules() -> tuple[frozenset[str], frozenset[str]]:
    """(sufiksy platform, wildcardy regionalne). region.run.app jest wspólny, usługa pod nim nie.

    Własna lista przez FTF_TRUSTED_DOMAINS działa także bez pakietu PSL, wtedy bez tych reguł.
    Domyślna lista zgłasza brak pakietu w load_trusted.
    """
    try:
        path = default_psl_path()
    except ImportError:
        return frozenset(), frozenset()
    return _load_rules(str(path), _stamp(path))


@lru_cache(maxsize=2)
def _load_blocked(path: str, stamp) -> frozenset[str]:
    return frozenset(read_list(Path(path)))


def cert_blocked() -> frozenset[str]:
    path = DATA / "cert_domains.txt"
    return _load_blocked(str(path), _stamp(path))


def load_trusted(path: str | None = None) -> frozenset[str]:
    """Cache the derived set; explicit path/env retains the custom text-list API."""
    override = path or os.getenv("FTF_TRUSTED_DOMAINS")
    if override:
        source = Path(override).resolve()
        return _load_override(str(source), _stamp(source))
    try:
        psl = default_psl_path()
    except ImportError as exc:
        raise RuntimeError("Brak publicsuffixlist. Zainstaluj graph/requirements-app.txt.") from exc
    paths = (DATA / "tranco_46YVX.csv", DATA / "trusted_manual.txt",
             DATA / "cert_domains.txt", psl)
    return _load_sources(tuple(str(p.resolve()) for p in paths), tuple(_stamp(p) for p in paths))
