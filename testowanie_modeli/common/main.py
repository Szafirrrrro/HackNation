"""Punkt wejścia każdego kontenera.

    python /app/common/main.py extract [--data /data] [--out /out] [--models a,b] [--threads N]
    python /app/common/main.py bench   [--data /data] [--results /results]
    python /app/common/main.py list

Ekstraktory danego kontenera są w /app/uc/models.py (lista EXTRACTORS).
`extract` = realne użycie: cechy w formacie kontraktu -> /out/<dataset_id>/.
`bench`   = tylko pomiar kosztu CPU/RAM -> /results/<use_case>.json (żadnych cech).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, "/app/uc")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from corpus import Item, load_corpus  # noqa: E402
from extractor import SCHEMA, FeatureWriter, Unavailable  # noqa: E402


def _select(exts, only: str):
    names = [s for s in (only or "").split(",") if s]
    return [e for e in exts if not names or any(n.lower() in e.name.lower() or n == e.slug
                                                for n in names)]


DERIVED_TEXT_FIELDS = {"ocr.text", "asr.text"}


def derived_text_items(out: Path) -> list[Item]:
    """Tekst z OCR/ASR z wcześniejszych ekstrakcji (dziedziczy origin_id obrazu/nagrania)."""
    items = []
    for f in sorted((out / "features").glob("*.jsonl")) if (out / "features").exists() else []:
        for line in f.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r["status"] == "ok" and r["field"] in DERIVED_TEXT_FIELDS and (r["value"] or "").strip():
                items.append(Item(r["ad_id"], r["origin_id"], f"{r['field']}@{r['method_version']}",
                                  "text", text=r["value"]))
    return items


def cmd_extract(args, exts):
    from bench import cpu_seconds, set_threads
    corpus = load_corpus(args.data)
    out = Path(args.out) / corpus.dataset_id
    out.mkdir(parents=True, exist_ok=True)
    with (out / "ads.jsonl").open("w", encoding="utf-8") as f:
        for a in corpus.ads:
            f.write(json.dumps(a.record, ensure_ascii=False) + "\n")
    (out / "corpus.json").write_text(json.dumps({
        "schema": SCHEMA, "dataset_id": corpus.dataset_id, "mode": corpus.mode,
        "corpus_root": os.environ.get("CORPUS_HOST_PATH", str(corpus.root)),
        "n_ads": len(corpus.ads), "report": corpus.report,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    threads = args.threads or os.cpu_count() or 1
    for ext in exts:
        items = corpus.items(ext.modality)
        if ext.consumes_derived_text:
            items += derived_text_items(out)
        print(f"== {ext.name}: {len(items)} wejść ({ext.modality}), wątki={threads}", flush=True)
        set_threads(threads)
        w = FeatureWriter(out, ext)
        covered = {it.ad_id for it in items}
        for a in corpus.ads:
            if a.ad_id not in covered:
                w.unavailable(a.ad_id, None, None, f"no_{ext.modality}_input")
        c0, t0 = cpu_seconds(), time.time()
        ext.load(threads)
        load_s = time.time() - t0
        errors = 0
        for it in items:
            try:
                w.add(it, ext.extract(it))
            except Unavailable as e:
                w.unavailable(it.ad_id, it.origin_id, it.source_field, str(e))
            except Exception as e:  # noqa: BLE001 - jeden zły plik nie zatrzymuje ekstrakcji
                errors += 1
                traceback.print_exc()
                w.unavailable(it.ad_id, it.origin_id, it.source_field,
                              f"error: {type(e).__name__}: {e}")
        meta = w.close({"dataset_id": corpus.dataset_id, "n_inputs": len(items),
                        "errors": errors, "threads": threads, "load_s": round(load_s, 2),
                        "cpu_s_total": round(cpu_seconds() - c0, 2),
                        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
        print(json.dumps({k: meta[k] for k in ("slug", "rows_ok", "rows_unavailable",
                                                 "duration_s", "vector_fields")},
                         ensure_ascii=False), flush=True)
    print(f"cechy zapisane w {out}", flush=True)


def main():
    from models import EXTRACTORS
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["extract", "bench", "list"])
    ap.add_argument("--data", default=os.environ.get("DATA_DIR", "/data"))
    ap.add_argument("--out", default="/out")
    ap.add_argument("--results", default=os.environ.get("RESULTS_DIR", "/results"))
    ap.add_argument("--models", default=os.environ.get("MODELS", ""))
    ap.add_argument("--threads", type=int, default=int(os.environ.get("THREADS", "0") or 0))
    args = ap.parse_args()
    exts = _select(EXTRACTORS, args.models)

    if args.mode == "list":
        for e in exts:
            print(json.dumps({"name": e.name, "slug": e.slug, "use_case": e.use_case,
                              "modality": e.modality, "method_version": e.method_version,
                              "license": e.license}, ensure_ascii=False))
    elif args.mode == "extract":
        cmd_extract(args, exts)
    else:
        from bench import run_benchmark
        run_benchmark(exts, load_corpus(args.data), Path(args.results))


if __name__ == "__main__":
    main()
