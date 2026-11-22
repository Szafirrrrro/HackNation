"""Łączy wyniki reverse-SynthID i Effort w jedną tabelę (wywoływany przez provenance.sh).

  provenance_report.py unflagged <katalog cech>         -> ID obrazów bez znaku SynthID, po przecinku
  provenance_report.py report <katalog cech> <próg>     -> provenance.csv, provenance.json i podsumowanie

Tylko biblioteka standardowa: działa na hoście, poza kontenerami.
"""
import csv
import json
import sys
from pathlib import Path

SYNTHID = "ai_generated_reverse_synthid_v4"
EFFORT = "aigi_effort_effort_clip_l14"


def rows(ds: Path, slug: str) -> dict:
    """ad_id -> wiersz cechy; brak pliku = model nie był uruchomiony."""
    f = ds / "features" / f"{slug}.jsonl"
    if not f.exists():
        return {}
    out = {}
    for line in f.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("source_field") in (None, "image_path"):
            out[r["ad_id"]] = r
    return out


def label(path: str):
    """Etykieta z nazwy katalogu: .../ai/... albo .../real/...; inaczej brak."""
    parts = {p.lower() for p in Path(path).parts[:-1]}
    if "ai" in parts and "real" not in parts:
        return "ai"
    if "real" in parts and "ai" not in parts:
        return "real"
    return None


def table(ds: Path, threshold: float) -> list[dict]:
    syn, eff = rows(ds, SYNTHID), rows(ds, EFFORT)
    out = []
    for ad_id, s in syn.items():
        if not s.get("source_ref"):
            continue  # pozycja bez obrazu (np. plik tekstowy w luźnym katalogu)
        path = (s.get("source_ref") or {}).get("value") or ad_id
        sv = s["value"] if s["status"] == "ok" else None
        e = eff.get(ad_id)
        ev = e["value"] if e and e["status"] == "ok" else None
        watermark = bool(sv and sv.get("watermarked"))
        prob = ev.get("fake_prob") if ev else None
        if watermark:
            verdict, by = "ai", "synthid"
        elif prob is not None and prob >= threshold:
            verdict, by = "ai", "effort"
        elif sv is None or prob is None:
            verdict, by = "brak wyniku", ""
        else:
            verdict, by = "nieoznaczony", ""
        out.append({"path": path, "label": label(path) or "", "verdict": verdict, "flagged_by": by,
                    "synthid_watermarked": "" if sv is None else watermark,
                    "synthid_confidence": "" if sv is None else sv.get("confidence"),
                    "effort_fake_prob": "" if prob is None else prob, "ad_id": ad_id})
    return sorted(out, key=lambda r: r["path"])


def frac(n, of):
    return f"{n}/{of}" + (f" ({100 * n / of:.1f}%)" if of else "")


def report(ds: Path, threshold: float) -> int:
    t = table(ds, threshold)
    if not t:
        print("brak obrazów z wynikiem SynthID", file=sys.stderr)
        return 1
    with open(ds / "provenance.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(t[0]))
        w.writeheader()
        w.writerows(t)
    n = len(t)
    by_syn = sum(r["flagged_by"] == "synthid" for r in t)
    by_eff = sum(r["flagged_by"] == "effort" for r in t)
    missing = sum(r["verdict"] == "brak wyniku" for r in t)
    summary = {"images": n, "effort_threshold": threshold, "flagged_by_synthid": by_syn,
               "flagged_by_effort": by_eff, "not_flagged": n - by_syn - by_eff - missing, "no_result": missing}
    print(f"\nobrazy: {n}\noznaczone przez SynthID: {frac(by_syn, n)}\n"
          f"oznaczone przez Effort (fake_prob >= {threshold}): {frac(by_eff, n - by_syn)} nieoznaczonych przez SynthID\n"
          f"nieoznaczone: {frac(summary['not_flagged'], n)}" + (f"\nbrak wyniku: {missing}" if missing else ""))
    lab = [r for r in t if r["label"]]
    if lab:
        ai = [r for r in lab if r["label"] == "ai"]
        real = [r for r in lab if r["label"] == "real"]
        hit = {"SynthID": lambda r: r["synthid_watermarked"] is True,
               # Effort widzi tylko obrazy nieoznaczone przez SynthID, więc jego mianownik jest mniejszy
               "Effort": lambda r: r["flagged_by"] == "effort",
               "razem": lambda r: r["verdict"] == "ai"}
        seen = {"SynthID": lambda r: r["synthid_watermarked"] != "",
                "Effort": lambda r: r["effort_fake_prob"] != "",
                "razem": lambda r: r["verdict"] != "brak wyniku"}
        summary["labelled"] = {"ai": len(ai), "real": len(real)}
        print(f"\nz etykietą: {len(ai)} ai, {len(real)} real\n{'':10}{'wykryte AI':>22}{'fałszywe alarmy':>22}")
        for name in hit:
            d = (sum(hit[name](r) for r in ai), sum(seen[name](r) for r in ai))
            fa = (sum(hit[name](r) for r in real), sum(seen[name](r) for r in real))
            summary["labelled"][name] = {"detected_ai": list(d), "false_alarms": list(fa)}
            print(f"{name:10}{frac(*d):>22}{frac(*fa):>22}")
    (ds / "provenance.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\ntabela: {ds / 'provenance.csv'}")
    return 0


def main() -> int:
    cmd, ds = sys.argv[1], Path(sys.argv[2])
    if cmd == "unflagged":
        syn = rows(ds, SYNTHID)
        if not syn:
            print(f"brak wyniku SynthID w {ds}", file=sys.stderr)
            return 1
        # do Effort idą też obrazy, na których SynthID zawiódł: brak znaku nie jest rozstrzygnięciem
        print(",".join(a for a, r in syn.items()
                       if not (r["status"] == "ok" and r["value"].get("watermarked"))
                       and r.get("source_ref")))
        return 0
    if cmd == "report":
        return report(ds, float(sys.argv[3]))
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
