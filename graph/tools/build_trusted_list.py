#!/usr/bin/env python3
"""Buduje data/trusted_domains.txt — listę zaufanych domen, które NIE tworzą śladów ani węzłów w grafie.

Źródła i reguły:
  1. ranking Tranco (https://tranco-list.eu), plik CSV "pozycja,domena" — bierzemy czołówkę (--top);
  2. ręczne uzupełnienia z data/trusted_manual.txt (CDN-y, trackery, polskie serwisy);
  3. WYKLUCZAMY platformy, na których każdy może założyć własną subdomenę (blogspot.com, github.io,
     amazonaws.com, wixsite.com...). Bierzemy je z sekcji PRIVATE DOMAINS listy Public Suffix List
     (https://publicsuffix.org, plik dołączony do pakietu `publicsuffixlist`). Domena jest wykluczona,
     jeśli sama jest na tej liście albo jakikolwiek wpis z listy leży pod nią (np. s3.amazonaws.com
     wyklucza amazonaws.com). Na takich platformach nazwa subdomeny jest śladem oszusta;
  4. WYKLUCZAMY domeny z Listy Ostrzeżeń CERT Polska (--cert, plik domains.txt), jeśli jest podany.
     Pobierz:  curl -o data/cert_domains.txt https://hole.cert.pl/domains/v2/domains.txt

Użycie:
  python tools/build_trusted_list.py                                   # domyślne ścieżki, top 10 000
  python tools/build_trusted_list.py --tranco data/tranco_46YVX.csv --top 20000 --cert data/cert_domains.txt
"""
from __future__ import annotations

import argparse
import csv
import glob
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_list(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = (ln.split("#", 1)[0].strip().lower() for ln in path.read_text(encoding="utf-8").splitlines())
    return [ln for ln in lines if ln]


def read_tranco(path: Path, top: int) -> list[str]:
    out = []
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.reader(fh):
            if len(row) < 2 or not row[0].strip().isdigit():
                continue  # nagłówek albo pusty wiersz
            if int(row[0]) > top:
                break
            out.append(row[1].strip().lower())
    return out


def psl_private(path: Path | None) -> set[str]:
    """Wpisy z sekcji PRIVATE DOMAINS listy Public Suffix List (bez '*.' i '!')."""
    if path is None:
        try:
            import publicsuffixlist  # pip install publicsuffixlist

            found = glob.glob(str(Path(publicsuffixlist.__file__).parent / "*.dat"))
            path = Path(found[0]) if found else None
        except ImportError:
            path = None
    if path is None or not path.exists():
        raise SystemExit("Brak Public Suffix List: pip install publicsuffixlist albo podaj --psl public_suffix_list.dat")
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


def main() -> int:
    p = argparse.ArgumentParser(description="Buduje listę zaufanych domen z rankingu Tranco")
    p.add_argument("--tranco", default=str(ROOT / "data" / "tranco_46YVX.csv"))
    p.add_argument("--top", type=int, default=10_000, help="ile pierwszych domen rankingu (10 000)")
    p.add_argument("--manual", default=str(ROOT / "data" / "trusted_manual.txt"))
    p.add_argument("--cert", default=str(ROOT / "data" / "cert_domains.txt"),
                   help="Lista Ostrzeżeń CERT Polska (domains.txt); pomijana, jeśli pliku nie ma")
    p.add_argument("--psl", default=None, help="public_suffix_list.dat (domyślnie z pakietu publicsuffixlist)")
    p.add_argument("--out", default=str(ROOT / "data" / "trusted_domains.txt"))
    a = p.parse_args()

    tranco = read_tranco(Path(a.tranco), a.top)
    manual = read_list(Path(a.manual))
    hosting = ancestors(psl_private(Path(a.psl) if a.psl else None))
    cert = set(read_list(Path(a.cert)))

    excluded_hosting = sorted(d for d in set(tranco) | set(manual) if d in hosting)
    excluded_cert = sorted(d for d in set(tranco) | set(manual) if d in cert)
    trusted = sorted((set(tranco) | set(manual)) - hosting - cert)

    header = [
        "# WYGENEROWANE przez tools/build_trusted_list.py — nie edytuj ręcznie (zmiany w trusted_manual.txt).",
        f"# data: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC",
        f"# źródło: {Path(a.tranco).name}, top {a.top}  +  {Path(a.manual).name}",
        f"# wykluczone platformy z treściami użytkowników (Public Suffix List, private): {len(excluded_hosting)}",
        f"# wykluczone z Listy Ostrzeżeń CERT: {len(excluded_cert)}"
        + ("" if cert else "  (brak pliku CERT — pominięto)"),
        f"# domen zaufanych: {len(trusted)}",
        "",
    ]
    Path(a.out).write_text("\n".join(header + trusted) + "\n", encoding="utf-8")
    print(f"Zapisano {len(trusted)} zaufanych domen do {a.out}")
    print(f"Wykluczone platformy hostingowe ({len(excluded_hosting)}), np.: {', '.join(excluded_hosting[:12])}")
    if cert:
        print(f"Wykluczone z Listy Ostrzeżeń CERT ({len(excluded_cert)}): {', '.join(excluded_cert[:12])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
