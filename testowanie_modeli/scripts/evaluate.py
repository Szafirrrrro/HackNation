"""Ewaluacja decyzji z tabeli laboratorium (README: „Który eksperyment…”).

Uruchamiane przez ./evaluate.sh w kontenerze tm-text (numpy, scikit-learn, OpenCV).
Czyta wyłącznie gotowe cechy (out/features/...) i etykiety ewaluacyjne - nie zmienia cech.

  obraz : warianty (kadr, róg, zmniejszenie+JPEG) jako zapytania, oryginały jako kandydaci;
          top-1/top-3 dla pHash, DINOv2, ORB (remisy liczone NA NIEKORZYŚĆ metody); dodatkowe
          trafienia względem pHash; próg pomocniczy = 10. percentyl wyników prawdziwych par
          wariant-oryginał (NIE punkt pracy) i liczba WSZYSTKICH par oryginałów z różnych grup
          tymczasowych i z tym samym screenshot_type, które go przekraczają; osobno wyniki
          rzeczywistych par tymczasowych (p3/p4, p1/p7/p15) i margines względem najwyższej
          niepowiązanej pary z tą samą ramką.
  tekst : TF-IDF char_wb 3-5 vs E5-small (prefiks "query: " po obu stronach); MRR, hit@1/@3,
          liczba zapytań z top-1 z innej grupy (fałszywe przypisania).
  OCR   : CER, pełne frazy i domeny względem ręcznej referencji (jeśli istnieje) + p95 z benchmarku.

Reguły decyzji są podpisane jako decyzje zespołu (README) - skrypt podaje propozycję, liczby i
mianowniki; przy zerowym mianowniku wynik jest „niemierzalny”.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np

sys.path.insert(0, "/app/common")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from features_lib import ORB_MATCH, FeatureStore, hamming_hex  # noqa: E402


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


def pct(a, b):
    return "niemierzalne (0)" if not b else f"{a}/{b} ({100 * a / b:.0f}%)"


def method_of(fs, use_case, field, name_sub):
    ms = [m["method_version"] for m in fs.methods() if m["use_case"] == use_case
          and m["field"] == field and name_sub in m["method_version"]]
    return ms[0] if ms else None


# --------------------------------------------------------------------- obraz --
def image_scores(fs: FeatureStore, queries, cands):
    """Słownik metoda -> macierz wyników [q, c] (większy = bardziej podobny)."""
    out = {}
    ph = {r["ad_id"]: r["value"] for r in fs.rows(field="image.phash")}
    if ph:
        out["pHash (−Hamming)"] = np.array([[-hamming_hex(ph[q], ph[c]) if q in ph and c in ph
                                             else -99 for c in cands] for q in queries], float)
    mv = method_of(fs, "image_embedding", "image.embedding", "dinov2")
    if mv:
        X, rows = fs.vectors(mv, "image.embedding")
        idx = {r["ad_id"]: i for i, r in enumerate(rows)}
        out["DINOv2-small (cos)"] = np.array([[float(X[idx[q]] @ X[idx[c]]) if q in idx and c in idx
                                               else -1 for c in cands] for q in queries])
    orb = {r["ad_id"]: r for r in fs.rows(field="image.orb")}
    if orb:
        import cv2
        cache = {}

        def des(ad):
            v = orb[ad]["value"]
            if v["array"] not in cache:
                cache[v["array"]] = np.load(fs.root / v["array"])
            return cache[v["array"]][v["key"]]
        bf = cv2.BFMatcher(cv2.NORM_HAMMING)

        def good(a, b):
            if a not in orb or b not in orb:
                return -1
            m = bf.knnMatch(des(a), des(b), k=2)
            return sum(1 for p in m if len(p) == 2 and p[0].distance < ORB_MATCH["ratio"] * p[1].distance)
        out["ORB (dobre dopasowania)"] = np.array([[good(q, c) for c in cands] for q in queries], float)
    return out


def eval_images(fs, variants, labels, frames):
    originals = sorted({v["variant_of"] for v in variants})
    queries = [v["ad_id"] for v in variants]
    truth = [originals.index(v["variant_of"]) for v in variants]
    kinds = [v["kind"] for v in variants]
    res, hits3 = {}, {}
    for name, S in image_scores(fs, queries, originals).items():
        # pozycja prawdziwego oryginału; remis liczony na niekorzyść metody (0 = jednoznacznie pierwszy)
        ranks = [int((S[i] >= S[i, t]).sum()) - 1 for i, t in enumerate(truth)]
        hits3[name] = [r < 3 for r in ranks]
        per_kind = {k: pct(sum(r < 3 for r, kk in zip(ranks, kinds) if kk == k),
                           sum(kk == k for kk in kinds)) for k in sorted(set(kinds))}
        # fałszywe połączenia przy wspólnej ramce: próg przyjmujący 90% prawdziwych par
        # wariant-oryginał; ile par RÓŻNYCH grup z tą samą ramką platformy go przekracza
        true_scores = np.array([S[i, t] for i, t in enumerate(truth)])
        thr = float(np.quantile(true_scores, 0.10))
        So = image_scores(fs, originals, originals)[name]
        fp, n, unrelated_max = [], 0, None
        real = []
        for i, a in enumerate(originals):
            for j in range(i + 1, len(originals)):
                b = originals[j]
                if a not in labels or b not in labels:
                    continue
                sc = float(max(So[i, j], So[j, i]))
                if labels[a] == labels[b]:
                    real.append({"pair": f"{a[-6:]}~{b[-6:]}", "score": round(sc, 4), "above_thr": sc >= thr})
                    continue
                if not frames.get(a) or frames.get(a) != frames.get(b):
                    continue
                n += 1
                unrelated_max = sc if unrelated_max is None else max(unrelated_max, sc)
                if sc >= thr:
                    fp.append(f"{a[-6:]}~{b[-6:]}")
        res[name] = {"top1": pct(sum(r == 0 for r in ranks), len(ranks)),
                     "top3": pct(sum(r < 3 for r in ranks), len(ranks)), "top3_by_kind": per_kind,
                     "aux_threshold_p10_true": round(thr, 4),
                     "frame_false_links": pct(len(fp), n), "frame_false_link_pairs": fp,
                     "real_pairs": real,
                     "real_pairs_above_thr": pct(sum(r["above_thr"] for r in real), len(real)),
                     "min_real_pair": min((r["score"] for r in real), default=None),
                     "max_unrelated_same_frame": None if unrelated_max is None else round(unrelated_max, 4)}
    base = hits3.get("pHash (−Hamming)")
    for name, h in hits3.items():
        if base is not None:
            res[name]["extra_top3_vs_phash"] = sum(1 for a, b in zip(h, base) if a and not b)
    return res


# --------------------------------------------------------------------- tekst --
def rank_metrics(S, groups):
    rr, h1, h3, n, wrong1 = [], 0, 0, 0, 0
    for i, g in enumerate(groups):
        rel = [j for j, gg in enumerate(groups) if gg == g and j != i]
        if not rel:
            continue
        n += 1
        order = [j for j in np.argsort(-S[i], kind="stable") if j != i]
        first = min(order.index(j) for j in rel)
        rr.append(1 / (first + 1))
        wrong1 += groups[order[0]] != g
        h1 += first == 0
        h3 += first < 3
    return {"queries": n, "MRR": round(float(np.mean(rr)), 3) if rr else "niemierzalne",
            "hit@1": pct(h1, n), "hit@3": pct(h3, n), "top1_wrong_group": pct(wrong1, n)}


def eval_text(fs, group_of):
    from features_lib import TFIDF_METHOD, tfidf_similarity
    ads = [a for a in sorted(fs.ads) if (fs.ads[a].get("text") or "").strip() and group_of(a)]
    if len(ads) < 2:
        return {"uwaga": "za mało tekstów z etykietą"}
    groups = [group_of(a) for a in ads]
    texts = [fs.ads[a]["text"] for a in ads]
    keys, St, _ = tfidf_similarity(dict(zip(ads, texts)))
    assert keys == ads
    out = {"TF-IDF char_wb 3-5": rank_metrics(St, groups)}
    out["_methods"] = {"TF-IDF char_wb 3-5": TFIDF_METHOD}
    mv = method_of(fs, "text_embedding", "text.embedding", "e5-small")
    if mv:
        X, rows = fs.vectors(mv, "text.embedding")
        idx = {r["ad_id"]: i for i, r in enumerate(rows) if r["source_field"] == "text"}
        if all(a in idx for a in ads):
            E = X[[idx[a] for a in ads]]
            out["E5-small (query: po obu stronach)"] = rank_metrics(E @ E.T, groups)
            out["_methods"]["E5-small (query: po obu stronach)"] = mv
    out["_n_texts"] = len(ads)
    out["_n_groups_with_pairs"] = len({g for g in groups if groups.count(g) > 1})
    return out


# ----------------------------------------------------------------------- OCR --
def norm_text(s):
    s = unicodedata.normalize("NFC", s or "").lower()
    return re.sub(r"\s+", " ", s).strip()


def levenshtein(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def eval_ocr(fs, ref_path, bench_dir):
    res = {}
    if bench_dir and (Path(bench_dir) / "ocr.json").exists():
        b = json.loads((Path(bench_dir) / "ocr.json").read_text(encoding="utf-8"))
        res["p95_ms"] = {f"{r['model']} ({r['threads']} w.)": r.get("lat_p95_ms") for r in b["results"]}
        res["p95_n"] = sorted({r.get("n_runs") for r in b["results"] if r.get("n_runs")})
    if not ref_path or not Path(ref_path).exists():
        res["CER"] = "niemierzalne: brak pliku referencji (eval/ocr_reference.jsonl)"
        return res
    refs = [r for r in jl(ref_path) if (r.get("text") or "").strip()]
    for m in sorted({r["method_version"] for r in fs.rows(field="ocr.text")}):
        got = {r["ad_id"]: r["value"] for r in fs.rows(field="ocr.text", method=m)}
        cer, ph, phn, dm, dmn, n = [], 0, 0, 0, 0, 0
        for r in refs:
            if r["ad_id"] not in got:
                continue
            n += 1
            ref, hyp = norm_text(r["text"]), norm_text(got[r["ad_id"]])
            cer.append(levenshtein(hyp, ref) / max(1, len(ref)))
            for p in r.get("key_phrases", []):
                phn += 1
                ph += norm_text(p) in hyp
            for d in r.get("domains", []):
                dmn += 1
                dm += norm_text(d) in hyp.replace(" ", "")
        res[m] = {"n": n, "CER_mean": round(float(np.mean(cer)), 3) if cer else "niemierzalne",
                  "key_phrases": pct(ph, phn), "domains": pct(dm, dmn)}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image-ds", required=True)
    ap.add_argument("--variants", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--text-ds", required=True)
    ap.add_argument("--synthetic-ds")
    ap.add_argument("--ocr-ref")
    ap.add_argument("--bench")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    labels = {r["ad_id"]: r["group"] for r in jl(a.labels)}
    fs_img = FeatureStore(a.image_ds)
    corpus_root = json.loads((Path(a.image_ds) / "corpus.json").read_text())["corpus_root"]
    frames = {}
    sp = Path(a.variants).parent / "observations" / "screenshots.jsonl"
    if sp.exists():
        frames = {r["ad_id"]: r.get("screenshot_type") for r in jl(sp)}
    result = {"image": eval_images(fs_img, jl(a.variants), labels, frames)}

    fs_txt = FeatureStore(a.text_ds)
    result["text_nask"] = eval_text(fs_txt, labels.get)
    if a.synthetic_ds:
        fs_syn = FeatureStore(a.synthetic_ds)

        def syn_group(ad):  # data/sample/texts/A1_krypto.txt -> "A" (kampanie syntetyczne)
            m = re.search(r"(?:^|/)([A-Z])\d+_", fs_syn.ads[ad].get("source", {}).get("ad_ref", ""))
            return m.group(1) if m else None
        result["text_synthetic"] = eval_text(fs_syn, syn_group)
    fs_ocr = fs_txt
    result["ocr"] = eval_ocr(fs_ocr, a.ocr_ref, a.bench)
    result["_methods"] = {"pHash (−Hamming)": method_of(fs_img, "image_embedding", "image.phash", "imagehash"),
                          "DINOv2-small (cos)": method_of(fs_img, "image_embedding", "image.embedding", "dinov2"),
                          "ORB (dobre dopasowania)": method_of(fs_img, "image_embedding", "image.orb", "orb"),
                          "ORB_match": {**ORB_MATCH, "matcher": "BFMatcher knn k=2"}}
    result["_inputs"] = {"image_ds": corpus_root, "labels": a.labels, "bench": a.bench,
                         "fingerprints": {"image": fs_img.fingerprint, "text": fs_txt.fingerprint}}

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "decisions.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
