"""Agreguje results/<RUN>/*.json do summary.md (tabela per use case)."""
import json
import sys
from pathlib import Path

res = Path(sys.argv[1])
COLS = [("model", "model"), ("threads", "wątki"), ("load_s", "ładowanie s"),
        ("model_ram_mb", "RAM modelu MB"), ("peak_ram_mb", "szczyt RAM MB"),
        ("lat_p50_ms", "p50 ms"), ("lat_p95_ms", "p95 ms"), ("throughput_per_s", "elem/s"),
        ("cpu_s_per_item", "CPU-s/elem"), ("avg_cores_used", "śr. rdzenie"),
        ("peak_cores_used", "szczyt rdzeni")]

out = [f"# Benchmark CPU — {res.name}\n",
       "CPU-s/elem = czas CPU (wszystkie wątki kontenera, cgroup) na jeden element; "
       "to główna miara kosztu. śr. rdzenie = CPU-s / czas ścienny.\n"]
for f in sorted(res.glob("*.json")):
    d = json.loads(f.read_text())
    env = d["env"]
    out.append(f"\n## {env['use_case']}\n")
    out.append(f"limit CPU: {env['cgroup_cpu_limit']} | elementy ≤ {env['max_items']} × "
               f"{env['repeats']} powt. | pomiar cgroup: {env['cgroup_measurement']} | "
               f"{env['machine']}\n")
    out.append("| " + " | ".join(c[1] for c in COLS) + " |")
    out.append("|" + "---|" * len(COLS))
    for r in d["results"]:
        if "error" in r or "skipped" in r:
            out.append(f"| {r['model']} | {r.get('threads')} | "
                       f"**{r.get('error') or r.get('skipped')}** |" + " |" * (len(COLS) - 3))
            continue
        out.append("| " + " | ".join(str(r.get(k, "")) for k, _ in COLS) + " |")
    lic = {r["model"]: r.get("license", "") for r in d["results"] if r.get("license")}
    out.append("\nLicencje: " + "; ".join(f"{k}: {v}" for k, v in lic.items()))
    # przykładowe wyjścia (najwyżej 4 elementy na model, z pierwszego przebiegu)
    seen = set()
    for r in d["results"]:
        if r["model"] in seen or "sample_outputs" not in r:
            continue
        seen.add(r["model"])
        out.append(f"\n<details><summary>wyjścia: {r['model']}</summary>\n\n```")
        for k, v in list(r["sample_outputs"].items())[:30]:
            out.append(f"{k}: {json.dumps(v, ensure_ascii=False)[:240]}")
        out.append("```\n</details>")

(res / "summary.md").write_text("\n".join(out) + "\n", encoding="utf-8")
print("\n".join(out))
