# Laboratorium modeli ScamGraph

Siedem kontenerów uruchamia dziewięć rodzajów eksperymentów (z dekoderem QR) na CPU w dwóch rozdzielonych trybach. **Ekstrakcja** (`./extract.sh`) zapisuje cechy w formacie [kontraktu](../docs/DATA_CONTRACT.md) do `out/features/<dataset_id>/` dla silnika Pary C. **Benchmark** (`./bench.sh run`) zapisuje wyłącznie koszt do `out/benchmark/<RUN>/` i nie produkuje cech. Oba tryby wywołują te same ekstraktory z `containers/<use_case>/models.py`. Katalogi `out/` i `data/` są ignorowane przez Git. Skuteczność modeli na kampaniach NASK czeka na etykiety. Porównanie modeli na próbie 492 reklam, z wynikami i decyzją o jednym modelu na parametr, opisuje [benchmark](benchmark/README.md). [Ekstrakcja](extract.sh) · [Pomiar](bench.sh) · [Ekstraktory](common/extractor.py) · [Kod pomiaru](common/bench.py) · [Raport](scripts/report.py)

## Który eksperyment odpowiada na problem analityka?

| Rodzina i implementacje w repozytorium | Decyzja i sposób sprawdzenia |
| --- | --- |
| **OCR** · Tesseract 5 `pol+eng`, EasyOCR `pl/en` | *Status: Tesseract `default`, EasyOCR `deferred` (zgoda użytkownika 2026-11-21: wybór ze względu na koszt, p95 EasyOCR 14,5 s poza budżetem; CER niezmierzony).* Zaczynamy od Tesseract. B przygotowuje pełne transkrypcje wybranych *kadrów*. Porównuje oba silniki przez odsetek błędnych znaków (CER), poprawne odczytanie całej charakterystycznej frazy lub domeny i p95. Teksty w lokalnym korpusie to ręczne fragmenty. Wykorzystanie fragmentu jako pełnej referencji błędnie ukarałoby poprawnie odczytane dodatkowe słowa. |
| **Obraz** · pHash/dHash, DINOv2-small, CLIP ViT-B/32, ORB | *Status: SHA-256 + pHash/dHash i DINOv2 `default` (DINOv2 jako sygnał rankingu), ORB `candidate`, CLIP `deferred` (wynik ewaluacji niżej).* Dla identycznego pliku wystarcza SHA-256. Dla podobnego kadru sprawdzamy pHash. Po przeoczeniu wykadrowanej kreacji porównujemy go z dopasowaniem lokalnych punktów ORB w OpenCV i DINOv2-small. Mierzymy dodatkowe poprawne wyniki top-3 oraz pomyłki przy wspólnej ramce platformy. CLIP odkładamy do zadania wyszukiwania obrazów o wspólnym znaczeniu. |
| **Tekst** · multilingual-e5-small, BGE-M3 | *Status: TF-IDF `char_wb` 3–5 domyślny (`features_lib.tfidf_similarity`, liczony przy porównaniu, nie w ekstrakcji), E5-small `candidate`, BGE-M3 `deferred`.* Punktem odniesienia będzie znakowy TF-IDF `char_wb` 3–5. E5-small testujemy, gdy pominięta parafraza różni się słownictwem. Dla symetrycznego porównania E5 dodajemy `query: ` do obu tekstów. Porównujemy miejsce właściwej emisji w rankingu. BGE-M3 ma sens po wykazaniu powtarzalnego błędu mniejszego modelu. |
| **Temat** · MiniLMv2-L6 XNLI, mDeBERTa-v3-base XNLI | *Status: `deferred`.* Odłożyć. Zestaw zwraca jedną z zadanych kategorii także dla tekstu spoza listy. Dwie różne kampanie mogą reklamować leki. |
| **Obiekty** · Grounding DINO tiny, OWLv2 base; dekoder QR | *Status: detektory `deferred`, dekoder QR OpenCV `default` (`qr.values`, `qr.urls`).* Odłożyć. Kod zwraca rozpoznane kategorie. Dla kodu QR bardziej użyteczne jest porównanie lokalnie zdekodowanych wartości. Wspólne logo lub telefon wymaga dalszych dowodów. |
| **Twarze** · YuNet + SFace, InsightFace buffalo_l | *Status: `deferred`.* Odłożyć. Ekstrakcja zapisuje ramki, wektory tożsamości i liczbę twarzy. Test powiązań wymagałby uprawnionej bazy referencyjnej, weryfikacji wag oraz różnych kampanii z tą samą osobą. |
| **Mowa** · faster-whisper base/small int8 | *Status: small `default`, base `deferred` (decyzja użytkownika 2026-11-21: wybór na oko, bez pomiaru WER).* Powód wyboru to oczekiwanie, nie pomiar: base gorzej radzi sobie z polskimi nazwami produktów i liczbami, a w reklamach to właśnie one wiążą emisje. Base nie był uruchamiany na nagraniach reklam. Do potwierdzenia: pełne ręczne transkrypcje nagrań, błąd słów (WER), odzyskane nazwy produktów, liczby i domeny oraz czas na minutę nagrania. Ekstrakcja zapisuje pełną transkrypcję i segmenty czasowe; raport benchmarku pokazuje tylko podgląd. Pierwszy przebieg 2026-11-21 na 3 nagraniach wideo reklam (materiał wyzwania, tylko lokalnie w `data/`, poza repo): dwa z mową dały spójną polską transkrypcję (ok. 2,9–3,4 tys. znaków), trzecie ma wyciszoną ścieżkę (`silent_audio`). Koszt small: 127 s na 7,5 min mowy przy 8 wątkach (aarch64), ok. 17 s na minutę nagrania. |
| **Audio** (rodzina `audio`) · Chromaprint `fpcalc`, SpeechBrain ECAPA (`spkrec-ecapa-voxceleb`) | *Status: Chromaprint `default`, ECAPA `candidate` (decyzja zespołu 2026-11-21, zgoda użytkownika).* Chromaprint zapisuje odcisk akustyczny (`audio.fingerprint`, tablica int32, ok. 8 subodcisków/s, bez wag) i wykrywa to samo nagranie po rekompresji lub przycięciu; porównanie `features_lib.fingerprint_match` (zgodność bitów przy najlepszym przesunięciu; wspólny fragment co najmniej 40 subodcisków, ok. 5 s, i połowa krótszego nagrania; losowe bity dają 0,5, tło prawdziwych nagrań jest wyższe). Ograniczenie: wspólny fragment krótszy niż połowa krótszego nagrania (np. ten sam 10-sekundowy dżingiel w dwóch 60-sekundowych spotach) daje wynik na poziomie tła; `min_fraction` w `CHROMAPRINT_MATCH` do ustalenia razem z progiem. ECAPA zapisuje odcisk głosu (`audio.speaker_embedding`, 192d, kosinus): ten sam lektor przy innym tekście. Model trenowano na VoxCeleb (głównie angielski); przed włączeniem do profilu domyślnego zmierzyć rozdzielenie tych samych i różnych mówców na prawdziwych reklamach, także z muzyką w tle. Odcisk dźwięku, głos i transkrypcja jednego nagrania mają wspólny `origin_id`. Detektor deepfake głosu odłożony. Kontrola techniczna 2026-11-21 na własnych nagraniach syntezatora `say` (to nie pomiar jakości): Chromaprint — rekompresja AAC 0,998, wycinek 7 s 0,963 (przesunięcie 3 s), ścieżka audio z MP4 0,932, ten sam tekst innym głosem 0,72, inny tekst 0,60; ECAPA — ten sam głos, inny tekst 0,92, inny głos 0,45–0,46. Koszt (aarch64, limit 4 CPU, nagrania ok. 15 s): Chromaprint p50 19 ms, ECAPA p50 619 ms przy 1 wątku i 260 ms przy 4, ok. 150 MB pamięci. Wysoka zgodność Chromaprint dla tego samego tekstu z syntezatora i krótkich wspólnych fragmentów oznacza, że próg trzeba ustalić na prawdziwych nagraniach. |
| **Pochodzenie obrazu** · reverse-SynthID v4, klasyfikator AI/human oparty na SigLIP | *Status: `excluded` (`grouping: false` w `runs/*.json`).* Pominąć w grupowaniu. Ten sam generator może służyć niezależnym kampaniom. Materiały walidacyjne producenta detektora i przykłady syntetyczne nadają się do próby uruchomienia. |
| **Ocena „czy to fake”** · Effort (CLIP ViT-L/14, ICML 2025), kontener `aigi_effort` | *Status: `excluded` (zgoda użytkownika 2026-11-21).* Wynik `ai.effort` (`fake_prob`, `label`) per reklama do pokazania analitykowi, poza grupowaniem. Fałszywe alarmy na zrzutach z ramką i tekstem trzeba zmierzyć na materiałach pewnie nie-AI. |

Porównanie całych 13 zrzutów dało 78 par. pHash o długości 64 bitów dał odległość 16 dla p3/p4 i 14 dla p5/p8, chociaż w tej drugiej parze transkrypcje są różne. Te same transkrypcje występują w czterech parach, jednej z p3/p4 i trzech z p1/p7/p15. To obserwacje podobieństwa cech. Trafność przypisania do kampanii wymaga niezależnych etykiet. [Dane i pochodzenie](../docs/NASK_DATA.md) · [Tesseract](https://tesseract-ocr.github.io/tessdoc/) · [Dopasowania OpenCV](https://docs.opencv.org/4.x/dc/dc3/tutorial_py_matcher.html) · [Karta E5](https://huggingface.co/intfloat/multilingual-e5-small) · [DINOv2](https://github.com/facebookresearch/dinov2)

## Ekstrakcja cech (wynik do dalszego użycia)

Statusy w tabeli wyżej sterują profilami: `PROFILE=default` (domyślnie) liczy tylko modele `default`, `PROFILE=eval` dodaje kandydatów, `PROFILE=all` liczy wszystko. Jawne `MODELS=` ma pierwszeństwo przed profilem. Status i uzasadnienie trafiają do `runs/<slug>.json` (`stage`, `decision`, `grouping`).

```bash
cd models
bash build.sh                                   # obrazy z wagami; raz, wymaga sieci
bash extract.sh                                 # wszystkie modele na ../data/nask-hacknation-2026
bash extract.sh face ocr                        # wybrane kontenery
DATA=./data/user MODELS=tesseract,e5-small bash extract.sh ocr text
```

Kolejność kontenerów jest stała, także przy wyborze części z nich: `face ocr asr image_embedding object_detection ai_generated text`. Kontener `text` przetwarza pole `text` reklamy oraz `ocr.text`/`asr.text` zapisane wcześniej przez OCR i ASR. `DATA` wskazuje korpus v0 (`ads.jsonl`, `media/`, opcjonalnie `observations/screenshots.jsonl`) albo luźny katalog. W luźnym katalogu każdy obraz, plik audio lub wideo i `*.txt` staje się reklamą `source.kind=upload` z `ad_id = file-<sha256[:16]>`. Identyczne pliki dostają to samo ID i trafiają do raportu duplikatów w `corpus.json`. `dataset_id` pochodzi z manifestu, a dla luźnego katalogu z nazwy katalogu na hoście (`DATA=./data/user` → `out/features/user/`). `corpus.json` i każdy `runs/<slug>.json` zapisują odcisk korpusu (`fingerprint`). `FeatureStore` i kontener `text` używają tylko wierszy reklam z bieżącego `ads.jsonl` i ostrzegają o przebiegach policzonych na innej wersji korpusu. Opcjonalne `audio_path`/`video_path` w `ads.jsonl` to rozszerzenie kontraktu dla multimediów.

| Plik w `out/features/<dataset_id>/` | Zawartość |
| --- | --- |
| `ads.jsonl`, `corpus.json` | Rekordy `Ad`, na których liczono, tryb wejścia, odcisk korpusu, błędy importu z numerem wiersza i duplikaty. |
| `features/<slug>.jsonl` | Wiersze `Feature`: `object_type` (`ad`), `ad_id`, `family`, `field`, `value`, `origin_id`, `source_ref` (pole źródłowe, ścieżka pliku albo metoda tekstu pochodnego), `method_version` oraz `status`, `reason`, `source_field`, `extractor`, `use_case`. Jeden plik na ekstraktor, zapisywany atomowo. Ponowne uruchomienie nadpisuje tylko jego pliki. |
| `vectors/<slug>/<field>.npy` | Embeddingi float32 `[n, d]`, wiersze L2-znormalizowane. `value` wskazuje plik, wiersz i wymiar. |
| `arrays/<slug>/<field>.npz` | Tablice o zmiennym rozmiarze (deskryptory ORB, odciski Chromaprint). `value` wskazuje plik, klucz, kształt i typ. |
| `runs/<slug>.json` | `status` (`ok`/`failed`) i `load_error`, `method_version`, parametry, licencja, ID obrazu Dockera, rewizja kodu, odcisk korpusu, czas, CPU, liczba wierszy `ok` i `unavailable`. |
| `analysis/neighbors.md` | Top-3 sąsiadów każdej reklamy według każdej metody. Służy do porównania modeli. Progów i decyzji `strong`/`similar` tu nie ustalamy. |

`origin_id` pochodzi kolejno z jawnego `image_origin`/`text_origin`/`audio_origin` rekordu, z `observation_group` (rekord lub `screenshots.jsonl`), a w ostateczności ma postać `<ad_id>#<pole>`. Zgodnie z kontraktem tekst reklamy z obrazem domyślnie dziedziczy pochodzenie obrazu. Cechy obrazu, tekst OCR, domeny z OCR (`ocr.urls`) i liczone z OCR embeddingi (`source_field = "ocr.text@<metoda>"`) mają to samo pochodzenie, więc nie są niezależną rodziną dowodu wobec obrazu. Analogicznie `asr.text`, `audio.fingerprint` i `audio.speaker_embedding` dzielą pochodzenie nagrania (`<ad_id>#audio_path` lub `#video_path`). Przyczyny braku dla audio: `no_audio_input`, `no_audio_stream` (wideo bez dźwięku), `unreadable_audio: …`, `audio_too_short`, `silent_audio` (ścieżka o szczycie poniżej ok. -80 dBFS, np. nagranie ekranu bez dźwięku; decyzja zespołu 2026-11-21, bo odcisk i głos ciszy pasowałyby do każdego niemego nagrania), `no_speech_detected` (tylko `asr.text`: dźwięk bez mowy).

**Braki.** Brak wejścia daje wiersz `unavailable` z przyczyną w polu głównym ekstraktora (`primary_field` w `runs/<slug>.json`, np. `face.count`, `ocr.text`, `image.phash`, `qr.count`). Możliwe przyczyny to `no_image_input`, `file_not_found: …`, `path_outside_corpus: …`, `unreadable_image: …`, `image_too_large: …` (ponad 60 MP lub 50 MB) i `error: …`. Pojedyncze pole może mieć własną przyczynę: przy nieczytelnym obrazie `image.sha256` jest liczony z bajtów, a `image.phash` dostaje `unavailable`. Brak śladu to też `unavailable`, a nie pusta wartość: `qr.values`/`qr.urls` → `no_qr_detected`, `ocr.urls` → `no_url_in_ocr_text`. Dzięki temu silnik nie liczy pustych pól jako porównywalnej rodziny. Model, który się nie ładuje, daje `model_load_error: …` dla każdego wejścia i `status: failed`. Kolejne modele i kontenery liczą się dalej, a `extract.sh` kończy się kodem 1 i listą nieudanych kontenerów.

**Wersja metody.** `method_version` = `<use_case>/<model>@<wersja>+<rewizja wag HF>#p<hash parametrów>`. Zmiana wag, promptów CLIP, zapytań detektora, etykiet tematów, prefiksu E5 czy progów zmienia wersję. Parametry są zapisane w `runs/<slug>.json`. Ustawienia: EasyOCR `paragraph=True` (bez `ocr.confidence`), Whisper `language="pl"` (stąd brak pola języka), E5 z prefiksem `query: ` dla każdego tekstu.

| Kontener | Pola `field` |
| --- | --- |
| `face` | `face.count`, `face.embedding` (wektor, ramka, `det_score`; buffalo_l także wiek i płeć) |
| `ocr` | `ocr.text`, `ocr.urls` (rodzina `infrastructure`; domeny z listą TLD, także z adresów e-mail; heurystyka bez pomiaru pominięć); Tesseract `ocr.confidence`, EasyOCR `ocr.blocks` |
| `asr` | `asr.text`, `asr.duration_s`, `asr.segments` (Whisper, rodzina `text`); `audio.fingerprint` (tablica int32 w `arrays/`), `audio.duration_s` (Chromaprint); `audio.speaker_embedding` (ECAPA 192d) |
| `image_embedding` | `image.embedding` (DINOv2; CLIP odłożony), `image.clip_tags`, `image.sha256`, `image.size`, `image.phash`, `image.dhash`, `image.orb` (deskryptory w `arrays/`); kontener liczy też `qr.count`, `qr.values`, `qr.urls` (use case `qr`) |
| `object_detection` | `objects.detections`, `objects.labels` |
| `ai_generated` | `ai.synthid`, `ai.generated` |
| `text` | `text.embedding`, `text.topic` |

```python
from features_lib import FeatureStore, hamming_hex, tfidf_similarity  # common/features_lib.py; numpy, TF-IDF wymaga scikit-learn
fs = FeatureStore("out/features/nask-hacknation-2026")
fs.methods()                                               # dostępne (method_version, field) i liczniki
ids, S, best = fs.ad_similarity(method_version, "face.embedding")  # cosine reklama×reklama
tess = next(m["method_version"] for m in fs.methods() if m["field"] == "ocr.text" and "tesseract" in m["method_version"])
keys, St, vec = tfidf_similarity({r["ad_id"]: r["value"] for r in fs.rows(field="ocr.text", method=tess)})  # domyślny tekst
left, right = best[(i, j)]                                 # wiersze Feature obu stron jako dowód
```

## Effort — ocena, czy obraz jest wygenerowany przez AI

Kontener `tm-aigi_effort` zawiera kod [Effort](https://github.com/YZY-stack/Effort-AIGI-Detection) z przypiętego commita `96f5dea` i CLIP ViT-L/14. Checkpointu `.pth` nie ma w obrazie. Wrzuć go do `models/weights/effort/`; katalog jest ignorowany przez Git i montowany tylko do odczytu jako `training/weights/`. **Do zrobienia:** udostępnić checkpoint zespołowi przez Git LFS albo Google Drive i opisać tu pobranie. Effort ocenia obrazy nieoznaczone przez reverse-SynthID (`./provenance.sh <katalog>`, opis w [benchmarku](benchmark/README.md)), więc bez wag parametr pochodzenia obrazu jest niepełny.

```bash
bash build.sh aigi_effort
./effort.sh --detector_config training/config/detector/effort.yaml \
  --weights ./training/weights/effort_clip_L14_trainOn_sdv14.pth --image ~/MNW/AI_Images/
./effort.sh                                    # to samo z domyślnymi argumentami (IMAGE=... zmienia katalog)
PROFILE=all ./extract.sh aigi_effort           # pole ai.effort w out/features/<dataset_id>/
```

`effort.sh` uruchamia w kontenerze `demo.py` z katalogu `DeepfakeBench/`, bez sieci, z tymi samymi argumentami i tym samym wyjściem co `python3 training/demo.py …`. Ścieżkę z `--image` montuje pod tą samą ścieżką, tylko do odczytu. Ekstraktor wywołuje tę samą funkcję inferencji z `demo.py`. Inny checkpoint wskazuje zmienna `EFFORT_WEIGHTS=<plik.pth>`. Do `demo.py` dodano przy budowie brakujący `import sys`.

**Ładowanie wag.** Oryginalny loader wczytuje cały CLIP-L/14 i liczy 96 rozkładów SVD, po czym nadpisuje wynik checkpointem. `containers/aigi_effort/fast_load.py` buduje wieżę wizyjną z samej konfiguracji, składa wagi warstw uwagi raz przy starcie i wczytuje checkpoint ze sprawdzeniem, że żaden klucz nie został pominięty. Pomiar na 8 rdzeniach, bez innych zadań (2026-11-22): ładowanie 134 s → 1,4 s, inferencja 1,1 s → 0,57 s na obraz, `fake_prob` i etykieta identyczne na 60 zrzutach. Gdy szybkie ładowanie się nie powiedzie (np. checkpoint ma inny układ kluczy), kod wraca do `demo.load_detector` i sprawdza, czy co najmniej 90% kluczy pasuje do modelu. `EFFORT_SLOW=1 ./effort.sh …` uruchamia niezmieniony `training/demo.py`.

## Ewaluacja decyzji

`bash evaluate.sh` buduje korpus wariantów: każdy zrzut dostaje kadr 70×75%, róg 80×80% oraz zmniejszenie z JPEG q60. Następnie liczy cechy profilu `eval` na NASK, na wariantach i na syntetycznych parafrazach z `data/sample/texts`, mierzy p95 OCR i zapisuje `out/eval/decisions.json` oraz `decisions.md`.

| Decyzja | Pomiar | Reguła (założenie zespołu) |
| --- | --- | --- |
| Obraz | top-1/top-3 wariantu wśród 13 oryginałów; dodatkowe trafienia top-3 względem pHash; wyniki rzeczywistych par tymczasowych; wszystkie pary oryginałów z różnych grup i z tym samym `screenshot_type` powyżej progu pomocniczego (remisy na niekorzyść metody) | kandydat wchodzi jako sygnał rankingu przy zysku top-3, gdy każda para rzeczywista przewyższa najwyższą niepowiązaną parę z tą samą ramką, a próg pomocniczy ma nad nią ≥ 5% zapasu |
| Tekst | MRR, hit@1, hit@3 dla TF-IDF `char_wb` 3–5 i E5-small (`query: ` po obu stronach) | embedding wchodzi obok TF-IDF przy dodatkowym trafieniu top-3 bez wzrostu fałszywych przypisań (top-1 z innej grupy) |
| OCR | CER, pełne frazy i domeny względem `eval/ocr_reference.jsonl`, p95 | EasyOCR zastępuje Tesseract przy CER niższym o ≥ 5 pkt proc., nie mniejszej liczbie fraz i p95 w budżecie |

**Wynik z 2026-11-21** (13 zrzutów NASK, 39 wariantów syntetycznych, 7 zapytań parafraz; szczegóły w `out/eval/decisions.md`):

| Metoda | top-3 wariantu | Pary z tą samą ramką ≥ próg pomocniczy* | Decyzja |
| --- | --- | --- | --- |
| pHash | 22/39 (kadr 8/13, róg 1/13; remisy na niekorzyść) | 38/44 | zostaje dla duplikatów i ponownej kompresji (13/13) |
| DINOv2-small | 39/39; pary rzeczywiste 0,68–0,94 vs najwyższa niepowiązana 0,61 | 0/44 | `default` jako sygnał rankingu obok pHash |
| ORB | 39/39 (top-1 37/39); niepowiązane zrzuty z tą samą ramką do 216 dopasowań przy progu 223 | 0/44 | `candidate`: wynik napędza wspólny interfejs platformy |
| TF-IDF / E5-small, parafrazy | hit@3 7/7 / 7/7; MRR 0,929 / 1,0 (różnica z jednego zapytania dopasowanego po temacie) | — | TF-IDF domyślny, E5 `candidate` |
| Tesseract / EasyOCR, p95 (4 wątki, 13 pomiarów) | 362 ms / 14 536 ms | — | Tesseract (zgoda użytkownika); CER niezmierzony |

\* Próg pomocniczy przyjmuje 90% prawdziwych par wariant–oryginał i **nie jest punktem pracy**. Liczba to wszystkie pary oryginałów z różnych tymczasowych grup (pojedyncze reklamy to brak udokumentowanego powiązania, nie potwierdzone różne kampanie) i z tym samym `screenshot_type`, które go przekraczają. Warianty są syntetyczne, czyli te same piksele po kadrowaniu lub kompresji. Ponowny render kreacji przez nadawcę może dać słabszy wynik ORB. Próba parafraz jest mała (7 zapytań).

Etykiety w `eval/labels_nask_provisional.jsonl` są tymczasowe (p3/p4, p1/p7/p15, reszta pojedynczo) i nie wchodzą do silnika. Test tekstowy na NASK jest trywialny, bo grupy mają identyczne transkrypcje; informację o parafrazach dają dane syntetyczne. CER wymaga pełnych transkrypcji przepisanych z obrazu, nie z wyniku OCR. Format jednego wiersza: `{"ad_id": "...", "text": "pełny tekst", "key_phrases": ["..."], "domains": ["..."]}`. Bez tego pliku raport oznacza CER jako niemierzalny.

## Uruchomienie dostępne dziś

**Testy laboratorium.** Z katalogu głównego repozytorium wykonaj polecenie w PowerShell. Na Linuksie użyj `python3` w miejsce `py -3`. Wystarcza Python 3.10+ i zapisywalny katalog plików tymczasowych. Dziewięć testów sprawdza odczyt korpusu i pochodzenie, raport, częściowe wyniki i oznaczanie nieudanych pomiarów. Testy kontraktu cech i ewaluacji wymagają numpy (część także scikit-learn i OpenCV) i bez nich są pomijane; w kontenerze uruchamia je `docker run --rm --network none -v "$PWD:/repo:ro" -w /repo tm-text python -B -m unittest discover -s models/tests`.

```powershell
py -3 -B -m unittest discover -s models/tests -v
```

**Pierwszy pomiar CPU.** Użyj Bash na Linuksie lub WSL2 z dostępnym z tej powłoki Dockerem w trybie kontenerów linuksowych i poleceniem `python3`. Budowanie wymaga sieci i miejsca na bazę PyTorch oraz pobierane wagi. Filtr `MODELS` działa podczas inferencji. Budowanie OCR pobiera również EasyOCR. Zacznij w katalogu głównym repozytorium z plikami Bash zakończonymi LF.

```bash
cd models
docker info
bash bench.sh build ocr
DATA=../data/nask-hacknation-2026 CPUS=4 MEM=6g THREADS=1 MODELS=tesseract bash bench.sh run ocr
```

Skrypt nada nowemu przebiegowi nazwę z daty i czasu. Zapisze `out/benchmark/<RUN>/ocr.json`, log oraz `summary.md`. Ponowne użycie istniejącej nazwy `RUN` powoduje błąd. Dane w kontenerze są zamontowane tylko do odczytu. Inferencja działa z `--network none`. W kopii Windows z końcami CRLF można w tej samej sesji Bash użyć funkcji poniżej i zastąpić w powyższych wywołaniach `bash bench.sh` nazwą `bench`. Funkcja normalizuje końce wierszy w pamięci. Polecenie `bench help` wyświetla opis.

```bash
bench() { bash -c "$(tr -d '\r' < bench.sh)" ./bench.sh "$@"; }
```

Do porównania użyj identycznego `DATA`, `CPUS`, `MEM`, `THREADS`, `WARMUP`, `REPEATS` i `MAX_ITEMS` w obu przebiegach. Warianty tekstowe buduje `bash bench.sh build text`, a wizualne `bash bench.sh build image_embedding`. Wykonaj wybrany eksperyment z katalogu laboratorium po zbudowaniu odpowiedniego obrazu.

```bash
DATA=../data/nask-hacknation-2026 THREADS=1 MODELS=multilingual-e5-small bash bench.sh run text
DATA=../data/nask-hacknation-2026 THREADS=1 MODELS=dinov2-small bash bench.sh run image_embedding
```

Polecenie `bash bench.sh report out/benchmark/NAZWA_PRZEBIEGU` odtwarza raport w podanym katalogu. Domyślnie laboratorium bierze maksymalnie 20 elementów, jedno wejście na rozgrzewkę, trzy powtórzenia oraz konfiguracje jednego i wszystkich przydzielonych wątków. Pominięcie zestawu przez filtr modeli jest dopuszczalne, gdy inny wybrany model dostarczył wynik. Błąd kontenera, niepełny zestaw lub brak wejść dla wybranego modelu wymaga sprawdzenia raportu i logu. Skrypt raportujący sygnalizuje taki przypadek niezerowym kodem wyjścia.

**Własne dane.** Benchmark przyjmuje te same wejścia co ekstrakcja: korpus v0 albo luźny katalog plików. Każdy obraz trafia do wszystkich kontenerów obrazowych, a podkatalogi służą tylko do opisu (`ad_ref`). Opcjonalne `bash bench.sh samples` wymaga wcześniejszego zbudowania obrazów `face` i `ai_generated`. Odtwarza przykłady w `data/sample/`, w tym materiały testowe podmiotów trzecich. Generowanie ścieżek audio zależy od macOS z polskim głosem Zosia. Do ASR na Linux/Windows dostarcz własne pliki audio.

## Pomiar jakości i decyzja o GPU

Raport CPU podaje p50/p95 inferencji, czas ładowania, przepustowość, zużycie CPU na element i pamięć próbkowaną co 100 ms. Latencja i CPU/elem pochodzą tylko z udanych wywołań. Liczby `n_ok`, `n_unavailable` i `n_errors` są w JSON. Wyjątek modelu albo brak udanego wywołania oznacza konfigurację jako błąd i raport kończy się kodem niezerowym. Szczyt pamięci obejmuje cały kontener, także proces nadrzędny harnessu. Krótki pik pamięci może wypaść między próbkami. Próbka benchmarku to pierwsze `MAX_ITEMS` wejść po sortowaniu po `ad_id`, co w luźnym katalogu miesza podkatalogi. Modele tekstowe są mierzone na polu `text`, bez dłuższego tekstu OCR i ASR. Cgroup v2 obejmuje cały kontener, procedura zastępcza wykorzystuje psutil. Uruchamiaj jeden model i jeden wariant wątków na przebieg. Zapisz procesor, limity, liczbę plików, odcisk danych, identyfikator obrazu i dokładne rewizje pobranych wag. Część źródeł korzysta z ruchomych wersji. [Implementacja pomiaru](common/bench.py)

Na zbiorze rozwojowym porównaj sam tekst, pełną bazę klasyczną i tę samą bazę z **jednym** embeddingiem. B przypisuje każdy przeoczony przypadek do błędu odczytu, wyszukiwania lub reguły scalania. Najpierw poprawiamy właściwy etap. Embedding wolno włączyć, gdy odzyska dodatkowy zgodny wariant w top-3, utrzyma lub obniży liczbę fałszywych przypisań i zmieści się w budżecie. Cel projektowy to p95 do 5 s od przyjęcia obrazu do wyniku na gotowym indeksie. Czas OCR zapisujemy także osobno. Raport kosztów pojedynczego modelu nie mierzy tej ścieżki. Po zamrożeniu konfiguracji mierzymy raz na odłożonych rodzinach. Publikujemy liczniki i mianowniki dla znanych oraz nowych kampanii, liczbę wstrzymań i oddzielne wyniki na danych syntetycznych. [Plan ewaluacji](../docs/MVP.md)

Dostępne stanowisko GPU ma RTX 3050 Laptop z 4 GiB VRAM. Obecny skrypt i obrazy wykonują obliczenia na CPU. Planowany eksperyment GPU ma własny obraz z PyTorch CUDA i lokalnymi wagami. Najpierw sprawdzamy zgodność sterownika i widoczność GPU w kontenerze. Ładujemy jeden wybrany model z partią 1 i mierzymy p95, VRAM oraz koszt odczytu OCR przy tych samych wejściach co na CPU. Po przekroczeniu pamięci lub budżetu demonstrator korzysta z pełnej ścieżki CPU. [Plan budowy](../docs/INSTRUKCJA_BUDOWY.md)

## Dane, licencje i pakiet dla jury

Cechy w `out/features/` oraz JSON benchmarku zawierają prywatny tekst OCR, identyfikatory i wektory. Przechowuj je w dostępie zespołu i jury. Przed eksportem sprawdź również kontekst budowania Dockera, logi i historię Git. Do publicznego przykładu użyj własnych materiałów o ustalonych prawach. [Zasady NASK](../docs/NASK_ZADANIE.md) · [Regulamin](../docs/NASK_REGULAMIN.md)

Ewidencja licencji powinna podawać dokładny pakiet, rewizję wag, źródło, warunki i wymagane noty. Tesseract i EasyOCR deklarują Apache-2.0, E5-small MIT, DINOv2 Apache-2.0. Oznaczenia pozostałych kandydatów znajdują się w polach `license` klas ekstraktorów w [kontenerach](containers/) i w `runs/<slug>.json` każdej ekstrakcji. Sprawdź je u producenta przed dołączeniem wag. Wagi buffalo_l ograniczono do badań niekomercyjnych. Effort (kod i wagi) ma licencję CC BY-NC 4.0, czyli niekomercyjną z uznaniem autorstwa. Eksperymentalny reverse-SynthID ma warunki badawcze, niekomercyjne i wymaganą atrybucję „reverse-SynthID by Alosh Denny — github.com/aloshdenny/reverse-SynthID”. Retencja i udostępnienie wyniku wymagają uwzględnienia także warunków danych wejściowych. [InsightFace](https://github.com/deepinsight/insightface#license) · [reverse-SynthID](https://github.com/aloshdenny/reverse-SynthID)
