"""Punkt wejścia każdego kontenera.

    python /app/common/main.py extract [--data /data] [--out /out] [--models a,b] [--threads N]
    python /app/common/main.py bench   [--data /data] [--results /results]
    python /app/common/main.py list

Ekstraktory danego kontenera są w /app/uc/models.py (lista EXTRACTORS).
`extract` = realne użycie: cechy w formacie kontraktu -> /out/<dataset_id>/.
`bench`   = tylko pomiar kosztu CPU/RAM -> /results/<use_case>.json (żadnych cech).
Kod wyjścia `extract` jest niezerowy, gdy któryś model nie dał się załadować.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, "/app/uc")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from corpus import Item, load_corpus  # noqa: E402
from extractor import SCHEMA, FeatureWriter, Unavailable, _atomic_write  # noqa: E402


PROFILES = {"default": {"default"}, "all": {"default", "on_demand"}}


def _select(exts, only: str, profile: str = "default"):
    """Jawne MODELS ma pierwszeństwo przed profilem; inaczej wybór wg pola stage."""
    names = [s for s in (only or "").split(",") if s]
    if names:
        return [e for e in exts if any(n.lower() in e.name.lower() or n == e.slug for n in names)]
    if profile not in PROFILES:
        sys.exit(f"nieznany PROFILE={profile}; dostępne: {', '.join(PROFILES)}")
    known = set().union(*PROFILES.values())
    if bad := [e.name for e in exts if e.stage not in known]:
        sys.exit(f"nieznany stage w ekstraktorach: {', '.join(bad)}")
    return [e for e in exts if e.stage in PROFILES[profile]]


DERIVED_TEXT_FIELDS = {"ocr.text", "asr.text"}


def derived_text_items(out: Path, corpus) -> list[Item]:
    """Tekst z OCR/ASR z wcześniejszych ekstrakcji (dziedziczy origin_id obrazu/nagrania).
    Tylko dla reklam z bieżącego korpusu; ostrzega o przebiegach z innej wersji korpusu."""
    ads = {a.ad_id: a for a in corpus.ads}
    items = []
    fdir = out / "features"
    for f in sorted(fdir.glob("*.jsonl")) if fdir.exists() else []:
        run = out / "runs" / f"{f.stem}.json"
        if run.exists():
            fp = json.loads(run.read_text(encoding="utf-8")).get("corpus_fingerprint")
            if fp and fp != corpus.fingerprint:
                print(f"UWAGA: {f.name} policzono na innej wersji korpusu ({fp} != "
                      f"{corpus.fingerprint}); używam tylko wierszy obecnych reklam", flush=True)
        for line in f.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if (r["status"] == "ok" and r["field"] in DERIVED_TEXT_FIELDS and r["ad_id"] in ads
                    and (r["value"] or "").strip()):
                items.append(Item(r["ad_id"], r["origin_id"], f"{r['field']}@{r['method_version']}",
                                  "text", text=r["value"], ref=ads[r["ad_id"]].ref))
    return items


def _already_done(out: Path, ext, corpus, input_key: str) -> bool:
    """Czy runs/<slug>.json opisuje udany przebieg tej samej wersji metody i obrazu kontenera na tych samych wejściach.
    Zmiana kodu bez zmiany method_version nie jest wykrywana, dlatego RESUME jest wyłączone domyślnie."""
    try:
        run = json.loads((out / "runs" / f"{ext.slug}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    vectors = all((out / "vectors" / ext.slug / f"{field}.npy").exists() for field in run.get("vector_fields") or {})
    return (run.get("status") == "ok" and not run.get("errors") and vectors
            and run.get("image_id") == os.environ.get("IMAGE_ID")
            and run.get("corpus_fingerprint") == corpus.fingerprint
            and run.get("method_version") == ext.method_version
            and run.get("input_key") == input_key
            and (out / "features" / f"{ext.slug}.jsonl").exists())


def cmd_extract(args, exts) -> int:
    from bench import cpu_seconds, set_threads
    corpus = load_corpus(args.data)
    out = Path(args.out) / corpus.dataset_id
    out.mkdir(parents=True, exist_ok=True)
    _atomic_write(out / "ads.jsonl", "".join(json.dumps(a.record, ensure_ascii=False) + "\n"
                                             for a in corpus.ads))
    _atomic_write(out / "corpus.json", json.dumps({
        "schema": SCHEMA, "dataset_id": corpus.dataset_id, "mode": corpus.mode,
        "fingerprint": corpus.fingerprint,
        "corpus_root": os.environ.get("CORPUS_HOST_PATH", str(corpus.root)),
        "n_ads": len(corpus.ads), "report": corpus.report,
    }, ensure_ascii=False, indent=2))
    if corpus.report.get("errors"):
        print(f"UWAGA: błędy importu: {json.dumps(corpus.report['errors'], ensure_ascii=False)}",
              flush=True)

    threads = args.threads or os.cpu_count() or 1
    only = {s for s in os.environ.get("ONLY_ADS", "").split(",") if s}
    unknown = only - {a.ad_id for a in corpus.ads}
    if unknown:
        print(f"UWAGA: ONLY_ADS zawiera {len(unknown)} ID spoza korpusu", flush=True)
    failed = 0
    if not exts:
        print("brak ekstraktorów w tym kontenerze dla wybranego profilu/MODELS", flush=True)
    for ext in exts:
        items = corpus.items(ext.modality)
        if ext.consumes_derived_text and os.environ.get("DERIVED_TEXT", "1") != "0":
            items += derived_text_items(out, corpus)
        if only:  # ONLY_ADS: drogi model na części korpusu; pozostałe reklamy dostają "not_selected"
            items = [it for it in items if it.ad_id in only]
        # odcisk zestawu wejść: RESUME=1 pomija model, który ma już udany wynik dla dokładnie tych wejść
        input_key = hashlib.sha256("\n".join(sorted(
            f"{it.ad_id}|{it.source_field}" for it in items)).encode()).hexdigest()[:16]
        if os.environ.get("RESUME") == "1" and _already_done(out, ext, corpus, input_key):
            print(f"== {ext.name}: pominięty (RESUME=1, wynik aktualny)", flush=True)
            continue
        print(f"== {ext.name}: {len(items)} wejść ({ext.modality}), wątki={threads}", flush=True)
        set_threads(threads)
        w = FeatureWriter(out, ext)
        covered = {it.ad_id for it in items}
        for a in corpus.ads:
            if a.ad_id not in covered:
                w.unavailable(a.ad_id, None, None, "not_selected" if only and a.ad_id not in only
                              else corpus.missing_reason(a, ext.modality))
        c0, t0 = cpu_seconds(), time.time()
        load_error = None
        try:
            ext.load(threads)
        except Exception as e:  # noqa: BLE001 - model nie działa: zapisz przyczynę, idź dalej
            traceback.print_exc()
            load_error = f"model_load_error: {type(e).__name__}: {e}"
            failed += 1
        load_s = time.time() - t0
        errors = 0
        seen, reused = {}, 0   # identyczny tekst liczymy raz; wynik zależy tylko od treści
        for it in items:
            if load_error:
                w.unavailable(it.ad_id, it.origin_id, it, load_error)
                continue
            try:
                if ext.modality == "text" and it.text in seen:
                    reused += 1
                    w.add(it, seen[it.text])
                    continue
                outs = ext.extract(it)
                if ext.modality == "text":
                    seen[it.text] = outs
                w.add(it, outs)
            except Unavailable as e:
                w.unavailable(it.ad_id, it.origin_id, it, str(e))
            except Exception as e:  # noqa: BLE001 - jeden zły plik nie zatrzymuje ekstrakcji
                errors += 1
                traceback.print_exc()
                w.unavailable(it.ad_id, it.origin_id, it, f"error: {type(e).__name__}: {e}")
        meta = w.close({"status": "failed" if load_error else "ok", "load_error": load_error,
                        "dataset_id": corpus.dataset_id, "corpus_fingerprint": corpus.fingerprint,
                        "n_inputs": len(items), "inputs_reused": reused, "input_key": input_key,
                        "only_ads": len(only) or None,
                        "errors": errors, "threads": threads,
                        "load_s": round(load_s, 2), "cpu_s_total": round(cpu_seconds() - c0, 2),
                        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
        print(json.dumps({k: meta[k] for k in ("slug", "status", "rows_ok", "rows_unavailable",
                                                 "errors", "duration_s", "vector_fields")},
                         ensure_ascii=False), flush=True)
    print(f"cechy zapisane w {out}", flush=True)
    return 1 if failed else 0


def main():
    from models import EXTRACTORS
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["extract", "bench", "list"])
    ap.add_argument("--data", default=os.environ.get("DATA_DIR", "/data"))
    ap.add_argument("--out", default="/out")
    ap.add_argument("--results", default=os.environ.get("RESULTS_DIR", "/results"))
    ap.add_argument("--models", default=os.environ.get("MODELS", ""))
    ap.add_argument("--threads", type=int, default=int(os.environ.get("THREADS", "0") or 0))
    # ekstrakcja domyślnie liczy profil "default"; benchmark mierzy wszystko (do decyzji)
    ap.add_argument("--profile", default=os.environ.get("PROFILE", ""))
    args = ap.parse_args()
    profile = args.profile or ("all" if args.mode in ("bench", "list") else "default")
    exts = _select(EXTRACTORS, args.models, profile)

    if args.mode == "list":
        for e in exts:
            print(json.dumps({"name": e.name, "slug": e.slug, "use_case": e.use_case,
                              "modality": e.modality, "stage": e.stage,
                              "method_version": e.method_version,
                              "license": e.license}, ensure_ascii=False))
    elif args.mode == "extract":
        sys.exit(cmd_extract(args, exts))
    else:
        from bench import run_benchmark
        run_benchmark(exts, load_corpus(args.data), Path(args.results),
                      all_exts=EXTRACTORS, model_filter=args.models or
                      ("" if profile == "all" else f"profile:{profile}"))


if __name__ == "__main__":
    main()
