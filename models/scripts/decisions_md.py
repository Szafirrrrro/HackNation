"""decisions.json -> decisions.md: liczby, mianowniki i propozycja decyzji wg reguł zespołu.

Reguły (README laboratorium: embedding wolno włączyć, gdy odzyska dodatkowy zgodny wariant
w top-3, utrzyma lub obniży liczbę fałszywych przypisań i zmieści się w budżecie; progi to
założenia zespołu):
  OCR   : Tesseract jest jedynym silnikiem; raport podaje CER, frazy i p95.
  Obraz : embedding (CLIP, model domyślny) spełnia regułę sygnału RANKINGU obok pHash, gdy (a) daje dodatkowe trafienia
          top-3, (b) każda rzeczywista para tymczasowa ma wynik wyższy niż najwyższa niepowiązana
          para z tą samą ramką, (c) próg pomocniczy przewyższa tę parę o >= 5% (zapas na ramkę).
  Tekst : embedding wchodzi obok TF-IDF, gdy na parafrazach ma więcej hit@3 i nie więcej
          zapytań z top-1 z innej grupy, a na NASK nie jest gorszy.
"""
import json
import re
import sys

d = json.load(open(sys.argv[1], encoding="utf-8"))


def num(s):
    m = re.match(r"(\d+)/(\d+)", str(s))
    return (int(m.group(1)), int(m.group(2))) if m else None


out = ["# Decyzje laboratorium — wyniki ewaluacji", "",
       "Etykiety NASK są **tymczasowe** (eval/labels_nask_provisional.jsonl: p3/p4 i p1/p7/p15, "
       "reszta pojedynczo; kampanie nieustalone). Parafrazy w data/sample są syntetyczne. "
       "Progi reguł to założenia zespołu. Wyniki opisują ten zbiór, nie skuteczność na kampaniach.", ""]

# ----- obraz
img = d.get("image", {})
out += ["## Obraz — warianty kreacji (zapytanie: wariant, kandydaci: 13 oryginałów)", "",
        "Remisy liczone na niekorzyść metody. Próg pomocniczy = 10. percentyl wyników prawdziwych par "
        "wariant–oryginał (przyjmuje 90% syntetycznych wariantów) — **to nie jest punkt pracy**. "
        "„Pary z tą samą ramką ≥ próg” = wszystkie pary oryginałów z różnych grup tymczasowych "
        "i z tym samym `screenshot_type` (pojedyncze reklamy to brak udokumentowanego powiązania, "
        "nie potwierdzone różne kampanie).", "",
        "| metoda | top-1 | top-3 | top-3 kadr | top-3 róg | top-3 zmniejszenie+JPEG | dodatkowe top-3 vs pHash | próg pomocniczy | pary z tą samą ramką ≥ próg |",
        "|---|---|---|---|---|---|---|---|---|"]
for m, r in img.items():
    k = r["top3_by_kind"]
    out.append(f"| {m} | {r['top1']} | {r['top3']} | {k.get('crop')} | {k.get('corner')} | {k.get('small')} | "
               f"{r.get('extra_top3_vs_phash', '—')} | {r['aux_threshold_p10_true']} | {r['frame_false_links']} |")
out += ["", "Rzeczywiste pary tymczasowe (p3/p4, p1/p7, p1/p15, p7/p15) na oryginałach:", "",
        "| metoda | pary ≥ próg pomocniczy | wyniki par | najniższa para | najwyższa niepowiązana para z tą samą ramką | margines |",
        "|---|---|---|---|---|---|"]
for m, r in img.items():
    lo, hi = r.get("min_real_pair"), r.get("max_unrelated_same_frame")
    margin = "—" if lo is None or hi is None else round(lo - hi, 4)
    out.append(f"| {m} | {r['real_pairs_above_thr']} | {', '.join(str(p['score']) for p in r['real_pairs'])} | "
               f"{lo} | {hi} | {margin} |")
base = img.get("pHash (−Hamming)")
out.append("")
for m, r in img.items():
    if m.startswith("pHash") or not base:
        continue
    extra = r.get("extra_top3_vs_phash", 0)
    lo, hi, thr = r.get("min_real_pair"), r.get("max_unrelated_same_frame"), r["aux_threshold_p10_true"]
    real_ok = lo is not None and hi is not None and lo > hi
    reserve_ok = hi is not None and thr - hi >= 0.05 * abs(hi)
    verdict = ("**sygnał rankingu obok pHash** (próg nie jest punktem pracy)"
               if extra > 0 and real_ok and reserve_ok else
               "reguła rankingu niespełniona (" + ", ".join(x for x, ok in (("brak dodatkowych trafień", extra > 0),
                                                                  ("para rzeczywista ≤ niepowiązanej", real_ok),
                                                                  ("zapas progu nad ramką < 5%", reserve_ok)) if not ok) + ")")
    out.append(f"- {m}: +{extra} top-3 vs pHash; najniższa para rzeczywista {lo} vs najwyższa niepowiązana "
               f"{hi}; próg pomocniczy {thr} → {verdict}")

# ----- tekst
def text_table(title, t):
    rows = [f"## {title}", ""]
    if "uwaga" in t:
        return rows + [t["uwaga"], ""]
    rows += [f"{t.get('_n_texts')} tekstów, grup z parami: {t.get('_n_groups_with_pairs')}.", "",
             "| metoda | zapytania | MRR | hit@1 | hit@3 | top-1 z innej grupy |", "|---|---|---|---|---|---|"]
    for m, r in t.items():
        if not m.startswith("_"):
            rows.append(f"| {m} | {r['queries']} | {r['MRR']} | {r['hit@1']} | {r['hit@3']} | {r['top1_wrong_group']} |")
    return rows + [""]


out.append("")
out += text_table("Tekst — NASK (tymczasowe grupy; identyczne transkrypcje, test trywialny)", d.get("text_nask", {}))
if "text_synthetic" in d:
    out += text_table("Tekst — parafrazy syntetyczne (data/sample/texts)", d["text_synthetic"])


def get(t, prefix, key):
    for k, v in (t or {}).items():
        if k.startswith(prefix) and isinstance(v, dict):
            return num(v.get(key)) if key != "MRR" else v.get("MRR")


syn, nask = d.get("text_synthetic"), d.get("text_nask")
e3, t3 = get(syn, "E5", "hit@3"), get(syn, "TF-IDF", "hit@3")
ew, tw = get(syn, "E5", "top1_wrong_group"), get(syn, "TF-IDF", "top1_wrong_group")
en, tn = get(nask, "E5", "hit@3"), get(nask, "TF-IDF", "hit@3")
if None in (e3, t3, ew, tw):
    out.append("- E5-small: niemierzalne (brak parafraz lub cech E5).")
else:
    ok = e3[0] > t3[0] and ew[0] <= tw[0] and (en is None or tn is None or en[0] >= tn[0])
    out.append(f"- E5-small: hit@3 parafrazy {e3[0]}/{e3[1]} vs TF-IDF {t3[0]}/{t3[1]}; top-1 z innej grupy "
               f"{ew[0]} vs {tw[0]}; MRR {get(syn, 'E5', 'MRR')} vs {get(syn, 'TF-IDF', 'MRR')} → "
               + ("**włączyć obok TF-IDF**" if ok else
                  "**TF-IDF char_wb 3-5 domyślnie** (" + ", ".join(
                      why for why, bad in (("brak dodatkowego trafienia top-3", e3[0] <= t3[0]),
                                           ("więcej top-1 z innej grupy", ew[0] > tw[0]),
                                           ("gorzej na NASK", en is not None and tn is not None and en[0] < tn[0]))
                      if bad) + ")"))

# ----- OCR
ocr = d.get("ocr", {})
out += ["", "## OCR", ""]
if isinstance(ocr.get("CER"), str):
    out.append(f"- CER: {ocr['CER']}.")
else:
    out += ["| metoda | n | średni CER | kluczowe frazy | domeny |", "|---|---|---|---|---|"]
    for m, r in ocr.items():
        if isinstance(r, dict) and "CER_mean" in r:
            out.append(f"| {m} | {r['n']} | {r['CER_mean']} | {r['key_phrases']} | {r['domains']} |")
if ocr.get("p95_ms"):
    out += ["", "p95 latencji OCR (ms) na tym korpusie: " +
            "; ".join(f"{k}: {v}" for k, v in ocr["p95_ms"].items()) +
            f". n = {ocr.get('p95_n', '?')} pomiarów na konfigurację (p95 z małej próby ≈ jedna z najwyższych wartości). "
            "Budżet projektu: p95 ≤ 5 s na całą ścieżkę obrazu."]
out += ["", "## Poza tym raportem", "",
        "Wybór modeli opisuje benchmark/README.md. Temat, obiekty, twarze i ocena Effort liczą się "
        "na żądanie: `PROFILE=all ./extract.sh` albo `MODELS=...`.",
        "", f"Wejścia: `{json.dumps(d.get('_inputs', {}), ensure_ascii=False)}`",
        "", f"Metody: `{json.dumps(d.get('_methods', {}), ensure_ascii=False)}`"]
print("\n".join(out))
