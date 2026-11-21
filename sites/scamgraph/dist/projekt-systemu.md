# ScamGraph — projekt systemu

Projekt dla zespołu HackNation 2026, 21 listopada 2026. Status: decyzje do implementacji. Strona Sites ilustruje reguły na danych syntetycznych. Konkursowy demonstrator to oddzielna, lokalna aplikacja.

## Wynik dla analityka

Analityk dodaje PNG/JPEG z reklamą, opcjonalnie dołącza tekst i znany adres celu wraz z ich pochodzeniem. Otrzymuje propozycję grupy lub wskazanie, czemu decyzja wymaga dalszej pracy. Może otworzyć każdy dowód, zobaczyć obie wartości, ich źródła i dostępność metod. Grupa to hipoteza o kampanii. Profil grupy podaje wspólne ślady, liczbę różnych emisji i ich ID.

## Co ocenia NASK

Opis zadania wymaga graficznego demonstratora (obecność 0/1) i kładzie nacisk na przydatność analizy, pozyskanie reklam oraz sposób wykrywania podobieństw i grupowania. Opublikowany opis pozostawia wybór reprezentacji i technologii zespołowi. Scheduler jest dodatkiem. Sposób identyfikacji osoby jest dowolny, organizator sugeruje małą bazę referencyjną. W pierwszej godzinie właściciel ewaluacji potwierdza u mentora zakres identyfikacji i ewentualną osobną punktację. §2 regulaminu odsyła do kryteriów zadania. Progi modelu i miary niżej są decyzjami zespołu. §4 dotyczy praw do wkładu i przeniesienia praw przez zwycięzców. Osoba od źródeł zapisuje pochodzenie, warunki użycia korpusu i licencje zależności oraz wag.

## Dane i pierwsza godzina

1. Wczytaj gotowy katalog `data/nask-hacknation-2026/` w repozytorium. Weryfikacja plików potwierdza 13 rekordów w `ads.jsonl`, 13 poprawnych SHA-256 obrazów oraz 15 osobnych zapisów w `observations/pages.jsonl`. Źródłem jest pakiet 436 plików NASK. Wśród 14 zrzutów było 11 sponsorowanych postów i 3 karty biblioteki Meta. W p1/p2 powtórzono te same pliki. Karty p3/p4 mają różne ID i zachowują dwa rekordy. Dla całego korpusu to 78 par, dla pierwszego przebiegu na 6–10 emisjach 15–45 par.
2. Wszystkie 13 rekordów ma obraz i tekst przepisany ze zrzutu, a 0 ma potwierdzony landing_url. Połącz `observations/screenshots.jsonl` przez ad_id i zachowaj observation_group. Główne dokumenty HTML i żądania w HAR potwierdzają zaobserwowane adresy stron. Warunkiem przypisania celu do reklamy jest udokumentowany związek. Dla p3 domena na karcie różni się od hosta z HAR. Wspólny piksel i sąsiedztwo plików pozwalają zapisać hipotezę. Adres o niepotwierdzonym związku pozostaje osobną obserwacją. W odczytanych HAR nie ma zapisanych przekierowań do importu. Treść HTML i HAR parsujemy offline, zachowując pola potrzebne do dowodu.
3. Pakiet nie zawiera wiarygodnych etykiet kampanii. Wybierz grupę referencyjną, odłożony wariant i podobny kontrprzykład, sprawdź dwie niezależne obserwacje po obu stronach pozytywnej pary. W bibliotece reklam Meta spróbuj odszukać wpisy po ID z kart, a brakujące przykłady można pozyskać z Google Ads Transparency Center po nazwie reklamodawcy lub witrynie. Zapisz zapytanie, region, okres, datę, ID i warunki użycia. Brak drugiego śladu pozostawia parę do oceny człowieka.
4. Osobny katalog trzech URL-i NASK ma wspólne `gad_source` i różne `gad_campaignid`. To próba odporności na popularny parametr. Jawnie syntetyczny korpus pozwala sprawdzić pełny przepływ podczas ustalania etykiet. Przypadki rzeczywiste z niepewną etykietą służą ocenie jakościowej. Liczby podajemy wraz z pochodzeniem próbki.

### Próba ImageHash na dwóch kartach Meta

W pojedynczej próbie na oryginalnych, pełnych PNG karty p3 i p4 dały odciski `9ee1e01e610f7c78` i `9ee17c1ee11e7007`. Odległość Hamminga wyniosła 16/64, choć w obu rekordach zapisano identyczny tekst. Przy progu 6 bitów użytym wyłącznie w interaktywnej ilustracji sygnał wizualny pozostałby poniżej wymaganej zgodności. Przy strojeniu na zbiorze rozwojowym warto porównać pełny zrzut z kadrem kreacji i zapisać pochodzenie obu wariantów. Wynik jednej pary nie wyznacza progu docelowego ani etykiety kampanii.

Odtworzenie z katalogu głównego repozytorium w środowisku z ImageHash 4.3.2 i Pillow 11.3.0:

```python
from pathlib import Path
from PIL import Image
import imagehash

media = Path("data/nask-hacknation-2026/media")
with Image.open(media / "p3-123146.png") as first, Image.open(media / "p4-123420.png") as second:
    print(imagehash.phash(first) - imagehash.phash(second))  # 16
```

## Moduły i ich granice

Jeden proces Pythona, pliki na dysku i indeks cech w pamięci. Podstawowe wywołania można testować niezależnie od Streamlit.

| Właściciel / moduł | Wejście | Wyjście i odbiór |
| --- | --- | --- |
| Źródła / ingest | manifest.json, ads.jsonl, media/ | Zwalidowane Ad, raport importu. Powtórny import zachowuje liczbę emisji. |
| Obraz i OCR / features | Bajty PNG/JPEG i pochodzenie | SHA-256, 64-bitowy pHash, tekst z Tesseract oraz informacja o brakach. Wspólne źródło OCR i obrazu zostaje zapisane. |
| Tekst i URL / features | Tekst, OCR, cel i zapisane przekierowania | Indeks znakowego TF-IDF, fragmenty źródłowe i ostrożnie normalizowane adresy. Wartości oryginalne pozostają dostępne. |
| Silnik / matching | Cechy, konfiguracja i indeks referencyjny | Evidence, PairAssessment, Campaign i MatchResult. Nowy materiał nie zmienia stanu referencyjnego. |
| Interfejs / Streamlit | Formularz i MatchResult | Status, grupa, podobne pojedyncze reklamy, źródła i wartości obok siebie. |
| Ewaluacja i demo / evaluation | Oddzielne etykiety, podział i zamrożona konfiguracja | Porównanie z metodą tekstową, zestaw kontrprzykładów, scenariusz offline. |

Manifest korpusu przechowuje schema_version, dataset_id, opis źródła i czas. Ad wymaga ad_id, source.kind, source.provider, source.collected_at ze strefą i przynajmniej jednego użytecznego pola (tekst, obraz lub zapisany URL). source.kind rozróżnia library, organizer, synthetic i upload. source.record_url wskazuje wpis w bibliotece, landing_url cel reklamy. Zaimportowana ścieżka obrazu musi wskazywać plik wewnątrz media/. Klucz powtórnego importu to dostawca i jego identyfikator, a przy braku identyfikatora dokładny odcisk stabilnych pól rekordu. Różne emisje tego samego pliku zachowują odrębne ID.

Rozszerzenie proponowane do kontraktu v0: przechowuj identyfikator pierwotnej obserwacji przy każdym polu każdego rekordu (mapa field → origin_id). Tożsamość źródła nadaje importer lub wybór pochodzenia w formularzu. OCR, przepisany tekst i URL odczytany ze zrzutu dziedziczą origin_id obrazu. Cel zapisany przez bibliotekę może mieć odrębne pochodzenie. Przy braku pewności traktujemy pochodne jako zależne. Dowód pary zachowuje oba ID pochodzenia, oryginalne wartości i nazwy pól. Dwa dowody są niezależne tylko wtedy, gdy odwołują się do różnych obserwacji zarówno w lewej, jak i prawej reklamie.

## Stos i decyzje algorytmiczne

| Decyzja P0 | Uzasadnienie i ograniczenie |
| --- | --- |
| Python, Streamlit, CPU | Jeden formularz i bezpośrednie wywołania funkcji. Brak usługi sieciowej na ścieżce analizy. |
| Pillow, ImageHash, hashlib | SHA-256 rozpoznaje ponowne użycie pliku. Odległość Hamminga pHash daje porównanie kreacji. Kadrowanie może osłabić wynik. |
| Tesseract + pytesseract, modele pol i eng | OCR lokalny. Pliki językowe i binarkę przygotować na laptopie przed próbą offline. Przy braku modelu pokaż stan i dopuść tekst z oznaczonym źródłem. |
| scikit-learn, TF-IDF char_wb 3–5, cosinus | Tani sposób na odmiany zapisu. Statystyki dopasuj wyłącznie do korpusu referencyjnego. Cytat jako dowód musi faktycznie występować w obu polach. |
| urllib.parse, zapisane metadane | Porównuj pełny cel lub charakterystyczny element o znanym zakresie. Normalizuj wielkość liter hosta i port domyślny, zachowaj semantykę ścieżki i parametrów. Popularny host i ogólne parametry mogą dać tylko sugestię. |
| Lista par i grup w pamięci | Dla 6–10 emisji potrzebujemy 15–45 par. Przechowujemy dowody oraz brakujące rodziny. Ponowny upload kosztuje n porównań. Cache wiąże odcisk korpusu, konfigurację i wersje ekstraktorów. |

Organizator wskazuje ImageHash, OCR i uzasadnianie krawędzi. Wymienia też CLIP/SigLIP, sentence-transformers, MinHash/LSH, HDBSCAN, Neo4j, sygnały infrastrukturalne oraz InsightFace/ArcFace, MagFace i facetorch. P1 ma jeden budżet eksperymentalny. Wybierz embedding tekstu przy przeoczonych parafrazach albo obrazu przy zmienionych kadrach. Włącz po wzroście recall na zbiorze rozwojowym przy tej samej lub mniejszej liczbie fałszywych par. Przy potrzebie rozpoznawania wizerunku sprawdź pochodzenie referencji i licencję wag oraz obsłuż wynik „nie rozpoznano”. Wspólna osoba pozostaje poszlaką. Scheduler wymaga powtarzalnego, dozwolonego źródła. Bazę grafową lub indeks kandydatów rozważ po pomiarze kosztu pełnego porównania. Integracja z DROZD jest kierunkiem dalszego rozwoju.

## Od pary do decyzji

1. Policz cechy referencyjne raz. Dla każdej pary zapisz dostępne rodziny (tekst, obraz, infrastruktura), pokrycie oraz trafienia z obu reklam. Możliwość porównania dwóch niezależnych rodzin wystarcza do oceny pokrycia nawet przy braku zgodności.
2. Mocna para wymaga zgodności przynajmniej dwóch niezależnych rodzin, w tym jednego specyficznego śladu (np. konkretny zapisany cel potwierdzony na zbiorze rozwojowym). Ustal listę takich śladów i progi na zbiorze rozwojowym. Pozostałe trafienia dają similar, brak trafień daje none. Ranking nadaje 2 punkty za obserwację specyficzną i 1 za pomocniczą. Dowody pochodne liczą się raz. Przy współdzielonym pochodzeniu wybierz najwyższą sumę dowodów rozłącznych po obu stronach. Wynik rankingu ustala kolejność, a o sile pary rozstrzyga osobna reguła.
3. Zacznij od pojedynczych rekordów. Rozpatruj mocne krawędzie malejąco według rankingu, remisy według uporządkowanych ID. Scalaj grupy tylko przy mocnej każdej parze między nimi. Mocne A–B i B–C przy słabym A–C tworzą jedną grupę dwóch rekordów i drugą sugestię. Taka heurystyka może rozdzielić prawdziwą kampanię z brakami danych. Zapisuj niescalone krawędzie do wglądu.
4. Porównaj upload z każdym członkiem zapisanego korpusu. Grupa referencyjna ma minimum dwie reklamy. Pierwsza pasująca reguła poniżej ustala status. Wyświetl pełne grupy przed częściowymi, w obrębie kategorii sortuj po najwyższej ocenie pary i ID grupy.

| Status | Warunek |
| --- | --- |
| probable_match | Dokładnie jedna grupa ma mocne połączenie z zapytaniem dla każdego członka, także gdy są inne częściowe sugestie. |
| review_needed | Kilka grup spełnia warunek albo występuje choć jedna częściowa sugestia lub podobna pojedyncza reklama. |
| insufficient_evidence | Brak sugestii i brak pary z wystarczającym pokryciem. |
| no_match | Brak sugestii przy co najmniej jednej parze z wystarczającym pokryciem. |

MatchResult przechowuje identyfikatory zapytania, korpusu i konfiguracji, status, reason_codes, kandydatów wraz z parami oraz similar_ads. Panel dowodu wskazuje rodzinę, siłę, oba ad_id, pola, wartości, obserwacje i opcjonalnie metrykę. Profil odlicza różne reklamy wspierające dany ślad.

## Plan, pomiar i odbiór

| Czas od startu | Rezultat możliwy do sprawdzenia |
| --- | --- |
| 0–1 h | Osoba od danych potwierdza źródło i pola, osoba od ewaluacji weryfikuje kryteria i odkłada przypadki. Zespół uzgadnia identyfikatory obserwacji. |
| 1–4 h | Import, ekstraktory, silnik i UI spotykają się na jednym rekordzie. Z formularza do pola źródłowego prowadzi pierwszy rzeczywiście obliczony dowód. |
| 4–10 h | Cały przepływ P0. Zespół próbuje pozytywu, kontrprzykładu, łańcucha A–B–C i czterech statusów. |
| 10–17 h | Strojenie i ewentualnie jeden eksperyment. Zamrożenie konfiguracji, słownika, korpusu referencyjnego i wersji zależności. |
| 17–24 h | Pomiar końcowy, czyste uruchomienie według README, powtórzenie offline, niezależny przegląd i poprawki. |

Tester zapisuje etykiety przypisane przez analityków wraz z podstawą decyzji, oddzielnie od wejścia silnika. Dzieli przypadki przed strojeniem, trzyma duplikaty jednej kreacji w jednej części, a wariant zapytania poza korpusem i jego statystykami. Dla wariantu tekstowego i pełnego używa tego samego podziału i tej samej reguły grupowania. Osobny próg tekstowy ustala na części rozwojowej. Na zamrożonym teście liczy TP, FP, FN dla par po grupowaniu, precision = TP/(TP+FP) oraz recall = TP/(TP+FN). Podaje liczebność, pochodzenie i liczbę niepewnych etykiet pominiętych w ocenie. Przy zerowym mianowniku raportuje „brak podstaw do obliczenia”. Oddzielnie podaje trafne, błędne i wstrzymane przypisania nowych reklam. Przy tak małym zbiorze publikujemy również surowe liczby.

Testy blokujące pokaz obejmują błędny format lub nadmiar bajtów/pikseli, brak OCR lub pusty słownik, brakujące metadane, ponowny import, obraz i tekst przepisany ze zrzutu, wspólną twarz lub gad_source, słabe A–C, dwie pełne grupy i pełną grupę z częściową sugestią. Sprawdź, czy przejście do poprzedniego wyniku nie miesza dowodów. Brak OCR wyłącza tę metodę, kolejny poprawny upload działa. Analiza używa wyłącznie danych lokalnych, podejrzane adresy są tekstem. Do README demonstratora wpisz rzeczywiście sprawdzone polecenia uruchomienia i testów.

Dwuminutowy pitch: przez 20 s pokaż źródło i dodaj odłożoną kreację. Do 1:10 pokaż grupę i dwa konkretne ślady. Do 1:40 pokaż podobną reklamę z uzasadnionym wstrzymaniem decyzji. W pozostałym czasie podaj wielkość próby oraz liczby z porównania z samym tekstem. Dzisiaj wynik empiryczny pozostaje do zmierzenia.

## Źródła

- [Oficjalny wykaz zadań i dokumenty konkursowe](https://hacknation.pl/zadania)
- [Przykład i wskazówki techniczne NASK](https://science.nask.pl/hacknation/)
- [NASK o celu zadania i DROZD](https://www.nask.pl/aktualnosci/polska-rzuca-wyzwanie-hakerom-nask-na-hacknation)
- [Przewodnik uczestnika](https://hacknation.pl/przewodnik-uczestnika)
- [Google o Ads Transparency Center](https://support.google.com/adspolicy/answer/13733850?hl=pl)
- [Dokumentacja ImageHash](https://github.com/JohannesBuchner/imagehash), [Tesseract](https://tesseract-ocr.github.io/tessdoc/Data-Files.html), [scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html)

Materiały zespołu w repozytorium obejmują README.md, docs/MVP.md, docs/DATA_CONTRACT.md, docs/NASK_DATA.md, docs/NASK_ZADANIE.md, docs/NASK_REGULAMIN.md oraz AGENTS.md.
