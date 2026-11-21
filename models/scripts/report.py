"""Podsumowanie pomiarów CPU. Zachowuje poprawne wyniki częściowego przebiegu."""
import json
import math
import sys
from pathlib import Path


METRICS = {
    "n_items": "próbki", "n_runs": "pomiary", "load_s": "ładowanie s",
    "model_ram_mb": "przyrost pamięci MB", "peak_ram_mb": "szczyt próbkowany MB",
    "lat_p50_ms": "p50 ms", "lat_p95_ms": "p95 ms", "throughput_per_s": "elem/s",
    "cpu_s_per_item": "CPU-s/elem", "avg_cores_used": "śr. rdzenie",
    "peak_cores_used": "szczyt rdzeni",
}


def summarize(folder):
    tables, issues = [], []
    successes = 0
    files = sorted(folder.glob("*.json"))
    manifest = folder / "expected-suites.txt"
    failed = folder / "failed-containers.txt"
    if failed.is_file():
        for name in failed.read_text(encoding="utf-8").splitlines():
            issues.append(f"{name} — błąd uruchomienia kontenera lub zapisu logu")
    if manifest.is_file():
        expected = set(manifest.read_text(encoding="utf-8").splitlines())
        for missing in sorted(expected - {path.stem for path in files}):
            issues.append(f"{missing} — brak pliku wynikowego")
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            env = data["env"]
            if env["use_case"] != path.stem or not isinstance(data["results"], list):
                raise ValueError("niespójny format zestawu")
            if data.get("state", "complete") != "complete":
                issues.append(f"{path.name} — zestaw nieukończony, poniżej zapisane konfiguracje")
            tables.extend(["", f"## {path.stem}", "",
                           f"{env['machine']} · limit CPU {env['cgroup_cpu_limit']} · "
                           f"pomiar cgroup {env['cgroup_measurement']}", ""])
        except (ValueError, KeyError, TypeError, OSError) as exc:
            issues.append(f"{path.name} — błąd odczytu zestawu ({exc})")
            continue
        rows = data["results"]
        if not rows:
            if env.get("model_filter"):
                tables.append("Żaden model w tym zestawie nie odpowiada filtrowi.")
            else:
                issues.append(f"{path.name} — brak wyników modeli")
            continue
        headers = ["model", "wątki", *METRICS.values()]
        tables.extend(["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)])
        for i, row in enumerate(rows, start=1):
            try:
                name, threads = row["model"], row["threads"]
                if "error" in row or "skipped" in row:
                    issues.append(f"{path.stem} / {name} / {threads} — {row.get('error') or row.get('skipped')}")
                    continue
                values = [row[key] for key in METRICS]
                for key, value in zip(METRICS, values):
                    if key == "peak_cores_used" and value is None:
                        continue  # próba mogła trwać krócej niż okres próbkowania
                    if type(value) not in (int, float) or not math.isfinite(value):
                        raise ValueError(f"brak pomiaru {key}")
                if row["n_items"] <= 0 or row["n_runs"] <= 0:
                    raise ValueError("brak próbek")
            except (ValueError, KeyError, TypeError) as exc:
                issues.append(f"{path.name}, wiersz {i} — uszkodzony wynik ({exc})")
                continue
            cells = [name, threads, *values]
            tables.append("| " + " | ".join("—" if v is None else str(v) for v in cells) + " |")
            successes += 1
    if not successes:
        issues.append("Brak udanych pomiarów kosztu.")
    lines = [f"# Benchmark CPU — {folder.name}", "", f"Udane konfiguracje modelu i wątków: {successes}.",
             "Koszt obejmuje inferencję i przygotowanie zwracanego wyniku. "
             "Pełne wyjścia i licencje modeli zapisano w plikach JSON."]
    if issues:
        lines.extend(["", "## Braki i błędy", "", *[f"- {issue}" for issue in issues]])
    lines.extend(tables)
    return "\n".join(lines) + "\n", bool(issues)


if __name__ == "__main__":
    folder = Path(sys.argv[1])
    if not folder.is_dir():
        sys.exit(f"Brak katalogu wyników: {folder}")
    report, failed = summarize(folder)
    (folder / "summary.md").write_text(report, encoding="utf-8")
    print(report)
    sys.exit(int(failed))
