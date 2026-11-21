# Laboratorium modeli ScamGraph

Siedem kontenerów uruchamia osiem rodzajów eksperymentów na CPU. Z każdego udanego przebiegu można odczytać wynik ekstrakcji i jego koszt. W sprawdzonym katalogu `results/` jest tylko `.gitkeep`. Skuteczność modeli na kampaniach NASK, zużycie pamięci i czas działania na docelowym komputerze czekają na pomiar. [Skrypt uruchomieniowy](bench.sh) · [Kod pomiaru](common/bench.py) · [Raport](scripts/report.py)

## Który eksperyment odpowiada na problem analityka?

| Rodzina i implementacje w repozytorium | Decyzja i sposób sprawdzenia |
| --- | --- |
| **OCR** · Tesseract 5 `pol+eng`, EasyOCR `pl/en` | Zaczynamy od Tesseract. B przygotowuje pełne transkrypcje wybranych *kadrów*. Porównuje oba silniki przez odsetek błędnych znaków (CER), poprawne odczytanie całej charakterystycznej frazy lub domeny i p95. Teksty w lokalnym korpusie to ręczne fragmenty. Wykorzystanie fragmentu jako pełnej referencji błędnie ukarałoby poprawnie odczytane dodatkowe słowa. |
| **Obraz** · pHash/dHash, DINOv2-small, CLIP ViT-B/32 | Dla identycznego pliku wystarcza SHA-256. Dla podobnego kadru sprawdzamy pHash. Po przeoczeniu wykadrowanej kreacji porównujemy go z dopasowaniem lokalnych punktów ORB w OpenCV i DINOv2-small. Mierzymy dodatkowe poprawne wyniki top-3 oraz pomyłki przy wspólnej ramce platformy. CLIP odkładamy do zadania wyszukiwania obrazów o wspólnym znaczeniu. |
| **Tekst** · multilingual-e5-small, BGE-M3 | Punktem odniesienia będzie znakowy TF-IDF `char_wb` 3–5. E5-small testujemy, gdy pominięta parafraza różni się słownictwem. Dla symetrycznego porównania E5 dodajemy `query: ` do obu tekstów. Porównujemy miejsce właściwej emisji w rankingu. BGE-M3 ma sens po wykazaniu powtarzalnego błędu mniejszego modelu. |
| **Temat** · MiniLMv2-L6 XNLI, mDeBERTa-v3-base XNLI | Odłożyć. Zestaw zwraca jedną z zadanych kategorii także dla tekstu spoza listy. Dwie różne kampanie mogą reklamować leki. |
| **Obiekty** · Grounding DINO tiny, OWLv2 base | Odłożyć. Kod zwraca rozpoznane kategorie. Dla kodu QR bardziej użyteczne jest porównanie lokalnie zdekodowanych wartości. Wspólne logo lub telefon wymaga dalszych dowodów. |
| **Twarze** · YuNet + SFace, InsightFace buffalo_l | Odłożyć. Kontener zapisuje m.in. ramki i rozmiar wektora. Test powiązań wymagałby uprawnionej bazy referencyjnej, weryfikacji wag oraz różnych kampanii z tą samą osobą. |
| **Mowa** · faster-whisper base/small int8 | Lokalny zbiór reklam składa się z obrazów. Przy otrzymaniu nagrań przygotować pełne transkrypcje i mierzyć błędy słów, odzyskane frazy oraz czas na minutę nagrania. Bieżący eksperyment zapisuje pierwsze 200 znaków transkrypcji. |
| **Pochodzenie obrazu** · reverse-SynthID v3/v4, klasyfikator AI/human oparty na SigLIP | Pominąć w grupowaniu. Ten sam generator może służyć niezależnym kampaniom. Materiały walidacyjne producenta detektora i przykłady syntetyczne nadają się do próby uruchomienia. |

Porównanie całych 13 zrzutów dało 78 par. pHash o długości 64 bitów dał odległość 16 dla p3/p4 i 14 dla p5/p8, chociaż w tej drugiej parze transkrypcje są różne. Te same transkrypcje występują w czterech parach, jednej z p3/p4 i trzech z p1/p7/p15. To obserwacje podobieństwa cech. Trafność przypisania do kampanii wymaga niezależnych etykiet. [Dane i pochodzenie](../docs/NASK_DATA.md) · [Tesseract](https://tesseract-ocr.github.io/tessdoc/) · [Dopasowania OpenCV](https://docs.opencv.org/4.x/dc/dc3/tutorial_py_matcher.html) · [Karta E5](https://huggingface.co/intfloat/multilingual-e5-small) · [DINOv2](https://github.com/facebookresearch/dinov2)

## Uruchomienie dostępne dziś

**Testy laboratorium.** Z katalogu głównego repozytorium wykonaj polecenie w PowerShell. Na Linuksie użyj `python3` w miejsce `py -3`. Wystarcza Python 3.10+ i zapisywalny katalog plików tymczasowych. Cztery testy sprawdzają odczyt danych, raport i zachowanie częściowych wyników.

```powershell
py -3 -B -m unittest discover -s testowanie_modeli/tests -v
```

**Pierwszy pomiar CPU.** Użyj Bash na Linuksie lub WSL2 z dostępnym z tej powłoki Dockerem w trybie kontenerów linuksowych i poleceniem `python3`. Budowanie wymaga sieci i miejsca na bazę PyTorch oraz pobierane wagi. Filtr `MODELS` działa podczas inferencji. Budowanie OCR pobiera również EasyOCR. Zacznij w katalogu głównym repozytorium z plikami Bash zakończonymi LF.

```bash
cd testowanie_modeli
docker info
bash bench.sh build ocr
DATA=../data/nask-hacknation-2026 CPUS=4 MEM=6g THREADS=1 MODELS=tesseract bash bench.sh run ocr
```

Skrypt nada nowemu przebiegowi nazwę z daty i czasu. Zapisze `results/<RUN>/ocr.json`, log oraz `summary.md`. Ponowne użycie istniejącej nazwy `RUN` powoduje błąd. Dane w kontenerze są zamontowane tylko do odczytu. Inferencja działa z `--network none`. W kopii Windows z końcami CRLF można w tej samej sesji Bash użyć funkcji poniżej i zastąpić w powyższych wywołaniach `bash bench.sh` nazwą `bench`. Funkcja normalizuje końce wierszy w pamięci. Polecenie `bench help` wyświetla opis.

```bash
bench() { bash -c "$(tr -d '\r' < bench.sh)" ./bench.sh "$@"; }
```

Do porównania użyj identycznego `DATA`, `CPUS`, `MEM`, `THREADS`, `WARMUP`, `REPEATS` i `MAX_ITEMS` w obu przebiegach. Warianty tekstowe buduje `bash bench.sh build text`, a wizualne `bash bench.sh build image_embedding`. Wykonaj wybrany eksperyment z katalogu laboratorium po zbudowaniu odpowiedniego obrazu.

```bash
DATA=../data/nask-hacknation-2026 THREADS=1 MODELS=multilingual-e5-small bash bench.sh run text
DATA=../data/nask-hacknation-2026 THREADS=1 MODELS=dinov2-small bash bench.sh run image_embedding
```

Polecenie `bash bench.sh report results/NAZWA_PRZEBIEGU` odtwarza raport w podanym katalogu. Domyślnie laboratorium bierze maksymalnie 20 elementów, jedno wejście na rozgrzewkę, trzy powtórzenia oraz konfiguracje jednego i wszystkich przydzielonych wątków. Pominięcie zestawu przez filtr modeli jest dopuszczalne, gdy inny wybrany model dostarczył wynik. Błąd kontenera, niepełny zestaw lub brak wejść dla wybranego modelu wymaga sprawdzenia raportu i logu. Skrypt raportujący sygnalizuje taki przypadek niezerowym kodem wyjścia.

**Własne dane.** Podaj `DATA` jako katalog z `texts/*.txt`, `images/` lub `audio/`. Można podać osobne `screenshots/`, `faces/` i `ai_generated/`. Na korpusie projektu laboratorium odczytuje `ads.jsonl` i `media/`. Opcjonalne `bash bench.sh samples` wymaga wcześniejszego zbudowania obrazów `face` i `ai_generated`. Odtwarza przykłady w `data/sample/`, w tym materiały testowe podmiotów trzecich. Generowanie ścieżek audio zależy od macOS z polskim głosem Zosia. Do ASR na Linux/Windows dostarcz własne pliki audio.

## Pomiar jakości i decyzja o GPU

Raport CPU podaje p50/p95 inferencji, czas ładowania, przepustowość, zużycie CPU na element i pamięć próbkowaną co 100 ms. Krótki pik pamięci może wypaść między próbkami. Cgroup v2 obejmuje cały kontener, procedura zastępcza wykorzystuje psutil. Uruchamiaj jeden model i jeden wariant wątków na przebieg. Zapisz procesor, limity, liczbę plików, odcisk danych, identyfikator obrazu i dokładne rewizje pobranych wag. Część źródeł korzysta z ruchomych wersji. [Implementacja pomiaru](common/bench.py)

Na zbiorze rozwojowym porównaj sam tekst, pełną bazę klasyczną i tę samą bazę z **jednym** embeddingiem. B przypisuje każdy przeoczony przypadek do błędu odczytu, wyszukiwania lub reguły scalania. Najpierw poprawiamy właściwy etap. Embedding wolno włączyć, gdy odzyska dodatkowy zgodny wariant w top-3, utrzyma lub obniży liczbę fałszywych przypisań i zmieści się w budżecie. Cel projektowy to p95 do 5 s od przyjęcia obrazu do wyniku na gotowym indeksie. Czas OCR zapisujemy także osobno. Raport kosztów pojedynczego modelu nie mierzy tej ścieżki. Po zamrożeniu konfiguracji mierzymy raz na odłożonych rodzinach. Publikujemy liczniki i mianowniki dla znanych oraz nowych kampanii, liczbę wstrzymań i oddzielne wyniki na danych syntetycznych. [Plan ewaluacji](../docs/MVP.md)

Dostępne stanowisko GPU ma RTX 3050 Laptop z 4 GiB VRAM. Obecny skrypt i obrazy wykonują obliczenia na CPU. Planowany eksperyment GPU ma własny obraz z PyTorch CUDA i lokalnymi wagami. Najpierw sprawdzamy zgodność sterownika i widoczność GPU w kontenerze. Ładujemy jeden wybrany model z partią 1 i mierzymy p95, VRAM oraz koszt odczytu OCR przy tych samych wejściach co na CPU. Po przekroczeniu pamięci lub budżetu demonstrator korzysta z pełnej ścieżki CPU. [Plan budowy](../docs/INSTRUKCJA_BUDOWY.md)

## Dane, licencje i pakiet dla jury

JSON z wynikami może zawierać prywatny tekst OCR, identyfikatory i wektory. Przechowuj katalogi przebiegów w dostępie zespołu i jury. Przed eksportem sprawdź również kontekst budowania Dockera, logi i historię Git. Do publicznego przykładu użyj własnych materiałów o ustalonych prawach. [Zasady NASK](../docs/NASK_ZADANIE.md) · [Regulamin](../docs/NASK_REGULAMIN.md)

Ewidencja licencji powinna podawać dokładny pakiet, rewizję wag, źródło, warunki i wymagane noty. Tesseract i EasyOCR deklarują Apache-2.0, E5-small MIT, DINOv2 Apache-2.0. Oznaczenia pozostałych kandydatów znajdują się przy `ModelSpec` w [kontenerach](containers/). Sprawdź je u producenta przed dołączeniem wag. Wagi buffalo_l ograniczono do badań niekomercyjnych. Eksperymentalny reverse-SynthID ma warunki badawcze, niekomercyjne i wymaganą atrybucję „reverse-SynthID by Alosh Denny — github.com/aloshdenny/reverse-SynthID”. Retencja i udostępnienie wyniku wymagają uwzględnienia także warunków danych wejściowych. [InsightFace](https://github.com/deepinsight/insightface#license) · [reverse-SynthID](https://github.com/aloshdenny/reverse-SynthID)
