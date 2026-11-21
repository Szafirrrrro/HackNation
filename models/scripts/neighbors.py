"""Przykład liczenia na cechach: najbliżsi sąsiedzi każdej reklamy wg każdej metody.

    python scripts/neighbors.py out/features/<dataset_id> [--k 3]

Zapisuje <dir>/analysis/neighbors.md i neighbors.json. To narzędzie do porównania modeli
(która metoda grupuje sensownie), nie silnik decyzji z MVP - progi nie są tu ustalane.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
sys.path.insert(0, "/app/common")
from features_lib import FeatureStore, hamming_hex  # noqa: E402


def ad_label(fs, a):
    src = fs.ads.get(a, {})
    ref = src.get("source", {}).get("ad_ref") or src.get("image_path") or ""
    return f"{a} ({ref})" if ref else a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--k", type=int, default=3)
    args = ap.parse_args()
    fs = FeatureStore(args.root)
    cj = fs.root / "corpus.json"
    ds = json.loads(cj.read_text(encoding="utf-8"))["dataset_id"] if cj.exists() else fs.root.name
    md = [f"# Najbliżsi sąsiedzi — {ds}\n",
          "Dla każdej metody wektorowej: podobieństwo reklam = max cosine między ich wektorami "
          "(w nawiasie pola, które się dopasowały). Dla hashy: minimalna odległość Hamminga "
          "(0 = identyczny obraz, 64 = maksymalnie różny).\n"]
    out = {}
    issues = [f"{r['slug']}: model nie załadował się ({r.get('load_error')})"
              for r in fs.runs() if r.get("status") == "failed"]
    issues += [f"{r['slug']}: policzono na innej wersji korpusu ({r.get('corpus_fingerprint')} != "
               f"{fs.fingerprint})" for r in fs.stale_runs()]
    if fs.dropped_rows:
        issues.append(f"pominięto {fs.dropped_rows} wierszy reklam spoza bieżącego ads.jsonl")
    if issues:
        md.append("\n**Uwagi:**\n\n" + "\n".join(f"- {i}" for i in issues) + "\n")

    for m in fs.methods():
        if not m["vector"]:
            continue
        ids, S, best = fs.ad_similarity(m["method_version"], m["field"])
        if len(ids) < 2:
            continue
        key = f"{m['method_version']} :: {m['field']}"
        md.append(f"\n## {key}\n")
        md.append(f"{len(ids)} reklam z wektorem, {m['ok']} wektorów.\n")
        md.append("| reklama | sąsiad | cos | dopasowane pola |\n|---|---|---|---|")
        out[key] = {}
        for i, a in enumerate(ids):
            order = [j for j in S[i].argsort()[::-1] if j != i][:args.k]
            out[key][a] = []
            for rank, j in enumerate(order):
                l, r = best[(i, j)]
                fields = f"{l['source_field']} ↔ {r['source_field']}"
                out[key][a].append({"neighbor": ids[j], "cos": round(float(S[i, j]), 4),
                                    "left": l["source_field"], "right": r["source_field"]})
                md.append(f"| {ad_label(fs, a) if rank == 0 else ''} | {ad_label(fs, ids[j])} | "
                          f"{S[i, j]:.3f} | {fields} |")

    for field in ("image.phash", "image.dhash"):
        rows = fs.rows(field=field)
        if len(rows) < 2:
            continue
        md.append(f"\n## {field} (Hamming)\n")
        md.append("| reklama | najbliższa | bity różnicy |\n|---|---|---|")
        out[field] = {}
        for r in rows:
            cands = [(hamming_hex(r["value"], o["value"]), o["ad_id"]) for o in rows
                     if o["ad_id"] != r["ad_id"]]
            d, other = min(cands)
            out[field][r["ad_id"]] = {"neighbor": other, "hamming": d}
            md.append(f"| {ad_label(fs, r['ad_id'])} | {ad_label(fs, other)} | {d} |")

    dst = fs.root / "analysis"
    dst.mkdir(exist_ok=True)
    (dst / "neighbors.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (dst / "neighbors.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"zapisano {dst}/neighbors.md")


if __name__ == "__main__":
    main()
