# Benchmark warstwy modeli

Stan na 2026-11-22. Dokument opisuje, jak porównaliśmy modele laboratorium na próbie 492 reklam, co wyszło i jakie decyzje z tego wynikają. Progi, reguły i wybór modeli to decyzje zespołu, nie wymagania NASK. Na każdy parametr zostaje jeden model (decyzja z 2026-11-22). Statusy `stage` w kodzie ekstraktorów nie zostały jeszcze zmienione. [Laboratorium](../README.md) · [Kontrakt cech](../../docs/DATA_CONTRACT.md)

## Pytanie

Laboratorium ma 22 ekstraktory, a część statusów (`default`, `candidate`, `deferred`) ustalono na 13 zrzutach albo na oko. Benchmark odpowiada na jedno pytanie dla każdej rodziny modeli: który model zostaje.

**W każdej rodzinie zostaje dokładnie jeden model**, z wyjątkiem pochodzenia obrazu, gdzie drugi model ocenia obrazy nieoznaczone przez pierwszy. Pierwotny plan dopuszczał drugi model, jeśli wnosi coś ponad pierwszy; zrezygnowaliśmy z tego po przebiegu, żeby każdy parametr miał jedno źródło. Obraz ma dwa parametry: skrót percepcyjny (ten sam plik) i podobieństwo. Benchmark jest rankingiem wewnątrz rodziny, a nie bramką, przez którą rodzina może nie przejść.

Dwie rzeczy trzeba od siebie oddzielić. „Najlepszy w rodzinie” nie znaczy „wchodzi do `PROFILE=default`” ani „bierze udział w grupowaniu”. O grupowaniu decyduje status: ekstraktor z `excluded` jest z niego wyłączony, a rodziny tematu, obiektów i twarzy pozostają poza profilem domyślnym niezależnie od tego, który model w nich wygrał.

„Rodzina” w tym dokumencie to grupa modeli rozwiązujących to samo zadanie (np. OCR). To nie to samo co pole `family` w kontrakcie cech (`text`, `visual`, `infrastructure`, `audio`).

Benchmark nie mierzy trafności przypisania reklam do kampanii. Do tego potrzebne są niezależne etykiety i końcowa ewaluacja silnika, opisana w [planie MVP](../../docs/MVP.md). Próba jest zbiorem rozwojowym: służy do porównania modeli między sobą, nie do podawania trafności systemu.

## Próba

492 reklamy zebrane z publicznego źródła. Każda ma zrzut karty reklamy (ok. 420 px szerokości, 418–731 px wysokości), tekst i nazwę nadawcy; 393 mają domenę docelową. Materiał leży w `models/data/`, poza Gitem, podobnie jak cechy i raporty w `models/out/`.

| Co | Liczba |
| --- | --- |
| Reklamy w próbie | 492 |
| Odrzucone: powtórzone ID emisji | 413 |
| Odrzucone: wycofana kreacja | 45 |
| Odrzucone: brak zrzutu albo nieczytelny pakiet | 2 |
| Unikalne teksty (co najmniej 24 znaki) | 362 |
| Nadawcy / z co najmniej dwiema reklamami | 241 / 81 (332 reklamy) |
| Domeny docelowe / z co najmniej dwiema reklamami | 173 / 66 (287 reklam) |
| Reklamy z co najmniej jedną reklamą powiązaną śladem zewnętrznym | 348 |
| Podzbiór dla drogich modeli (losowy, ziarno 20261122) | 60 |

Cztery właściwości próby wpływają na odczyt wyników:

- **Zrzut to cała karta, nie sama kreacja.** Obraz zawiera ramkę platformy, nazwę nadawcy i często podpis z domeną. Tekst karty bywa uzupełniony o domenę i napisy odtwarzacza.
- **Brak nagrań.** Część reklam to wideo, ale próba zawiera tylko zrzuty. Rodzin mowy i audio nie dało się na niej zmierzyć.
- **Duplikaty.** Identyczne pliki (to samo SHA-256) łączymy przed pomiarem. Zostają kreacje zapisane ponownie z inną kompresją; w miarach obrazu wyłączamy z puli negatywów oryginały odległe o najwyżej 4 bity pHash (dotyczy 54 zapytań).
- **Powiązania.** 348 z 492 reklam ma w próbie partnera o tym samym nadawcy lub domenie, więc jest co odzyskiwać.

## Miary

Próba nie ma etykiet kampanii, więc jakość mierzymy zamiennikami. Żaden sam nie wystarcza; każdy ma inne słabe miejsce.

| Miara | Definicja | Słabe miejsce |
| --- | --- | --- |
| **Pokrycie** | Odsetek reklam z niepustym wynikiem: co najmniej jedna twarz, co najmniej 20 znaków tekstu, co najmniej jedno wykrycie. Sam status `ok` nie wystarcza, bo pusty wynik też go dostaje. | Nie mówi nic o poprawności wyniku. |
| **Odzyskiwanie wariantów** | Z każdego obrazu podzbioru robimy trzy warianty: kadr, róg i pomniejszenie z rekompresją. Model szuka oryginału w galerii wszystkich 492 reklam. Podajemy hit@1 i hit@3, remisy na niekorzyść modelu. | Warianty to te same piksele po przekształceniu. Kreacja wyrenderowana na nowo przez nadawcę jest trudniejsza. |
| **Zgodność ze śladem zewnętrznym** | Reklamy tego samego nadawcy lub z tą samą domeną docelową traktujemy jako przypuszczalnie powiązane. Podajemy, jak często model umieszcza taką reklamę w top-3, oraz AUC rozdzielenia par powiązanych od pozostałych. | Jeden nadawca prowadzi różne kampanie. Ślad nie jest też niezależny od treści: nazwa nadawcy jest widoczna na zrzucie (patrz Ograniczenia). |
| **Zysk ponad bazę** | Pary, które model umieszcza w top-3, a metoda bazowa rodziny nie. Podajemy, ile z nich ma ślad zewnętrzny, i losujemy 30 na model do oceny ręcznej. | Miara pomocnicza: ocena ręczna się nie odbyła i nie jest potrzebna do decyzji. |
| **Odczyt znanych napisów** (OCR) | Odsetek słów tekstu karty odnalezionych w wyniku OCR oraz to, czy OCR odczytał nazwę nadawcy i domenę. | To nie CER: nie każde słowo tekstu karty jest widoczne na zrzucie. |
| **Zgodność z frazą** (temat) | Reklamy znalezione frazą o jednoznacznym temacie mają oczekiwaną kategorię. Podajemy, jak często model ją wskazuje. Mapowanie fraz na kategorie leży przy korpusie, poza repozytorium. | Słaba etykieta: fraza opisuje wyszukiwanie, nie treść konkretnej reklamy. Frazy wieloznaczne pomijamy, a oczekiwane kategorie w tej próbie są tylko dwie. |

Koszt mierzy `bench.sh`: p50 i p95 inferencji, czas ładowania i szczyt pamięci, przy tych samych limitach dla wszystkich modeli. Koszt jest ograniczeniem, nie kryterium rankingu. **Budżet:** p95 do 5 s na jedno wejście dla pojedynczego modelu, przy 4 rdzeniach i 4 wątkach. To cel projektowy laboratorium dla całej ścieżki obrazu przeniesiony na pojedynczy model, więc jest warunkiem koniecznym, nie wystarczającym.

## Reguła wyboru

1. **Miara rozstrzygająca** jest przypisana rodzinie przed odczytem wyników (tabela w sekcji Decyzje). Gdy rodzina ma dwie, pierwszeństwo ma ta, która nie zależy od śladu zewnętrznego.
2. **Najlepszy model** to ten z najlepszym wynikiem miary rozstrzygającej wśród mieszczących się w budżecie. Gdy żaden się nie mieści, rodzina zostaje poza profilem domyślnym, a ranking podajemy informacyjnie.
3. **Remis** ogłaszamy, gdy różnica jest mniejsza niż 2 pkt proc. albo dotyczy mniej niż 5 zapytań. Rozstrzyga wtedy niższy p95, a przy zbliżonym koszcie licencja pozwalająca na szersze użycie. Dla miar innych niż hit@3 stosujemy ten sam próg do odsetka.
4. **Jeden model na parametr.** Modele, które przegrały, nie zostają jako kandydaci. To, w czym były lepsze, zapisujemy w tabeli decyzji jako znaną stratę.
5. **Gdy baza przegrywa**, traci miejsce podstawowego modelu jak każdy inny. Zmiana statusu `default` wymaga jednak uzgodnienia z odbiorcą cech, bo zmienia wejście silnika grupowania.
6. Rywali porównujemy zawsze na tych samych zapytaniach i tej samej galerii.

Próg remisu w punkcie 3 przyjęliśmy przed przebiegiem i zatwierdziliśmy bez zmian po nim. Punkt 4 zastąpił po przebiegu wcześniejszą regułę o drugim modelu. Dwa dalsze doprecyzowania powstały po obejrzeniu wyników i trzeba je czytać z tą świadomością: pierwszeństwo miary niezależnej od śladu zewnętrznego (punkt 1) oraz kolejność miar w rodzinie OCR, gdzie dwie miary wskazały różne modele.

Reguła nie rozstrzyga wszystkiego. Tam, gdzie decyzja od niej odbiega albo brakuje miary, tabela decyzji mówi to wprost.

## Przebieg

Narzędzia są w tym katalogu i działają z katalogu `models/`:

| Plik | Rola |
| --- | --- |
| `make_corpus.py` | Buduje z zebranych pakietów korpus v0, metadane śladu zewnętrznego i losowy podzbiór. |
| `run.sh` | Uruchamia kroki `smoke`, `full`, `subset`, `variants`, `cost`, `metrics`. |
| `metrics.py` | Czyta trzy zbiory cech przez `FeatureStore` i zapisuje `results.json` oraz pary do oceny ręcznej. |

```bash
cd models
benchmark/run.sh ./data/<próba>                    # wszystkie kroki
STEPS="metrics" benchmark/run.sh ./data/<próba>    # wybrane kroki
OCR_VARIANT_ADS=15 MAX_ITEMS=5 STEPS="variants cost" benchmark/run.sh ./data/<próba>
RESUME=1 benchmark/run.sh ./data/<próba>           # po przerwaniu: pomija modele z aktualnym wynikiem
```

Krok `smoke` przepuszcza dwie reklamy przez wszystkie modele (ok. 80 s) i zatrzymuje benchmark, gdy któryś model nie zwraca wyniku. Kroki uruchamiamy kolejno i bez innych zadań na maszynie: równoległe obciążenie wydłużało modele tekstu 3–7 razy.

Co faktycznie policzono:

| Krok | Zakres | Czas |
| --- | --- | --- |
| Pilotaż | 49 reklam, 12 w podzbiorze; sprawdzenie, że całość przechodzi | — |
| `full` | Twarze, obraz, Tesseract, E5-small i BGE-M3 na 492 reklamach | 59 min |
| `subset` | Wszystkie modele na 60 reklamach | ok. 45 min, w dwóch podejściach |
| `variants` | Modele obrazu i Tesseract na 240 obrazach; EasyOCR na wariantach 15 reklam | ok. 10 min |
| `cost` | 5 wejść na model, 4 rdzenie, 4 wątki, 6 GB, jedno powtórzenie | 3 min |
| `metrics` | Całość | 1 min |

Odstępstwa od planu, o których trzeba wiedzieć przy czytaniu liczb:

- **Podzbiór 60 zamiast 100 reklam**, bo detektory obiektów liczą obraz ok. 8–10 s.
- **Przebieg został przerwany i dokończony w okrojonej formie.** EasyOCR policzył warianty 15 reklam zamiast 60 (45 zapytań), a koszt mierzono na 5 wejściach zamiast 20. Miara odzyskiwania dla obu OCR jest liczona na tych samych 45 zapytaniach.
- **Czasy kroków `full` i `subset` są zawyżone** przez inne zadania działające równolegle. Koszt modeli podajemy wyłącznie z kroku `cost`, który liczył się sam.
- **Błąd wykryty przez pilotaż:** ekstraktor Effort nie zwracał wyniku dla żadnego obrazu (rzutowanie dwóch logitów na jedną liczbę). Poprawka jest w `containers/aigi_effort/models.py`; po niej Effort ocenia 60 z 60 obrazów.
- **Usprawnienia dodane po przebiegu.** Krok `smoke`, wznawianie (`RESUME=1`), liczenie identycznych tekstów raz, pomijanie tekstu z OCR w modelach tekstu (`DERIVED_TEXT=0`; miary czytają tylko pole `text`) i liczenie samych wariantów bez oryginałów nie powinny zmieniać wyników. Pomiarem potwierdziliśmy to dla tekstu: E5-small policzony ponownie na 492 tekstach dał wektory identyczne z wcześniejszymi (130 tekstów wziętych z pamięci). Dla wariantów bez oryginałów wynika to z kodu miar, który ze zbioru wariantów czyta tylko warianty. Kroki `full`, `subset` i `variants` w nowej postaci nie były uruchomione w całości. Tabele poniżej pochodzą z przebiegu sprzed tych zmian.
- **Ocena ręczna się nie odbyła.** 175 par czeka w `out/benchmark-quality/<próba>/pairs.jsonl`; klucz wiążący parę z modelem jest w osobnym pliku, żeby oceniający go nie widział.

Środowisko: Apple M3, Docker z 8 rdzeniami i 7,65 GB pamięci, obrazy `tm-*` zbudowane z rewizji `1fd8c8a` ze zmianami roboczymi. Odciski korpusów: cała próba `56c2daa346fdc817`, podzbiór `b00a5eed3017fd5d`, warianty `e5be09fe2e1ed312`. Rewizje wag i identyfikatory obrazów są w `out/features/<próba>/runs/*.json`.

## Wyniki

Do repozytorium trafiają wyłącznie liczby zbiorcze, bez tekstów, identyfikatorów i obrazów reklam. Przy każdej liczbie podany jest mianownik.

### Obraz

Warianty: 180 zapytań (60 obrazów × 3), galeria 492. Ślad zewnętrzny: 150 wylosowanych zapytań, galeria 492.

| Model | Warianty hit@1 | Warianty hit@3 | Róg | Kadr | Pomniejszenie | Ślad hit@3 | Ślad AUC | p95 | Szczyt pamięci |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ORB | 98,3% | 100% | 60/60 | 60/60 | 60/60 | 82,0% | 0,884 | 8 ms | 391 MB |
| CLIP ViT-B/32 | 70,0% | 81,1% | 37/60 | 49/60 | 60/60 | 88,7% | 0,943 | 63 ms | 604 MB |
| DINOv2-small | 56,7% | 62,2% | 13/60 | 40/60 | 59/60 | 65,3% | 0,711 | 59 ms | 529 MB |
| pHash | 33,3% | 35,0% | 0/60 | 3/60 | 60/60 | 48,0% | 0,723 | 5 ms | 405 MB |
| dHash | 31,7% | 33,9% | 0/60 | 4/60 | 57/60 | 48,0% | 0,780 | 5 ms | 405 MB |

Zysk ponad pHash (pary w top-3 modelu, których pHash nie ma w top-3):

| Model | Dodatkowe pary | Z nich ze śladem zewnętrznym |
| --- | --- | --- |
| CLIP ViT-B/32 | 340 | 199 (58,5%) |
| ORB | 348 | 173 (49,7%) |
| DINOv2-small | 355 | 102 (28,7%) |
| dHash | 343 | 62 (18,1%) |

Liczba dodatkowych par dla dHash jest w dużej części szumem: przy remisach odległości top-3 pHash zależy od kolejności reklam.

Skróty percepcyjne znajdują pomniejszoną kopię, ale nie kadr ani róg, czyli działają zgodnie z przeznaczeniem: ten sam plik po rekompresji. DINOv2-small, dziś model domyślny, przegrywa z ORB i CLIP w obu miarach. ORB odzyskuje wszystkie warianty, co jest częściowo wpisane w metodę: dopasowuje lokalne punkty, a wariant to te same piksele. CLIP jest najlepszy tam, gdzie reklamy łączy nadawca, a nie identyczny obraz.

### Tekst

219 zapytań wśród 362 unikalnych tekstów kart; identyczne teksty liczone jako jedna pozycja.

| Model | hit@1 | hit@3 | AUC | Dodatkowe pary ponad TF-IDF | Z nich ze śladem | p95 | Szczyt pamięci |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BGE-M3 | 87,7% | 92,2% | 0,939 | 251 | 91 (36,3%) | 759 ms | 974 MB |
| TF-IDF `char_wb` 3–5 | 87,7% | 90,9% | 0,875 | baza | — | nie mierzono | — |
| E5-small | 85,4% | 90,0% | 0,926 | 239 | 67 (28,0%) | 43 ms | 782 MB |

Różnice hit@3 to 3 zapytania (BGE-M3 wobec TF-IDF) i 2 zapytania (TF-IDF wobec E5-small), czyli remis z bazą. BGE-M3 wobec E5-small to 5 zapytań i 2,3 pkt proc., czyli już nie remis. Modele embeddingów mają wyższe AUC, więc lepiej porządkują pary w całym zakresie wyników, ale w top-3 nie widać z tego korzyści.

### OCR

Podzbiór 60 reklam; warianty 15 reklam (45 zapytań, po 15 na rodzaj). Te 15 reklam to pierwsze według identyfikatora, nie losowe. Galerią odzyskiwania jest 60 oryginałów podzbioru, a nie cała próba jak dla obrazu. Domeny liczone są jako wystąpienia: 53 w 52 reklamach.

| Miara | Tesseract `pol+eng` | EasyOCR `pl/en` |
| --- | --- | --- |
| Niepusty wynik | 60/60 | 60/60 |
| Odnalezione słowa tekstu karty (średnio) | 61,1% | 44,9% |
| Odczytana nazwa nadawcy | 55/60 | 42/60 |
| Odczytana domena docelowa | 4/53 | 3/53 |
| Warianty hit@3: kadr / róg | 15/15, 15/15 | 15/15, 15/15 |
| Warianty hit@3: pomniejszenie | 0/15 | 7/15 |
| Warianty hit@3 łącznie | 30/45 (66,7%) | 37/45 (82,2%) |
| p95 | 0,27 s | 2,4 s |
| Szczyt pamięci | 233 MB | 684 MB |

Miary wskazują różne modele. Tesseract czyta więcej tekstu z obrazu w oryginalnym rozmiarze i jest dziewięć razy szybszy. EasyOCR radzi sobie lepiej z obrazem pomniejszonym, na którym Tesseract nie odzyskał żadnego z 15 oryginałów (na wszystkich 60 reklamach: 2). Oba OCR prawie nie czytają domeny docelowej.

### Twarze

Cała próba, 492 reklamy. Ślad zewnętrzny liczony tylko dla reklam z twarzą, więc zapytania nie są te same dla obu modeli.

| Model | Reklamy z twarzą | Ślad hit@3 | Ślad AUC | p95 | Szczyt pamięci | Licencja wag |
| --- | --- | --- | --- | --- | --- | --- |
| InsightFace buffalo_l | 206 (41,9%) | 112/147 (76,2%) | 0,759 | 141 ms | 1358 MB | niekomercyjna |
| YuNet + SFace | 147 (29,9%) | 76/99 (76,8%) | 0,750 | 13 ms | 665 MB | MIT, Apache-2.0 |

Wyniki śladu zewnętrznego są zbliżone, ale liczone na różnych zapytaniach, więc nie rozstrzygają. InsightFace znajduje twarz w 59 reklamach więcej; nie sprawdziliśmy, ile z nich to prawdziwe twarze.

### Temat

Podzbiór, 60 tekstów kart; 53 mają oczekiwaną kategorię z frazy.

| Model | Zgodność z frazą | Wynik najlepszej kategorii poniżej 0,5 | Najczęstsza etykieta | p95 |
| --- | --- | --- | --- | --- |
| mDeBERTa-v3 XNLI | 21/53 (39,6%) | 25/60 | zakupy i promocje (29) | 2,7 s |
| MiniLMv2-L6 XNLI | 7/53 (13,2%) | 43/60 | randki i związki (35) | 0,16 s |

Oczekiwane kategorie są tylko dwie i modele zachowują się w nich odwrotnie:

| Oczekiwana kategoria | mDeBERTa-v3 | MiniLMv2-L6 |
| --- | --- | --- |
| zdrowie, leki i suplementy | 21/38 | 3/38 |
| inwestycje i kryptowaluty | 0/15 | 4/15 |

Modele zgadzają się ze sobą w 7 z 60 tekstów. MiniLMv2 przypisuje ponad połowę reklam do kategorii „randki i związki”, co nie odpowiada składowi próby. Przewaga mDeBERTa pochodzi w całości z kategorii zdrowia; kategorii inwestycji nie wskazał ani razu.

### Obiekty

Podzbiór, 60 obrazów. Poprawności wykryć nie ocenialiśmy.

| Model | Obrazy z wykryciem | Średnio wykryć | Najczęstsze etykiety | p95 | Szczyt pamięci |
| --- | --- | --- | --- | --- | --- |
| Grounding DINO tiny | 60/60 | 4,35 | karta kredytowa 48, osoba 44, logo 42 | 8,2 s | 2561 MB |
| OWLv2 base | 55/60 | 2,48 | logo 34, osoba 32, wykres 26 | 10,1 s | 2277 MB |

Zgodność zestawów etykiet między modelami jest niska (średni Jaccard 0,29). Karta kredytowa w 48 z 60 reklam u Grounding DINO wygląda na fałszywe alarmy. Oba modele przekraczają budżet 5 s. Dekoder QR nie znalazł kodu w żadnym z 60 obrazów, podczas gdy OWLv2 zgłasza kod QR w 14.

### Pochodzenie obrazu

Podzbiór, 60 zrzutów. Nie wiemy, które kreacje faktycznie powstały z użyciem AI.

| Model | Oznaczone jako AI | p95 | Szczyt pamięci |
| --- | --- | --- | --- |
| Klasyfikator SigLIP | 60/60 | 0,23 s | 841 MB |
| reverse-SynthID v4 | 9/60 | 0,13 s | 1688 MB |
| Effort CLIP-L/14 | 0/60 | 1,0 s | 3410 MB |

SigLIP oznacza każdy zrzut karty, więc na tym materiale nic nie rozróżnia. To samo można powiedzieć o Effort, który nie oznacza żadnego: wynik zero może oznaczać brak fałszywych alarmów albo brak czułości. Odrzucenie SigLIP opiera się na założeniu, że nie wszystkie 60 kreacji powstało z użyciem AI; bez zbioru obrazów o znanym pochodzeniu nie da się rozstrzygnąć nic więcej.

### Mowa i audio

Nie zmierzono: próba nie zawiera nagrań. Statusy zostają bez zmian.

## Decyzje

Decyzje zespołu z 2026-11-22: jeden model na parametr. Statusy w kodzie pozostają na razie takie jak przed benchmarkiem.

| Parametr | Miara rozstrzygająca | Zostaje | Odpada | Podstawa i znana strata |
| --- | --- | --- | --- | --- |
| Obraz, ten sam plik | brak rywala | pHash i dHash | — | Odzyskują pomniejszoną kopię (60/60 i 57/60), zgodnie z przeznaczeniem. Jeden ekstraktor liczy oba skróty. |
| Obraz, podobieństwo | Odzyskiwanie wariantów, potem ślad zewnętrzny | CLIP ViT-B/32 | ORB, DINOv2-small | Odstępstwo od reguły, opisane niżej. ORB wygrywa warianty (100% wobec 81,1%), CLIP ślad zewnętrzny (88,7% wobec 82,0%). DINOv2-small przegrywa z oboma w obu miarach. Strata: 34 z 180 wariantów, których CLIP nie ma w top-3, głównie róg (23) i kadr (11). |
| Tekst | Ślad zewnętrzny | TF-IDF | BGE-M3, E5-small | Remis w hit@3 z oboma modelami. Reguła każe wtedy wybrać niższy p95; kosztu TF-IDF nie mierzyliśmy, przyjmujemy, że metoda bez modelu jest tańsza. Strata: lepsze porządkowanie par poza top-3 (AUC 0,939 i 0,926 wobec 0,875). |
| OCR | Odczyt znanych napisów, potem odzyskiwanie wariantów | Tesseract | EasyOCR | Tesseract czyta więcej (61% wobec 45% słów, 55 wobec 42 nazw nadawców) przy dziewięciokrotnie niższym koszcie. Strata: odczyt z pomniejszonych obrazów (0/15 wobec 7/15). |
| Twarze | Pokrycie, potem ślad zewnętrzny | YuNet + SFace | InsightFace buffalo_l | Odstępstwo od reguły: w pokryciu wygrywa InsightFace (206 wobec 147 reklam), ale jego wagi mają licencję niekomercyjną, a poprawność 59 dodatkowych twarzy nie jest sprawdzona. YuNet + SFace ma swobodną licencję i jest dziesięć razy szybszy. |
| Temat | Zgodność z frazą | mDeBERTa-v3 | MiniLMv2-L6 | 39,6% wobec 13,2%, przy słabej etykiecie i tylko dwóch kategoriach. Rodzina zostaje poza profilem domyślnym: lepszy model nie wskazał kategorii inwestycji w żadnym z 15 przypadków. |
| Obiekty | Ocena ręczna (brak) | OWLv2 base, tymczasowo | Grounding DINO tiny | Oba przekraczają budżet, więc ranking jest informacyjny, a rodzina zostaje poza profilem domyślnym. Bez miary poprawności kolejność opiera się na obserwacji: Grounding DINO zgłasza kartę kredytową w 48 z 60 reklam, OWLv2 kod QR w 14, w których dekoder nie znalazł żadnego. Grounding DINO jest szybszy (8,2 s wobec 10,1 s). |
| Pochodzenie obrazu | Fałszywe alarmy i wykrywalność (brak zbioru odniesienia) | reverse-SynthID, potem Effort | SigLIP | Wyjątek od zasady jednego modelu (decyzja z 2026-11-22). SynthID sprawdza obraz pierwszy; obrazy, których nie oznaczył, ocenia Effort. Benchmark tej kolejności nie uzasadnia ani nie podważa: bez obrazów o znanym pochodzeniu żadnego z modeli nie da się ocenić. SigLIP oznacza 60/60, przy założeniu opisanym w wynikach. Rodzina zostaje wyłączona z grupowania. |
| Mowa, audio | — | bez zmian | — | Brak nagrań w próbie. |

### Podobieństwo obrazu: dlaczego CLIP, a nie ORB

Reguła wskazuje ORB, bo wygrywa miarę rozstrzygającą. Wybieramy CLIP z trzech powodów:

- **Podział ról.** Obraz ma dwa parametry. Skróty percepcyjne i ORB rozpoznają to samo: te same piksele po przekształceniu. CLIP uzupełnia skróty, zamiast je powtarzać, i najlepiej łączy reklamy jednego nadawcy o różnych obrazach.
- **Wynik ORB jest częściowo wpisany w metodę.** Wariant syntetyczny to te same piksele po kadrowaniu i rekompresji, a ORB dopasowuje właśnie lokalne punkty. Kreacji wyrenderowanej na nowo nie testowaliśmy.
- **Jeden wektor.** CLIP daje embedding, który silnik może przeszukiwać. ORB porównuje deskryptory parami, co nie skaluje się z galerią.

Słabe miejsce tej decyzji: przewaga CLIP w śladzie zewnętrznym może częściowo wynikać z nazwy nadawcy widocznej na zrzucie. Rozstrzygnęłaby to ocena ręczna 60 wylosowanych par (po 30 dla CLIP i ORB).

### Pochodzenie obrazu: dwa modele po kolei

To jedyny parametr z dwoma modelami. reverse-SynthID szuka znaku wodnego, który mają tylko obrazy z części generatorów, więc brak oznaczenia nic nie mówi o pozostałych. Obrazy nieoznaczone ocenia Effort, a wynik zapisuje, który model oznaczył obraz. Kaskadę uruchamia `provenance.sh <katalog z obrazami>`; podkatalogi `ai/` i `real/` służą jako etykiety i dają liczbę wykrytych obrazów oraz fałszywych alarmów. Skrypt nie był jeszcze uruchomiony w całości.

Do zrobienia zostają trzy rzeczy:

- **Wagi Effort.** Checkpointu nie ma w repozytorium ani w obrazie kontenera; trzeba go udostępnić zespołowi przez Git LFS albo Google Drive i opisać pobranie w [laboratorium](../README.md).
- **Zbiór kontrolny.** Kilkadziesiąt własnych obrazów o znanym pochodzeniu, także jako zrzuty kart. Bez niego nie wiemy, czy 9 oznaczeń SynthID na 60 zrzutach to prawdziwe znaki wodne ani czy Effort (0 z 60) widzi cokolwiek na tym materiale.
- **Próg Effort.** Skrypt przyjmuje `fake_prob` co najmniej 0,5 (`EFFORT_THRESHOLD`); próg trzeba ustalić na zbiorze kontrolnym.

### Co zmienia się względem stanu obecnego

1. **Podobieństwo obrazu:** CLIP zastępuje DINOv2-small jako model domyślny. To zmiana wejścia silnika grupowania (inny model, wymiar 512 zamiast 384), więc przed zmianą statusu w kodzie wymaga uzgodnienia z Parą C. ORB traci status kandydata.
2. **Tekst:** E5-small traci status kandydata; tekst porównuje TF-IDF.
3. **Twarze:** jeśli rodzina wejdzie do użycia, modelem jest YuNet + SFace.
4. **Temat:** jeśli rodzina wejdzie do użycia, modelem jest mDeBERTa-v3.

## Ocena ręczna

Dwie osoby oceniają te same pary niezależnie. Pary wszystkich modeli z jednej rodziny są wymieszane, a oceniający nie widzi, który model wskazał parę. Możliwe odpowiedzi: powiązane, niepowiązane, nie da się ustalić. Do każdej odpowiedzi „powiązane” oceniający dopisuje podstawę (ta sama kreacja, ten sam tekst, ta sama osoba i produkt).

Pary, w których oceny się różnią, trafiają do puli nieustalonej. Nie liczymy ich na korzyść modelu i podajemy ich liczbę w wynikach.

Ocena ręczna nie jest już warunkiem żadnej decyzji, bo drugich modeli nie zostawiamy. Opis zostaje jako procedura na wypadek sporu, przede wszystkim CLIP wobec ORB. Wylosowanych jest 175 par: po 30 wylosowanych na każdy z sześciu modeli obrazu i tekstu ponad bazę rodziny, po złączeniu par wskazanych przez więcej niż jeden model.

## Ograniczenia

- **Ślad zewnętrzny nie jest niezależny od treści.** Nazwa nadawcy i często domena są widoczne na zrzucie i w tekście karty. Model, który „czyta” nazwę z obrazu, dostaje punkty za ślad zewnętrzny bez rozpoznania kreacji. Dotyczy to zwłaszcza CLIP i modeli tekstu. Dlatego dla obrazu pierwszeństwo ma odzyskiwanie wariantów.
- **Ramka platformy jest wspólna dla wszystkich zrzutów.** Nie zmierzyliśmy osobno, jak wysoko modele oceniają pary niepowiązanych reklam o tej samej ramce.
- **Warianty syntetyczne faworyzują metody odporne na kadrowanie i kompresję.** Nie sprawdzają odporności na zmianę układu, kolorów czy napisów w kreacji. Wynik ORB (100%) trzeba czytać z tym zastrzeżeniem.
- **Mały podzbiór.** Drogie modele mają wyniki z 60 reklam, a EasyOCR na wariantach z 15. Różnica 7 zapytań na 45 wskazuje kierunek, nie wielkość efektu.
- **Brak transkrypcji i nagrań.** Nie policzyliśmy CER ani WER. Wybór OCR opiera się na miarach pośrednich, a mowa i audio nie były mierzone.
- **Brak oceny ręcznej.** Wybór CLIP zamiast ORB nie jest nią potwierdzony, a poprawność etykiet tematu, wykryć obiektów i dodatkowych twarzy nie została sprawdzona.
- **Koszt z 5 wejść.** p95 z pięciu pomiarów jest w praktyce wartością najwyższą z pięciu. TF-IDF nie ma pomiaru kosztu, bo nie jest ekstraktorem kontenerowym.
- **Koszt pojedynczego modelu nie jest czasem całej ścieżki** od przyjęcia reklamy do wyniku. Ten mierzymy osobno, po ustaleniu profilu.
