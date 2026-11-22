"""Miary jakości benchmarku warstwy modeli (opis: models/benchmark/README.md).

Uruchamiane w kontenerze tm-text (numpy, scikit-learn, OpenCV) przez models/benchmark/run.sh:

    python metrics.py --corpus /corpus --full /out/features/<ds> --subset /out/features/<ds>-subset
        --variants /out/features/<ds>-subset-eval-variants --variants-map /variants/variants.jsonl
        --out /quality

Wynik: <out>/results.json (liczby zbiorcze), <out>/pairs.jsonl i pairs_key.json (pary do oceny
ręcznej; zawierają identyfikatory reklam, więc zostają poza Gitem).
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, "/app/common")
from features_lib import ORB_MATCH, FeatureStore, tfidf_similarity  # noqa: E402

LOW = -1e9
NEAR_DUP_PHASH = 4        # reklamy o pHash bliższym niż to uznajemy za tę samą kreację
MAX_IMAGE_QUERIES = 150   # zapytania śladu zewnętrznego dla obrazu (ORB liczy każdą parę osobno)
PAIRS_PER_MODEL = 30


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


def frac(a, b):
    return {"n": int(a), "of": int(b), "pct": round(100 * a / b, 1) if b else None}


def norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s or "").casefold()).strip()


def method(fs, field, name):
    ms = sorted({m["method_version"] for m in fs.methods() if m["field"] == field and name in m["method_version"]})
    return ms[0] if ms else None


def by_ad(fs, field, name):
    mv = method(fs, field, name)
    return {r["ad_id"]: r["value"] for r in fs.rows(field=field, method=mv)} if mv else {}


# ------------------------------------------------------------------ ranking --
def ranks(S, pos, excl):
    """Pozycja najlepszego trafienia (0 = pierwsze); remisy liczone na niekorzyść metody."""
    out = []
    for i in range(S.shape[0]):
        mask = np.ones(S.shape[1], bool)
        mask[list(excl[i])] = False
        mask[list(pos[i])] = False
        best = S[i, list(pos[i])].max()
        out.append(int((S[i, mask] >= best).sum()) if best > LOW else S.shape[1])
    return np.array(out)


def rank_summary(r):
    return {"queries": len(r), "hit@1": frac((r == 0).sum(), len(r)), "hit@3": frac((r < 3).sum(), len(r)),
            "MRR": round(float(np.mean(1 / (r + 1))), 3) if len(r) else None}


def auc(S, pos, excl):
    """Szansa, że para ze śladem zewnętrznym ma wyższy wynik niż para bez niego (pary wszystkich zapytań razem)."""
    from sklearn.metrics import roc_auc_score
    y, s = [], []
    for i in range(S.shape[0]):
        mask = np.ones(S.shape[1], bool)
        mask[list(excl[i])] = False
        lab = np.zeros(S.shape[1], bool)
        lab[list(pos[i])] = True
        y.append(lab[mask])
        s.append(S[i, mask])
    y, s = np.concatenate(y), np.concatenate(s)
    return round(float(roc_auc_score(y, s)), 3) if 0 < y.sum() < len(y) else None


def top3(S, excl):
    out = []
    for i in range(S.shape[0]):
        s = S[i].copy()
        s[list(excl[i])] = LOW
        out.append([int(j) for j in np.argsort(-s, kind="stable")[:3] if s[j] > LOW])
    return out


# -------------------------------------------------------------------- obraz --
def hash_bits(values, ids):
    rows = [np.unpackbits(np.frombuffer(bytes.fromhex(values[a]), np.uint8)) if a in values else None for a in ids]
    width = next((len(r) for r in rows if r is not None), 64)
    have = np.array([r is not None for r in rows])
    return np.array([r if r is not None else np.zeros(width, np.uint8) for r in rows], np.int16), have


def hamming(fq, q_ids, fg, g_ids, field):
    A, ha = hash_bits(by_ad(fq, field, "imagehash"), q_ids)
    B, hb = hash_bits(by_ad(fg, field, "imagehash"), g_ids)
    D = (A[:, None, :] != B[None, :, :]).sum(-1).astype(float)
    S = -D
    S[~ha, :] = LOW
    S[:, ~hb] = LOW
    return S


def embedding(fq, q_ids, fg, g_ids, field, name, source_field=None):
    def load(fs, ids):
        mv = method(fs, field, name)
        X, rows = fs.vectors(mv, field) if mv else (np.zeros((0, 1), np.float32), [])
        idx = {r["ad_id"]: i for i, r in enumerate(rows) if source_field in (None, r.get("source_field"))}
        M = np.zeros((len(ids), X.shape[1]), np.float32)
        have = np.zeros(len(ids), bool)
        for k, a in enumerate(ids):
            if a in idx:
                M[k], have[k] = X[idx[a]], True
        return M, have
    A, ha = load(fq, q_ids)
    B, hb = load(fg, g_ids)
    if A.shape[1] != B.shape[1]:
        return None
    S = (A @ B.T).astype(float)
    S[~ha, :] = LOW
    S[:, ~hb] = LOW
    return S


def orb(fq, q_ids, fg, g_ids):
    import cv2
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)

    def load(fs, ids):
        vals = by_ad(fs, "image.orb", "orb")
        files = {p: np.load(fs.root / p) for p in {v["array"] for v in vals.values()}}
        return [files[vals[a]["array"]][vals[a]["key"]] if a in vals else None for a in ids]
    Q, G = load(fq, q_ids), load(fg, g_ids)
    S = np.full((len(Q), len(G)), LOW)
    for i, dq in enumerate(Q):
        if dq is None or len(dq) < 2:
            continue
        for j, dg in enumerate(G):
            if dg is None or len(dg) < 2:
                continue
            m = bf.knnMatch(dq, dg, k=2)
            S[i, j] = sum(1 for p in m if len(p) == 2 and p[0].distance < ORB_MATCH["ratio"] * p[1].distance)
    return S


def image_scores(fq, q_ids, fg, g_ids):
    out = {"pHash": hamming(fq, q_ids, fg, g_ids, "image.phash"),
           "dHash": hamming(fq, q_ids, fg, g_ids, "image.dhash"),
           "DINOv2-small": embedding(fq, q_ids, fg, g_ids, "image.embedding", "dinov2"),
           "CLIP ViT-B/32": embedding(fq, q_ids, fg, g_ids, "image.embedding", "clip"),
           "ORB": orb(fq, q_ids, fg, g_ids)}
    return {k: v for k, v in out.items() if v is not None and (v > LOW).any()}


def partners(ids, meta):
    """Indeksy reklam z tym samym nadawcą lub wspólną domeną docelową (ślad zewnętrzny)."""
    by_key = defaultdict(set)
    for i, a in enumerate(ids):
        m = meta.get(a, {})
        if m.get("advertiser"):
            by_key[("adv", m["advertiser"])].add(i)
        for d in m.get("landing_domains", []):
            by_key[("dom", d)].add(i)
    out = [set() for _ in ids]
    for members in by_key.values():
        for i in members:
            out[i] |= members - {i}
    return out


def eval_image(full, variants, vmap, meta, rng, pairs):
    g_ids = sorted(a for a in full.ads if full.ads[a].get("image_path"))
    gi = {a: i for i, a in enumerate(g_ids)}
    res = {"gallery": len(g_ids)}

    # 1) warianty syntetyczne: zapytanie = wariant reklamy z podzbioru, galeria = cała próba
    vmap = [v for v in vmap if v["variant_of"] in gi]
    q_ids = [v["ad_id"] for v in vmap]
    truth = [gi[v["variant_of"]] for v in vmap]
    near = hamming(full, g_ids, full, g_ids, "image.phash") >= -NEAR_DUP_PHASH
    excl = [set(np.flatnonzero(near[t]).tolist()) - {t} for t in truth]
    res["near_duplicate_originals_excluded"] = int(sum(bool(e) for e in excl))
    res["variants"] = {}
    for name, S in image_scores(variants, q_ids, full, g_ids).items():
        r = ranks(S, [{t} for t in truth], excl)
        res["variants"][name] = {**rank_summary(r), "hit@3_by_kind": {
            k: frac(sum(x < 3 for x, v in zip(r, vmap) if v["kind"] == k), sum(v["kind"] == k for v in vmap))
            for k in sorted({v["kind"] for v in vmap})}}

    # 2) ślad zewnętrzny i zysk ponad pHash: zapytanie = reklama z partnerem, galeria = cała próba
    part = partners(g_ids, meta)
    with_partner = [i for i, p in enumerate(part) if p]
    q = sorted(rng.sample(with_partner, min(MAX_IMAGE_QUERIES, len(with_partner))))
    res["external"] = {"ads_with_partner": len(with_partner), "queries": len(q)}
    if not q:
        return res
    scores = image_scores(full, [g_ids[i] for i in q], full, g_ids)
    self_excl = [{i} for i in q]
    tops = {}
    for name, S in scores.items():
        res["external"][name] = {**rank_summary(ranks(S, [part[i] for i in q], self_excl)),
                                 "AUC": auc(S, [part[i] for i in q], self_excl)}
        tops[name] = top3(S, self_excl)
    gain_pairs("image", "pHash", tops, [g_ids[i] for i in q], g_ids, [part[i] for i in q], rng, pairs, res)
    return res


def gain_pairs(family, base, tops, q_ids, g_ids, part, rng, pairs, res):
    """Pary w top-3 modelu, których nie ma w top-3 metody bazowej; losujemy do oceny ręcznej."""
    res["gain_over_base"] = {"base": base}
    for name, top in tops.items():
        if name == base:
            continue
        cand = [(q_ids[k], g_ids[j], j in part[k]) for k in range(len(q_ids))
                for j in top[k] if j not in tops[base][k]]
        picked = rng.sample(cand, min(PAIRS_PER_MODEL, len(cand)))
        res["gain_over_base"][name] = {"extra_pairs": len(cand),
                                       "with_external_trace": frac(sum(c[2] for c in cand), len(cand)),
                                       "sampled_for_review": len(picked)}
        for a, b, traced in picked:
            pairs.append({"family": family, "model": name, "a": a, "b": b, "external_trace": bool(traced)})


# -------------------------------------------------------------------- tekst --
def eval_text(full, meta, rng, pairs):
    groups = defaultdict(list)                     # identyczne teksty liczymy jako jedną pozycję
    for a in sorted(full.ads):
        t = norm(full.ads[a].get("text"))
        if len(t) >= 24:
            groups[t].append(a)
    reps = [members[0] for members in groups.values()]
    # partner: wspólny nadawca lub domena między dowolnymi reklamami dwóch różnych tekstów
    keys = defaultdict(set)
    for i, members in enumerate(groups.values()):
        for a in members:
            m = meta.get(a, {})
            if m.get("advertiser"):
                keys[("adv", m["advertiser"])].add(i)
            for d in m.get("landing_domains", []):
                keys[("dom", d)].add(i)
    part = [set() for _ in reps]
    for members in keys.values():
        for i in members:
            part[i] |= members - {i}
    q = [i for i, p in enumerate(part) if p]
    res = {"ads_with_text": sum(len(m) for m in groups.values()), "unique_texts": len(reps), "queries": len(q)}
    if not q:
        return res
    _, St, _ = tfidf_similarity({a: full.ads[a]["text"] for a in reps})
    scores = {"TF-IDF char_wb 3-5": St[q]}
    for label, name in (("E5-small", "e5-small"), ("BGE-M3", "bge-m3")):
        S = embedding(full, [reps[i] for i in q], full, reps, "text.embedding", name, source_field="text")
        if S is not None and (S > LOW).any():
            scores[label] = S
    self_excl = [{i} for i in q]
    tops = {}
    for name, S in scores.items():
        res[name] = {**rank_summary(ranks(S, [part[i] for i in q], self_excl)),
                     "AUC": auc(S, [part[i] for i in q], self_excl)}
        tops[name] = top3(S, self_excl)
    gain_pairs("text", "TF-IDF char_wb 3-5", tops, [reps[i] for i in q], reps, [part[i] for i in q], rng, pairs, res)
    return res


# ---------------------------------------------------------------------- OCR --
def tokens(text):
    return sorted({w for w in re.findall(r"[^\W\d_]{4,}", norm(text))})


def eval_ocr(subset, variants, vmap, meta):
    res = {}
    originals = sorted(a for a in subset.ads if subset.ads[a].get("image_path"))
    models = (("Tesseract pol+eng", "tesseract"), ("EasyOCR pl/en", "easyocr"))
    done = [set(by_ad(variants, "ocr.text", name)) for _, name in models]
    common = set.intersection(*[d for d in done if d]) if any(done) else set()
    for label, name in models:
        got = by_ad(subset, "ocr.text", name)
        if not got:
            continue
        recall, adv, dom, dom_n = [], 0, 0, 0
        for a in originals:
            hyp = norm(got.get(a, ""))
            squeezed = hyp.replace(" ", "")
            ref = tokens(subset.ads[a].get("text"))
            if len(ref) >= 5:
                recall.append(sum(t in hyp for t in ref) / len(ref))
            m = meta.get(a, {})
            if m.get("advertiser"):
                adv += norm(m["advertiser"]).replace(" ", "") in squeezed
            for d in m.get("landing_domains", []):
                dom_n += 1
                dom += d in squeezed
        out = {"non_empty": frac(sum(len(norm(got.get(a, ""))) >= 20 for a in originals), len(originals)),
               "card_text_word_recall": {"mean": round(float(np.mean(recall)), 3) if recall else None,
                                         "ads": len(recall)},
               "advertiser_name_read": frac(adv, sum(1 for a in originals if meta.get(a, {}).get("advertiser"))),
               "landing_domain_read": frac(dom, dom_n)}
        vgot = by_ad(variants, "ocr.text", name)
        if vgot:
            gallery = {a: got.get(a) or "-" for a in originals}
            keys, _, vec = tfidf_similarity(gallery)
            G = vec.transform([gallery[k] for k in keys])
            # te same zapytania dla obu OCR: tylko warianty, które policzył każdy z nich
            qs = [v for v in vmap if v["variant_of"] in gallery and v["ad_id"] in common]
            Q = vec.transform([vgot.get(v["ad_id"]) or "" for v in qs])
            S = (Q @ G.T).toarray()
            S[S <= 0] = LOW
            r = ranks(S, [{keys.index(v["variant_of"])} for v in qs], [set() for _ in qs])
            out["variant_retrieval_tfidf"] = {**rank_summary(r), "hit@3_by_kind": {
                k: frac(sum(x < 3 for x, v in zip(r, qs) if v["kind"] == k), sum(v["kind"] == k for v in qs))
                for k in sorted({v["kind"] for v in qs})}}
        res[label] = out
    return res


# --------------------------------------------------- rodziny bez odzyskiwania --
def eval_faces(full, meta):
    res = {}
    ids = sorted(a for a in full.ads if full.ads[a].get("image_path"))
    counts = {}
    for label, name in (("YuNet + SFace", "yunet"), ("InsightFace buffalo_l", "insightface")):
        c = by_ad(full, "face.count", name)
        if not c:
            continue
        counts[label] = c
        res[label] = {"ads_with_face": frac(sum((c.get(a) or 0) > 0 for a in ids), len(ids)),
                      "mean_faces": round(float(np.mean([c.get(a) or 0 for a in ids])), 2)}
        mv = method(full, "face.embedding", name)
        if mv:
            ad_ids, S, _ = full.ad_similarity(mv, "face.embedding")
            part = partners(ad_ids, meta)
            q = [i for i, p in enumerate(part) if p]
            if q:
                S = S.astype(float)
                res[label]["external"] = {**rank_summary(ranks(S[q], [part[i] for i in q], [{i} for i in q])),
                                          "AUC": auc(S[q], [part[i] for i in q], [{i} for i in q])}
    if len(counts) == 2:
        a, b = counts.values()
        res["agreement_has_face"] = frac(sum(((a.get(x) or 0) > 0) == ((b.get(x) or 0) > 0) for x in ids), len(ids))
    return res


# Słaba etykieta tematu: fraza, którą znaleziono reklamę -> oczekiwana kategoria. Mapowanie leży przy
# korpusie (<korpus>/topic_phrases.json: {kategoria: [frazy]}), poza repozytorium; frazy
# niejednoznaczne są w nim pominięte. Bez pliku miara zgodności z frazą nie jest liczona.
def eval_topic(subset, meta, phrase_topic):
    expected = {}
    for a, m in meta.items():
        for topic, phrases in phrase_topic.items():
            if norm(m.get("query_phrase")) in {norm(p) for p in phrases}:
                expected[a] = topic
    res, labels = {}, {}
    for label, name in (("MiniLMv2-L6 XNLI", "MiniLMv2"), ("mDeBERTa-v3 XNLI", "mDeBERTa")):
        mv = method(subset, "text.topic", name)
        rows = [r for r in subset.rows(field="text.topic", method=mv) if r.get("source_field") == "text"] if mv else []
        if not rows:
            continue
        labels[label] = {r["ad_id"]: r["value"]["label"] for r in rows}
        res[label] = {"texts": len(rows),
                      "top_score_below_0.5": frac(sum(r["value"]["score"] < 0.5 for r in rows), len(rows)),
                      "matches_query_phrase_topic": frac(
                          sum(labels[label][a] == expected[a] for a in labels[label] if a in expected),
                          sum(a in expected for a in labels[label])),
                      "matches_by_expected_topic": {t: frac(
                          sum(labels[label][a] == t for a in labels[label] if expected.get(a) == t),
                          sum(expected.get(a) == t for a in labels[label])) for t in sorted(set(expected.values()))},
                      "labels": dict(Counter(r["value"]["label"] for r in rows).most_common())}
    if len(labels) == 2:
        a, b = labels.values()
        common = sorted(set(a) & set(b))
        res["agreement_top_label"] = frac(sum(a[x] == b[x] for x in common), len(common))
    return res


def eval_objects(subset):
    res, sets = {}, {}
    ids = sorted(a for a in subset.ads if subset.ads[a].get("image_path"))
    for label, name in (("Grounding DINO tiny", "grounding-dino"), ("OWLv2 base", "owlv2")):
        det = by_ad(subset, "objects.detections", name)
        if not det:
            continue
        sets[label] = {a: {d["label"] for d in det.get(a) or []} for a in ids}
        res[label] = {"ads_with_detection": frac(sum(bool(det.get(a)) for a in ids), len(ids)),
                      "mean_detections": round(float(np.mean([len(det.get(a) or []) for a in ids])), 2),
                      "labels": dict(Counter(l for a in ids for l in sets[label][a]).most_common(8))}
    if len(sets) == 2:
        a, b = sets.values()
        jac = [len(a[x] & b[x]) / len(a[x] | b[x]) for x in ids if a[x] | b[x]]
        res["label_set_jaccard_mean"] = round(float(np.mean(jac)), 3) if jac else None
    qr = by_ad(subset, "qr.count", "opencv-qr")
    if qr:
        res["QR OpenCV"] = {"ads_with_qr": frac(sum((qr.get(a) or 0) > 0 for a in ids), len(ids))}
    return res


def eval_ai(subset):
    res, flags = {}, {}
    ids = sorted(a for a in subset.ads if subset.ads[a].get("image_path"))
    spec = (("reverse-SynthID v4", "ai.synthid", "synthid-v4", lambda v: bool(v.get("watermarked"))),
            ("SigLIP AI/human", "ai.generated", "siglip", lambda v: v.get("top") == "ai"),
            ("Effort CLIP-L/14", "ai.effort", "effort", lambda v: v.get("label") == 1))
    for label, field, name, flagged in spec:
        vals = {a: v for a, v in by_ad(subset, field, name).items() if isinstance(v, dict)}
        if not vals:
            continue
        flags[label] = {a: flagged(v) for a, v in vals.items()}
        res[label] = {"scored": frac(len(vals), len(ids)), "flagged_as_ai": frac(sum(flags[label].values()), len(vals))}
    if "SigLIP AI/human" in flags and "Effort CLIP-L/14" in flags:
        a, b = flags["SigLIP AI/human"], flags["Effort CLIP-L/14"]
        common = sorted(set(a) & set(b))
        res["agreement_siglip_effort"] = frac(sum(a[x] == b[x] for x in common), len(common))
    return res


def costs(stores):
    """Średni czas na wejście z metadanych ekstrakcji (runs/<slug>.json); p95 podaje bench.sh."""
    out = {}
    for tag, fs in stores.items():
        for r in fs.runs():
            if r.get("status") != "ok" or not r.get("n_inputs"):
                continue
            out.setdefault(r["extractor"], {})[tag] = {
                "inputs": r["n_inputs"],
                "s_per_input": round((r["duration_s"] - (r.get("load_s") or 0))
                                     / max(1, r["n_inputs"] - (r.get("inputs_reused") or 0)), 3),
                "load_s": r.get("load_s"), "threads": r.get("threads"), "stage": r.get("stage")}
    return out


def main():
    ap = argparse.ArgumentParser()
    for name in ("corpus", "full", "subset", "variants", "variants-map", "out"):
        ap.add_argument(f"--{name}", required=True)
    ap.add_argument("--seed", type=int, default=20261122)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    meta = {r["ad_id"]: r for r in jl(Path(a.corpus) / "benchmark_meta.jsonl")}
    tp = Path(a.corpus) / "topic_phrases.json"
    phrase_topic = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else {}
    full, subset, variants = FeatureStore(a.full), FeatureStore(a.subset), FeatureStore(a.variants)
    vmap = jl(a.variants_map)
    pairs = []
    result = {
        "sample": {**json.loads((Path(a.corpus) / "benchmark_sample.json").read_text(encoding="utf-8")),
                   "fingerprints": {"full": full.fingerprint, "subset": subset.fingerprint,
                                    "variants": variants.fingerprint},
                   "variant_queries": len(vmap)},
        "image": eval_image(full, variants, vmap, meta, rng, pairs),
        "text": eval_text(full, meta, rng, pairs),
        "ocr": eval_ocr(subset, variants, vmap, meta),
        "faces": eval_faces(full, meta),
        "topic": eval_topic(subset, meta, phrase_topic),
        "objects": eval_objects(subset),
        "ai_provenance": eval_ai(subset),
        "cost": costs({"full": full, "subset": subset}),
        "params": {"seed": a.seed, "near_dup_phash": NEAR_DUP_PHASH, "max_image_queries": MAX_IMAGE_QUERIES,
                   "pairs_per_model": PAIRS_PER_MODEL, "orb_match": ORB_MATCH},
    }
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    # ocena ręczna na ślepo: pary wymieszane, a nazwa modelu w osobnym pliku
    merged = defaultdict(lambda: {"models": set(), "external_trace": False})
    for p in pairs:
        key = (p["family"], *sorted((p["a"], p["b"])))
        merged[key]["models"].add(p["model"])
        merged[key]["external_trace"] |= p["external_trace"]
    order = sorted(merged)
    rng.shuffle(order)
    rows, key_rows = [], {}
    for n, key in enumerate(order, 1):
        pid = f"{key[0]}-{n:03d}"
        rows.append({"pair_id": pid, "family": key[0], "a": key[1], "b": key[2], "verdict": None, "basis": None})
        key_rows[pid] = {"models": sorted(merged[key]["models"]), "external_trace": merged[key]["external_trace"]}
    (out / "pairs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    (out / "pairs_key.json").write_text(json.dumps(key_rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wynik: {out}/results.json; pary do oceny: {len(rows)}")


if __name__ == "__main__":
    main()
