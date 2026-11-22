#!/usr/bin/env python3
"""Opcjonalnie eksportuje listę TXT popularnych domen, które NIE tworzą śladów ani węzłów w grafie.

To nie pełna lista hostów bez śladu: wspólne hosty i platformy dodaje reguła card.is_trusted.

Źródła i reguły:
  1. pierwsze 10 000 pozycji rankingu Tranco (https://tranco-list.eu), plik CSV "pozycja,domena", limit pozycji: 10 000;
  2. ręczne uzupełnienia z data/trusted_manual.txt (CDN-y, trackery, polskie serwisy);
  3. WYKLUCZAMY same platformy, na których każdy może założyć subdomenę (blogspot.com, wixsite.com...):
     dokładne wpisy z sekcji PRIVATE DOMAINS listy Public Suffix List, a z rankingu także sufiksy rejestrów.
     Rodzic wpisu zostaje, np. pro.typeform.com nie usuwa typeform.com;
  4. WYKLUCZAMY domeny z Listy Ostrzeżeń CERT Polska (--cert, plik domains.txt), jeśli jest podany.
     Pobierz:  curl -o data/cert_domains.txt https://hole.cert.pl/domains/v2/domains.txt

Użycie:
  python tools/build_trusted_list.py --out /tmp/trusted_domains.txt     # opcjonalny eksport
  python tools/build_trusted_list.py --tranco data/tranco_46YVX.csv --cert data/cert_domains.txt --out /tmp/trusted_domains.txt
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ftf_graph.trusted import build_trusted, psl_private, read_list, read_tranco


def main() -> int:
    p = argparse.ArgumentParser(description="Buduje listę zaufanych domen z rankingu Tranco")
    p.add_argument("--tranco", default=str(ROOT / "data" / "tranco_46YVX.csv"))
    p.add_argument("--manual", default=str(ROOT / "data" / "trusted_manual.txt"))
    p.add_argument("--cert", default=str(ROOT / "data" / "cert_domains.txt"),
                   help="Lista Ostrzeżeń CERT Polska (domains.txt); pomijana, jeśli pliku nie ma")
    p.add_argument("--psl", default=None, help="public_suffix_list.dat (domyślnie z pakietu publicsuffixlist)")
    p.add_argument("--out", required=True, help="Jawna ścieżka opcjonalnego eksportu TXT")
    a = p.parse_args()

    tranco = read_tranco(Path(a.tranco))
    manual = read_list(Path(a.manual))
    hosting = psl_private(Path(a.psl) if a.psl else None)
    cert = set(read_list(Path(a.cert)))

    excluded_hosting = sorted(d for d in set(tranco) | set(manual) if d in hosting)
    excluded_cert = sorted(d for d in set(tranco) | set(manual) if d in cert)
    trusted = sorted(build_trusted(Path(a.tranco), Path(a.manual), Path(a.cert),
                                   Path(a.psl) if a.psl else None))

    header = [
        "# WYGENEROWANE przez tools/build_trusted_list.py — nie edytuj ręcznie (zmiany w trusted_manual.txt).",
        f"# data: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC",
        f"# źródło: {Path(a.tranco).name}, ranking (limit pozycji: 10 000)  +  {Path(a.manual).name}",
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
