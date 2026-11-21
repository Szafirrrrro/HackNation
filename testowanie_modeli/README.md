# testowanie_modeli — benchmark CPU modeli dla „Follow the Fake” (NASK / HackNation)

Kontenery z kandydującymi modelami do ekstrakcji cech z podejrzanych reklam
(wg `NASK - Pełna Treść Zadania Konkursowego.pdf`) i benchmark zużycia CPU.
Wszystko działa **na CPU, bez sieci** (`--network none`); wagi są wbudowane w obrazy.

## Use case'y i modele

| use case (kontener) | po co w zadaniu | model A (lżejszy) | model B (mocniejszy) |
|---|---|---|---|
| `face` | wizerunki osób → baza referencyjna znanych osób | OpenCV YuNet + SFace (128d) | InsightFace buffalo_l (RetinaFace + ArcFace 512d + wiek/płeć) |
| `ocr` | tekst/URL ze zrzutów ekranu | Tesseract 5 (pol+eng) | EasyOCR (CRAFT + CRNN, pl/en) |
| `text` → `text_embedding` | podobieństwo narracji, klastrowanie | multilingual-e5-small | BAAI/bge-m3 |
| `text` → `text_topic` | tematyka (krypto, zdrowie, dopłaty…) zero-shot | multilingual-MiniLMv2-L6 xnli | mDeBERTa-v3-base xnli |
| `image_embedding` | podobieństwo kreacji / szablonu, duplikaty | DINOv2-small (+ pHash/dHash baseline) | CLIP ViT-B/32 LAION (+ zero-shot tagi) |
| `object_detection` | logotypy, QR, osoby, banknoty, karty (open-vocab) | Grounding DINO tiny | OWLv2 base |
| `asr` | transkrypcja reklam wideo | faster-whisper base int8 | faster-whisper small int8 |
| `ai_generated` | czy kreacja z generatora AI / SynthID (Gemini) | reverse-SynthID v3 i v4 (spektralne, bez NN) | SigLIP „AI vs human” (Ateeqq) |

### Uwaga o reverse-SynthID
Używamy **wyłącznie ścieżek detekcji** z [aloshdenny/reverse-SynthID](https://github.com/aloshdenny/reverse-SynthID)
(przypięty commit `b110836`, bez bypassu). Autor deklaruje ~90% skuteczności, ale niezależna analiza
([froggeric/…/synthid-detection-feasibility.md](https://github.com/froggeric/gemini-watermark-and-synthid-remover/blob/main/docs/research/synthid-detection-feasibility.md))
raportuje brak mocy dyskryminacyjnej na obrazach z treścią (ROC AUC ≈ 0.20). Dlatego `./bench.sh samples`
kopiuje etykietowany zestaw z repo (`ai_generated/gemini` = z watermarkiem, `cleaned` = po usunięciu,
`non_ai` = nasze syntetyczne grafiki) — wyniki w `summary.md` pozwalają ocenić to na własnych danych.
Sygnał SynthID traktujmy najwyżej jako cechę pomocniczą „ten sam generator/pipeline” w klastrowaniu.
Codebook v3 to plik pickle z upstreamu — ładowany wyłącznie w kontenerze bez sieci.

## Użycie

```bash
./bench.sh build                 # tm-base + 7 obrazów (kilka-kilkanaście GB, raz)
./bench.sh samples               # syntetyczne dane -> data/sample (teksty, grafiki, twarze, audio PL przez macOS `say`)
./bench.sh run                   # wszystkie use case'y -> results/<timestamp>/summary.md
./bench.sh run face ocr          # wybrane
DATA=./data/user CPUS=2 THREADS=1,2 RUN=moje ./bench.sh run
MODELS=bge-m3 ./bench.sh run text
./bench.sh report results/<RUN>
```

### Własne dane (`DATA=...`)
```
data/user/
  texts/*.txt          # 1 plik = 1 tekst reklamy
  images/*.png|jpg     # kreacje (embedding obrazów, detekcja obiektów; fallback dla faces/screenshots)
  faces/*.jpg          # opcjonalnie, inaczej images/
  screenshots/*.png    # opcjonalnie (OCR), inaczej images/
  audio/*.wav|mp3|mp4  # ASR
  ai_generated/**      # opcjonalnie (podkatalogi = etykiety), inaczej images/
```

## Co mierzymy
Harness: `common/bench.py`. Dla każdego modelu i liczby wątków (`THREADS`, domyślnie `1,all`):
- **CPU-s/elem** — czas CPU całego kontenera (cgroup v2 `cpu.stat`, łapie wszystkie wątki i podprocesy, np. tesseract) na element. Główna miara kosztu; przy 1 wątku ≈ koszt na rdzeń.
- latencja p50/p95, throughput, średnie i szczytowe zużycie rdzeni (próbkowanie co 100 ms),
- czas ładowania modelu, RAM modelu, szczytowy RAM kontenera.
Limit CPU kontenera: `CPUS` (domyślnie 4), RAM: `MEM` (domyślnie 6g; Docker Desktop ma ~7.6 GB).
Wyniki dotyczą maszyny, na której puszczono benchmark (tu: Apple M3, Linux arm64 w VM Docker Desktop).

## Licencje (do dokumentacji projektu, wymóg pkt 4 zadania)
| komponent | licencja / ograniczenia |
|---|---|
| InsightFace buffalo_l | kod MIT; **wagi tylko niekomercyjnie** |
| OpenCV YuNet / SFace | MIT / Apache-2.0 |
| Tesseract, EasyOCR | Apache-2.0 |
| multilingual-e5-small, bge-m3, mDeBERTa/MiniLM xnli (MoritzLaurer) | MIT |
| CLIP ViT-B/32 LAION | MIT; DINOv2 Apache-2.0; imagehash BSD-2 |
| OWLv2, Grounding DINO | Apache-2.0 |
| faster-whisper / Whisper | MIT |
| reverse-SynthID | **Research License: niekomercyjnie, wymagana atrybucja** „reverse-SynthID by Alosh Denny — github.com/aloshdenny/reverse-SynthID” |
| Ateeqq/ai-vs-human-image-detector | Apache-2.0 |

Dane w `data/sample` są syntetyczne (oprócz zdjęcia testowego z pakietu insightface i obrazów walidacyjnych z repo reverse-SynthID) — to smoke-test, nie ewaluacja jakości.
