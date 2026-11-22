"""Tabela wyników Effort dla katalogu obrazów (wywoływany przez provenance.sh).

  provenance_report.py <katalog cech> <próg> [<plik wag>]   -> provenance.csv, provenance.json i podsumowanie

Tylko biblioteka standardowa: działa na hoście, poza kontenerami.
"""
import csv
import json
import sys
from pathlib import Path

EFFORT = "aigi_effort_effort_clip_l14"


def rows(ds: Path) -> list[dict]:
    f = ds / "features" / f"{EFFORT}.jsonl"
    if not f.exists():
        return []
    out = [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
    # pozycje bez source_ref nie mają obrazu (np. plik tekstowy w luźnym katalogu)
    return [r for r in out if r.get("source_ref")]


def label(path: str) -> str:
    """Etykieta z nazwy katalogu: .../ai/... albo .../real/...; inaczej brak."""
    parts = {p.lower() for p in Path(path).parts[:-1]}
    if "ai" in parts and "real" not in parts:
        return "ai"
    if "real" in parts and "ai" not in parts:
        return "real"
    return ""


def table(ds: Path, threshold: float) -> list[dict]:
    out = []
    for r in rows(ds):
        path = r["source_ref"].get("value") or r["ad_id"]
        prob = (r.get("value") or {}).get("fake_prob") if r["status"] == "ok" else None
        if prob is None:
            verdict = "brak wyniku"
        else:
            verdict = "ai" if prob >= threshold else "nieoznaczony"
        out.append({"path": path, "label": label(path), "verdict": verdict,
                    "effort_fake_prob": "" if prob is None else prob, "ad_id": r["ad_id"]})
    return sorted(out, key=lambda r: r["path"])


def frac(n, of):
    return f"{n}/{of}" + (f" ({100 * n / of:.1f}%)" if of else "")


def report(ds: Path, threshold: float, weights: str) -> int:
    t = table(ds, threshold)
    if not t:
        print(f"brak wyników Effort w {ds}", file=sys.stderr)
        return 1
    with open(ds / "provenance.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(t[0]))
        w.writeheader()
        w.writerows(t)
    scored = [r for r in t if r["verdict"] != "brak wyniku"]
    flagged = sum(r["verdict"] == "ai" for r in scored)
    summary = {"images": len(t), "effort_weights": weights, "effort_threshold": threshold,
               "flagged": flagged, "not_flagged": len(scored) - flagged, "no_result": len(t) - len(scored)}
    print(f"\nobrazy: {len(t)}\noznaczone jako AI (fake_prob >= {threshold}): {frac(flagged, len(scored))}"
          + (f"\nbrak wyniku: {summary['no_result']}" if summary["no_result"] else ""))
    ai = [r for r in scored if r["label"] == "ai"]
    real = [r for r in scored if r["label"] == "real"]
    if ai or real:
        d = sum(r["verdict"] == "ai" for r in ai)
        fa = sum(r["verdict"] == "ai" for r in real)
        # ai/real liczą obrazy z wynikiem; pozostałe z etykietą są w labelled_no_result
        summary["labelled"] = {"ai": len(ai), "real": len(real), "detected_ai": d, "false_alarms": fa,
                               "labelled_no_result": sum(bool(r["label"]) for r in t) - len(ai) - len(real)}
        print(f"wykryte AI: {frac(d, len(ai))}\nfałszywe alarmy: {frac(fa, len(real))}")
    (ds / "provenance.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\ntabela: {ds / 'provenance.csv'}")
    return 0


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    return report(Path(sys.argv[1]), float(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else "")


if __name__ == "__main__":
    sys.exit(main())
