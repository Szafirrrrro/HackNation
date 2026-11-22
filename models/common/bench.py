"""Wspólny harness benchmarku CPU dla wszystkich kontenerów.

Uruchamiane przez `main.py bench`. Mierzy te same ekstraktory (models.py), których używa
`main.py extract`, ale NIE zapisuje cech - tylko koszt. Wyniki -> /results/<use_case>.json.
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
from pathlib import Path

import psutil

CGROUP = Path("/sys/fs/cgroup")


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


# ---------------------------------------------------------------- benchmark --
def _pct(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return s[k]


def _bench_one(ext, items, threads: int, warmup: int, repeats: int) -> dict:
    """Mierzy jedną konfigurację. Latencja i CPU/elem liczone tylko z udanych wywołań;
    wejścia `Unavailable` (np. uszkodzony plik) są liczone osobno, a każdy inny wyjątek
    albo brak choćby jednego udanego wywołania oznacza konfigurację jako błąd."""
    if __package__:  # import jako pakiet (testy)
        from .errors import Unavailable
    else:
        from errors import Unavailable
    set_threads(threads)
    if not items:
        return {"model": ext.name, "use_case": ext.use_case, "threads": threads,
                "skipped": f"brak wejść typu {ext.modality}"}
    gc.collect()
    mem0 = rss_bytes()
    c0, t0 = cpu_seconds(), time.perf_counter()
    ext.load(threads)
    load_s = time.perf_counter() - t0
    load_cpu = cpu_seconds() - c0
    mem_loaded = rss_bytes()
    counts = {"ok": 0, "unavailable": 0, "error": 0}
    first_error = None

    def call(it):
        nonlocal first_error
        try:
            out = ext.summarize(ext.extract(it))
            return "ok", out
        except Unavailable as e:
            return "unavailable", {"unavailable": str(e)}
        except Exception as e:  # noqa: BLE001
            first_error = first_error or f"{type(e).__name__}: {e}"
            return "error", {"error": f"{type(e).__name__}: {e}"}

    for it in items[:warmup]:
        call(it)
    lat, outputs = [], {}
    cpu_ok = 0.0
    with Sampler() as smp:
        t1 = time.perf_counter()
        for _ in range(repeats):
            for it in items:
                c, s = cpu_seconds(), time.perf_counter()
                status, out = call(it)
                dt, dc = time.perf_counter() - s, cpu_seconds() - c
                counts[status] += 1
                if status == "ok":
                    lat.append(dt)
                    cpu_ok += dc
                outputs.setdefault(it.label, out)
        wall = time.perf_counter() - t1
    base = {"model": ext.name, "use_case": ext.use_case, "method_version": ext.method_version,
            "license": ext.license, "notes": ext.notes, "threads": threads,
            "n_items": len(items), "n_ok": counts["ok"], "n_unavailable": counts["unavailable"],
            "n_errors": counts["error"], "sample_outputs": outputs}
    if counts["error"]:
        return {**base, "error": f"{counts['error']} wywołań zakończonych błędem, np. {first_error}"}
    if not lat:
        return {**base, "error": "żadne wejście nie zostało przetworzone (wszystkie niedostępne)"}
    n = len(lat)
    busy = sum(lat)
    return {
        **base, "n_runs": n,
        "load_s": round(load_s, 3), "load_cpu_s": round(load_cpu, 3),
        "model_ram_mb": round((mem_loaded - mem0) / 2**20, 1),
        "peak_ram_mb": round(smp.peak_rss / 2**20, 1),
        "lat_mean_ms": round(1000 * statistics.mean(lat), 1),
        "lat_p50_ms": round(1000 * _pct(lat, .5), 1),
        "lat_p95_ms": round(1000 * _pct(lat, .95), 1),
        "throughput_per_s": round(n / busy, 3) if busy else None,
        "cpu_s_per_item": round(cpu_ok / n, 4),
        "avg_cores_used": round(cpu_ok / busy, 2) if busy else None,
        "peak_cores_used": round(max(smp.samples_cores), 2) if smp.samples_cores else None,
        "wall_s": round(wall, 3),
    }


def bench_items(corpus, modality: str, max_items: int):
    """Wejścia benchmarku: posortowane po ad_id (w luźnym katalogu = hash treści), więc próbka
    miesza podkatalogi zamiast brać pierwsze alfabetycznie (np. z jednego podkatalogu)."""
    return sorted(corpus.items(modality), key=lambda it: it.ad_id)[:max_items]


def _child_env(threads: int, model: str, out: str) -> dict:
    env = dict(os.environ)
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                "OMP_THREAD_LIMIT", "NUMEXPR_NUM_THREADS"):
        env[var] = str(threads)
    env.update(BENCH_CHILD_MODEL=model, BENCH_CHILD_THREADS=str(threads), BENCH_CHILD_OUT=out)
    return env


def _run_child(ext, threads: int) -> dict:
    """Mierzy jedną parę (ekstraktor, wątki) w świeżym podprocesie tego samego polecenia."""
    import subprocess
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        out = tf.name
    try:
        proc = subprocess.run([sys.executable] + sys.argv, env=_child_env(threads, ext.name, out))
        try:
            return json.loads(Path(out).read_text())
        except Exception:  # noqa: BLE001
            return {"model": ext.name, "use_case": ext.use_case, "threads": threads,
                    "error": f"podproces zakończony kodem {proc.returncode} (OOM?)"}
    finally:
        Path(out).unlink(missing_ok=True)


def run_benchmark(exts, corpus, results: Path, all_exts=None, model_filter: str = ""):
    """Rodzic: dla każdej pary (ekstraktor, wątki) świeży podproces (czyste pule wątków,
    czysty pomiar RAM). Dziecko: mierzy tylko swoją parę i zapisuje JSON.

    Każdy use case kontenera dostaje plik /results/<use_case>.json zapisywany atomowo po
    każdej konfiguracji (state: running -> complete), więc przerwany przebieg zachowuje
    ukończone pomiary. Use case bez modeli po filtrze dostaje pusty, ukończony zestaw z
    `model_filter` (raport odróżnia to od błędu)."""
    warmup = int(os.environ.get("BENCH_WARMUP", "1"))
    repeats = int(os.environ.get("BENCH_REPEATS", "3"))
    max_items = int(os.environ.get("BENCH_MAX_ITEMS", "20"))

    child = os.environ.get("BENCH_CHILD_MODEL")
    if child is not None:
        ext = next(e for e in exts if e.name == child)
        th = int(os.environ["BENCH_CHILD_THREADS"])
        items = bench_items(corpus, ext.modality, max_items)
        try:
            r = _bench_one(ext, items, th, warmup, repeats)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            r = {"model": ext.name, "use_case": ext.use_case, "threads": th,
                 "error": f"{type(e).__name__}: {e}"}
        Path(os.environ["BENCH_CHILD_OUT"]).write_text(json.dumps(r, ensure_ascii=False, default=str))
        return

    filt = [s for s in (model_filter or "").split(",") if s]
    env = {
        "dataset_id": corpus.dataset_id, "corpus_mode": corpus.mode, "n_ads": len(corpus.ads),
        "corpus_fingerprint": getattr(corpus, "fingerprint", None),
        "corpus_root": os.environ.get("CORPUS_HOST_PATH"),
        "image_id": os.environ.get("IMAGE_ID"), "code_rev": os.environ.get("GIT_REV"),
        "host_cpu_count": os.cpu_count(), "cgroup_cpu_limit": _cgroup_cpu_limit(),
        "cgroup_measurement": _cgroup_cpu_usec() is not None,
        "machine": platform.machine(), "python": sys.version.split()[0],
        "threads_tested": thread_counts(), "model_filter": filt,
        "warmup": warmup, "repeats": repeats, "max_items": max_items,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    print(f"== benchmark :: {json.dumps(env)}", flush=True)
    results.mkdir(parents=True, exist_ok=True)
    use_cases = list(dict.fromkeys(e.use_case for e in (all_exts or exts)))
    by_uc: dict[str, list] = {uc: [] for uc in use_cases}

    def checkpoint(uc, state):
        out = results / f"{uc}.json"
        tmp = out.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump({"state": state, "env": {"use_case": uc, **env}, "results": by_uc[uc]},
                      f, ensure_ascii=False, indent=2, default=str)
        tmp.replace(out)

    for uc in use_cases:
        checkpoint(uc, "running")
    for ext in exts:
        for th in thread_counts():
            print(f"-- {ext.name} threads={th}", flush=True)
            r = _run_child(ext, th)
            print(json.dumps({k: v for k, v in r.items() if k != "sample_outputs"},
                             ensure_ascii=False), flush=True)
            by_uc[ext.use_case].append(r)
            checkpoint(ext.use_case, "running")
    for uc in use_cases:
        checkpoint(uc, "complete")
        print(f"zapisano {results / (uc + '.json')}", flush=True)
