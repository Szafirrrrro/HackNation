"""Wspólny harness benchmarku CPU dla wszystkich kontenerów.

Każdy kontener definiuje listę modeli (obiekty ModelSpec) i woła `run_suite`.
Pomiar:
  * cgroup v2 cpu.stat (usage_usec) -> CPU-sekundy zużyte przez CAŁY kontener
    (wszystkie wątki: torch/onnx/tesseract-subprocess), niezależnie od psutil,
  * psutil (proces + dzieci) jako fallback, gdy cgroup niedostępny,
  * próbkowanie co 100 ms -> szczytowe wykorzystanie CPU (w rdzeniach) i RSS,
  * szczyt pamięci w oknie inferencji według próbnika.

Raport per model i per liczba wątków: czas ładowania, latencja p50/p95/mean,
throughput, CPU-s na element, średnie i szczytowe wykorzystanie rdzeni, RAM.
"""
from __future__ import annotations

import gc
import json
import os
import platform
import statistics
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import psutil

CGROUP = Path("/sys/fs/cgroup")
DATA = Path(os.environ.get("DATA_DIR", "/data"))
RESULTS = Path(os.environ.get("RESULTS_DIR", "/results"))


# ---------------------------------------------------------------- CPU / RAM --
def _cgroup_cpu_usec() -> int | None:
    try:
        for line in (CGROUP / "cpu.stat").read_text().splitlines():
            k, v = line.split()
            if k == "usage_usec":
                return int(v)
    except Exception:
        return None
    return None


def _cgroup_mem() -> int | None:
    try:
        return int((CGROUP / "memory.current").read_text())
    except Exception:
        return None


def _cgroup_cpu_limit() -> float | None:
    try:
        quota, period = (CGROUP / "cpu.max").read_text().split()
        if quota == "max":
            return None
        return int(quota) / int(period)
    except Exception:
        return None


def _proc_cpu_seconds() -> float:
    p = psutil.Process()
    t = p.cpu_times()
    total = t.user + t.system + t.children_user + t.children_system
    for c in p.children(recursive=True):
        try:
            ct = c.cpu_times()
            total += ct.user + ct.system
        except psutil.Error:
            pass
    return total


def cpu_seconds() -> float:
    u = _cgroup_cpu_usec()
    return u / 1e6 if u is not None else _proc_cpu_seconds()


def rss_bytes() -> int:
    m = _cgroup_mem()
    if m is not None:
        return m
    p = psutil.Process()
    total = p.memory_info().rss
    for c in p.children(recursive=True):
        try:
            total += c.memory_info().rss
        except psutil.Error:
            pass
    return total


class Sampler:
    """Wątek próbkujący wykorzystanie CPU (rdzenie) i RAM co `interval` s."""

    def __init__(self, interval: float = 0.1):
        self.interval = interval
        self.samples_cores: list[float] = []
        self.peak_rss = 0
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        last_c, last_t = cpu_seconds(), time.perf_counter()
        while not self._stop.wait(self.interval):
            c, t = cpu_seconds(), time.perf_counter()
            if t > last_t:
                self.samples_cores.append((c - last_c) / (t - last_t))
            last_c, last_t = c, t
            self.peak_rss = max(self.peak_rss, rss_bytes())

    def __enter__(self):
        self.peak_rss = rss_bytes()
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        self._t.join()


# ------------------------------------------------------------------ threads --
def set_threads(n: int):
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                "OMP_THREAD_LIMIT", "NUMEXPR_NUM_THREADS"):
        os.environ[var] = str(n)
    try:
        import torch
        torch.set_num_threads(n)
    except Exception:
        pass
    try:
        import cv2
        cv2.setNumThreads(n)
    except Exception:
        pass


def thread_counts() -> list[int]:
    raw = os.environ.get("BENCH_THREADS", "1,all")
    ncpu = os.cpu_count() or 1
    lim = _cgroup_cpu_limit()
    if lim:
        ncpu = max(1, min(ncpu, int(round(lim))))
    out = []
    for tok in raw.split(","):
        tok = tok.strip()
        n = ncpu if tok == "all" else int(tok)
        if n not in out:
            out.append(n)
    return out


# -------------------------------------------------------------------- spec --
@dataclass
class ModelSpec:
    name: str                       # np. "insightface/buffalo_l"
    use_case: str                   # np. "face"
    license: str
    load: Callable[[int], Any]      # load(threads) -> model
    infer: Callable[[Any, Any], Any]  # infer(model, item) -> wynik (JSON-able)
    inputs: Callable[[], list]      # lista elementów (ścieżki / teksty)
    notes: str = ""
    item_label: Callable[[Any], str] = field(default=lambda x: str(x))


def _pct(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return s[k]


def _bench_one(spec: ModelSpec, threads: int, warmup: int, repeats: int,
               max_items: int) -> dict:
    set_threads(threads)
    items = spec.inputs()[:max_items]
    if not items:
        return {"model": spec.name, "threads": threads, "skipped": "brak danych wejściowych"}

    gc.collect()
    mem0 = rss_bytes()
    c0, t0 = cpu_seconds(), time.perf_counter()
    model = spec.load(threads)
    load_s = time.perf_counter() - t0
    load_cpu = cpu_seconds() - c0
    mem_loaded = rss_bytes()

    for it in items[:warmup]:
        spec.infer(model, it)

    lat = []
    outputs = {}
    with Sampler() as smp:
        c1, t1 = cpu_seconds(), time.perf_counter()
        for _ in range(repeats):
            for it in items:
                s = time.perf_counter()
                out = spec.infer(model, it)
                lat.append(time.perf_counter() - s)
                outputs.setdefault(spec.item_label(it), out)
        wall = time.perf_counter() - t1
        cpu = cpu_seconds() - c1

    n = len(lat)
    del model
    gc.collect()
    return {
        "model": spec.name,
        "use_case": spec.use_case,
        "license": spec.license,
        "notes": spec.notes,
        "threads": threads,
        "n_items": len(items),
        "n_runs": n,
        "load_s": round(load_s, 3),
        "load_cpu_s": round(load_cpu, 3),
        "model_ram_mb": round((mem_loaded - mem0) / 2**20, 1),
        "peak_ram_mb": round(smp.peak_rss / 2**20, 1),
        "lat_mean_ms": round(1000 * statistics.mean(lat), 1),
        "lat_p50_ms": round(1000 * _pct(lat, .5), 1),
        "lat_p95_ms": round(1000 * _pct(lat, .95), 1),
        "throughput_per_s": round(n / wall, 3) if wall else None,
        "cpu_s_per_item": round(cpu / n, 4),
        "avg_cores_used": round(cpu / wall, 2) if wall else None,
        "peak_cores_used": round(max(smp.samples_cores), 2) if smp.samples_cores else None,
        "sample_outputs": outputs,
    }


def run_suite(use_case: str, specs: list[ModelSpec]):
    warmup = int(os.environ.get("BENCH_WARMUP", "1"))
    repeats = int(os.environ.get("BENCH_REPEATS", "3"))
    max_items = int(os.environ.get("BENCH_MAX_ITEMS", "20"))
    only = [s for s in os.environ.get("BENCH_MODELS", "").split(",") if s]

    env = {
        "use_case": use_case,
        "host_cpu_count": os.cpu_count(),
        "cgroup_cpu_limit": _cgroup_cpu_limit(),
        "cgroup_measurement": _cgroup_cpu_usec() is not None,
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "threads_tested": thread_counts(),
        "model_filter": only,
        "warmup": warmup, "repeats": repeats, "max_items": max_items,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    print(f"== {use_case} :: {json.dumps(env)}", flush=True)
    results = []
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{use_case}.json"
    temporary = out.with_suffix(".json.tmp")

    def checkpoint(state):
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump({"state": state, "env": env, "results": results}, stream,
                      ensure_ascii=False, indent=2, default=str)
        temporary.replace(out)

    checkpoint("running")
    for spec in specs:
        if only and not any(o in spec.name for o in only):
            continue
        for th in thread_counts():
            print(f"-- {spec.name} threads={th}", flush=True)
            try:
                r = _bench_one(spec, th, warmup, repeats, max_items)
            except Exception as e:
                traceback.print_exc()
                r = {"model": spec.name, "use_case": use_case, "threads": th,
                     "error": f"{type(e).__name__}: {e}"}
            short = {k: v for k, v in r.items() if k != "sample_outputs"}
            print(json.dumps(short, ensure_ascii=False), flush=True)
            results.append(r)
            checkpoint("running")

    checkpoint("complete")
    print(f"zapisano {out}", flush=True)


# ------------------------------------------------------------------ inputs --
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".mp4", ".webm"}


def files(sub: str, exts: set[str]) -> list[str]:
    """Pliki z /data/<sub> (rekurencyjnie), posortowane."""
    root = DATA / sub
    if sub == "images" and not root.exists() and (DATA / "ads.jsonl").is_file():
        root = DATA / "media"
    if not root.exists():
        return []
    return sorted(str(p) for p in root.rglob("*") if p.suffix.lower() in exts)


def texts() -> list[tuple[str, str]]:
    """Stabilny identyfikator próbki i tekst, odczytane przed pomiarem."""
    root = DATA / "texts"
    if root.is_dir():
        rows = [(short_label(p), p.read_text(encoding="utf-8").strip())
                for p in sorted(root.rglob("*.txt"))]
    elif (DATA / "ads.jsonl").is_file():
        records = (json.loads(line) for line in (DATA / "ads.jsonl").read_text(encoding="utf-8").splitlines() if line.strip())
        rows = [(rec["ad_id"], (rec.get("text") or "").strip()) for rec in records]
    else:
        return []
    return [(label, value) for label, value in rows if value]


def short_label(x) -> str:
    return Path(x).relative_to(DATA).as_posix()
