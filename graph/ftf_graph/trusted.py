"""Trusted domains derived in memory from the complete local Tranco ranking."""
from __future__ import annotations

import csv
import os
from functools import lru_cache
from pathlib import Path

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


def ancestors(domains: set[str]) -> set[str]:
    """Każdy wpis i wszystkie domeny nad nim (bez samej końcówki .com/.pl): s3.amazonaws.com ->
    {s3.amazonaws.com, amazonaws.com}."""
    out = set()
    for d in domains:
        parts = d.split(".")
        for k in range(len(parts) - 1):
            out.add(".".join(parts[k:]))
    return out


def build_trusted(tranco: Path, manual: Path, cert: Path, psl: Path | None = None) -> frozenset[str]:
    candidates = set(read_tranco(tranco)) | set(read_list(manual))
    return frozenset(candidates - ancestors(psl_private(psl)) - set(read_list(cert)))


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
