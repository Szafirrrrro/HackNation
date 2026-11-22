"""Próba benchmarku: pakiety kart reklam (capture-v1) -> korpus v0 dla laboratorium.

    python3 models/benchmark/make_corpus.py <wyjście> <katalog_stanu> [<katalog_stanu> ...]
        [--subset 100] [--seed 20261122] [--subset-only]

<katalog_stanu> zawiera captures/<id>/{extracted.json, ad/card.json, ad/screenshot-1.png}.
Wynik (trzymaj w models/data/, poza Gitem):
  <wyjście>/manifest.json, ads.jsonl, media/      korpus v0 czytany przez extract.sh i bench.sh
  <wyjście>/benchmark_meta.jsonl                  nadawca i domeny docelowe (ślad zewnętrzny)
  <wyjście>/benchmark_sample.json                 liczniki: odrzucenia, duplikaty, skład
  <wyjście>-subset/                               losowy podzbiór (--subset) w tym samym formacie

Odrzucamy karty bez zrzutu i z wycofaną kreacją (zrzut pokazuje tylko komunikat platformy),
powtórzenia tego samego ID emisji oraz kolejne reklamy o identycznym pliku zrzutu (SHA-256).
Wymaga tylko biblioteki standardowej.
"""
import argparse
import hashlib
import json
import random
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

PLATFORM_HOSTS = ("facebook.com", "fb.com", "fb.me", "instagram.com", "messenger.com", "m.me",
                  "whatsapp.com", "wa.me", "meta.com", "threads.net", "threads.com")


def domain(url: str) -> str | None:
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    if not host or any(host == p or host.endswith("." + p) for p in PLATFORM_HOSTS):
        return None
    return host


def read_packets(states):
    for state in states:
        for packet in sorted(Path(state, "captures").glob("*/extracted.json")):
            try:
                ext = json.loads(packet.read_text(encoding="utf-8"))
                card = json.loads((packet.parent / "ad" / "card.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                yield packet.parent, None, None
                continue
            yield packet.parent, ext, card


def write_corpus(out: Path, rows, description: str):
    if out.exists():
        shutil.rmtree(out)
    (out / "media").mkdir(parents=True)
    ads, meta = [], []
    for row in rows:
        shutil.copyfile(row["image"], out / row["ad"]["image_path"])
        ads.append(row["ad"])
        meta.append(row["meta"])
    (out / "manifest.json").write_text(json.dumps({
        "schema_version": "v0", "dataset_id": out.name,
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_description": description}, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, data in (("ads.jsonl", ads), ("benchmark_meta.jsonl", meta)):
        (out / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in data),
                                encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("states", nargs="+", type=Path)
    ap.add_argument("--subset", type=int, default=0)
    ap.add_argument("--seed", type=int, default=20261122)
    ap.add_argument("--subset-only", action="store_true",
                    help="zapisz tylko podzbiór; istniejący korpus główny zostaje bez zmian")
    args = ap.parse_args()

    dropped, rows, seen_ids, seen_sha = Counter(), [], set(), set()
    for packet, ext, card in read_packets(args.states):
        ad = (ext or {}).get("ad") or {}
        if not ad.get("ad_id"):
            dropped["nieczytelny pakiet lub brak ID"] += 1
            continue
        if ad["ad_id"] in seen_ids:
            dropped["powtórzone ID emisji"] += 1
            continue
        seen_ids.add(ad["ad_id"])
        image = packet / (ad.get("image_path") or "-")
        if not image.is_file():
            dropped["brak zrzutu"] += 1
            continue
        if card.get("creative_state") != "visible":
            dropped["wycofana kreacja"] += 1
            continue
        sha = hashlib.sha256(image.read_bytes()).hexdigest()
        if sha in seen_sha:
            dropped["identyczny plik zrzutu"] += 1
            continue
        seen_sha.add(sha)
        record = {k: v for k, v in ad.items() if k in ("ad_id", "source", "text", "image_origin", "text_origin")}
        record["image_path"] = f"media/{packet.name}{image.suffix.lower()}"
        domains = sorted({d for c in card.get("landing_candidates") or [] if (d := domain(c.get("url", "")))}
                         | ({d} if (d := domain(ad.get("landing_url") or "")) else set()))
        rows.append({"ad": record, "image": image,
                     "meta": {"ad_id": ad["ad_id"], "advertiser": (card.get("page_name") or "").strip() or None,
                              "landing_domains": domains, "query_phrase": card.get("query_phrase")}})
    rows.sort(key=lambda r: r["ad"]["ad_id"])

    if not args.subset_only:
        write_corpus(args.out, rows, "Próba benchmarku warstwy modeli: publiczne karty reklam, "
                                         "po deduplikacji "
                                         "(models/benchmark/make_corpus.py).")
    sample = {"ads": len(rows), "with_text": sum(1 for r in rows if (r["ad"].get("text") or "").strip()),
              "with_advertiser": sum(1 for r in rows if r["meta"]["advertiser"]),
              "with_landing_domain": sum(1 for r in rows if r["meta"]["landing_domains"]),
              "dropped": dict(dropped), "seed": args.seed}
    if args.subset:
        picked = random.Random(args.seed).sample(rows, min(args.subset, len(rows)))
        picked.sort(key=lambda r: r["ad"]["ad_id"])
        sub = args.out.with_name(args.out.name + "-subset")
        write_corpus(sub, picked, f"Losowy podzbiór {len(picked)} reklam z {args.out.name} (ziarno {args.seed}).")
        sample["subset"] = len(picked)
    (args.out / "benchmark_sample.json").write_text(json.dumps(sample, ensure_ascii=False, indent=2),
                                                    encoding="utf-8")
    print(json.dumps(sample, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
