# ScamGraph — plan implementacji

W ciągu 24 godzin zespół ma dostarczyć lokalny demonstrator, w którym analityk dodaje reklamę i sprawdza, czy jest wariantem znanej kampanii. Wynik prowadzi do pól obu porównywanych reklam. Repozytorium zawiera dziś lokalny korpus, kontrakt i statyczne przykłady reguł. Silnik Pythona, demonstrator Streamlit i końcowy pomiar są pracą do wykonania.

## Kryteria jury i dowody na pokaz

Wagi pochodzą z punktu 9 pełnego opisu wyzwania. Testy odbiorowe w prawej kolumnie są propozycją zespołu.

| Kryterium jury | Waga | Co oddajemy i jak to sprawdzamy |
| --- | --- | --- |
| Jakość metody korelacji i grupowania materiałów | 30% | C1 pokazuje wariant znanej grupy, odrębną kampanię i niejednoznaczny przypadek. Raport porównuje model pełny z samym tekstem na identycznym podziale. |
| Użyteczność i trafność pozyskiwanych cech oraz źródeł danych | 30% | Pary A i B dostarczają obraz, tekst i dostępne ślady infrastruktury z pochodzeniem i miarą. Na odłożonych przypadkach pokazują, które rodziny pomagają oraz kiedy generują fałszywe połączenia. |
| Kompletność demonstratora i działanie procesu end-to-end | 15% | C2 uruchamia interfejs na czystym środowisku, importuje dane, dodaje wcześniej niewidziany plik i prezentuje rzeczywiście obliczone grupy. Powtarza próbę z brakującymi polami. |
| Czytelność i interpretowalność prezentowanych powiązań | 15% | Przy parze widać oba rekordy, wartości i źródła, przy grupie wspólne ślady i liczbę wspierających emisji. Kontrprzykład wyjaśnia wstrzymanie decyzji. |
| Potencjał wdrożeniowy, skalowalność i przenośność rozwiązania | 10% | Instrukcja instalacji, konfiguracji i uruchomienia, wersje zależności, licencje, pomiar czasu budowy indeksu i analizy nowej reklamy z podaną liczebnością oraz sprzętem. Planujemy preferowany przez NASK kontener z lokalnymi modelami OCR. |

Opis formalny wymaga GUI, metodyki, instrukcji i dostępnego organizatorowi kodu. Opis techniczny pozostawia wybór technologii zespołowi. Dopisek o obecności GUI 0/1 w załączonej zajawce dotyczy samego środowiska graficznego. Pełny proces end-to-end stanowi 15% oceny.

## Zespoły i granice modułów

Założenie organizacyjne to sześć osób w trzech parach. Oznaczenia identyfikują role do obsadzenia.

| Para | Zadania dwóch osób | Co przekazuje pozostałym | Test własny |
| --- | --- | --- | --- |
| **A · obraz i OCR** | **A1** waliduje bajty i wymiary PNG/JPEG, liczy SHA-256 i pHash całej kreacji oraz sprawdza wpływ kadru. **A2** uruchamia Tesseract z lokalnymi językami polskim i angielskim, zapisuje tekst i pochodzenie. | Cechy wizualne dla C1, tekst OCR z identyfikatorem źródłowego obrazu dla B2. Stos: Pillow, ImageHash, Tesseract i pytesseract. | Ten sam plik w dwóch emisjach zachowuje oba ID. Zmieniona kompresja, uszkodzony obraz i brak modelu OCR dają opisane wyniki. |
| **B · tekst, dane i infrastruktura** | **B1** importuje manifest/JSONL, sprawdza źródła, deduplikuje ponowny import i parsuje zapisane obserwacje URL/HTML/HAR. **B2** buduje tekstowy punkt odniesienia, porównuje tekst źródłowy i OCR, zwraca wspólny fragment. | Rekordy `Ad` dla A i C, cechy tekstowe i infrastrukturalne z oryginalnym polem dla C1. Stos: Python, JSONL, urllib.parse, scikit-learn. | Ponowny import zachowuje liczbę emisji. Popularny parametr i sam przepisany napis nie dają mocnego przypisania. Pusty tekst lub słownik nie zatrzymuje analizy. |
| **C · korelacja, GUI i ewaluacja** | **C1** implementuje ocenę par, grupowanie, porównanie nowego materiału i raport jakości. **C2** składa formularz i panel dowodów w Streamlit, odpowiada za instrukcję, kontener, licencje i próbę od zera. | Wersjonowane `PairAssessment`, `Campaign` i `MatchResult`, działający przepływ oraz raport. | Cztery statusy, dwie konkurujące grupy, test łańcucha i próba offline. |

A2 i B2 są opiekunami odłożonego testu. Oznaczają przypadki niezależnie, następnie uzgadniają sporne etykiety. B1 dokumentuje pozyskanie i źródła, A1 dostarcza duplikaty i warianty. Do strojenia C1 otrzymuje wyłącznie część rozwojową. Na każdym punkcie integracji druga para sprawdza rzeczywisty wynik właściciela.

## Przepływ i kontrakty

| Warstwa | Wejście | Wyjście | Jak sprawdzić granicę |
| --- | --- | --- | --- |
| Import · B1 | Lokalny katalog korpusu lub materiał z formularza, opcjonalny opis i znany adres celu | `Ad` ze stabilnym ID, źródłem i stanem dostępnych pól | Obsłuż nowy identyfikator i inny rozkład plików przez adapter. Przy brakującym zasobie zachowaj użyteczne pola. |
| Ekstrakcja · A + B | `Ad`, obraz i źródło pola, oddzielne obserwacje stron | `Feature` z `ad_id, family, field, value, origin_id, method_version` | Tekst z OCR, ręczna transkrypcja i wycinek tego samego obrazu dziedziczą jego `origin_id`. B2 korzysta z tekstu źródłowego również przy wyłączonym OCR. |
| Korelacja i grupowanie · C1 | Cechy oraz zamrożone progi | `Evidence → PairAssessment → Campaign` | Każdy dowód wskazuje pola po obu stronach. Brak porównywalnego pola odróżniamy od zmierzonej niezgodności. |
| Zapytanie i prezentacja · C1 + C2 | Nowa reklama, indeks korpusu, konfiguracja | `MatchResult` i panel w Streamlit | Upload porównujemy z każdym członkiem grupy. Zapytanie nie zmienia grup, statystyk tekstu ani wyników poprzedniej analizy. |

Jeden proces Pythona ładuje katalog wskazany przez użytkownika. Ekstraktory działają jako zwykłe funkcje, więc CLI testów i Streamlit mogą wywoływać te same obliczenia. Cechy referencyjne liczymy raz. Klucz pamięci podręcznej obejmuje odcisk korpusu, konfigurację i wersje metod. Przy 13 rekordach pełne porównanie daje 78 par, a dla nowej reklamy potrzeba 13 porównań. Większy zbiór uzasadni indeks kandydatów, gdy zmierzony czas przestanie spełniać wymagania demonstracji.

## Dane i jakość śladów

W repozytorium zespół ma 13 różnych zrzutów, 15 obserwacji stron i trzy adresy do testu parsera. Każdy z 13 rekordów ma tekst przepisany z obrazu. Liczba potwierdzonych adresów docelowych w rekordach wynosi zero. Pakiet startowy i materiały z kanału organizatora służą realizacji wyzwania. Zachowujemy je w dostępie ograniczonym do zespołu i oceniających. Publiczny pakiet strony korzysta z syntetycznych przykładów. Do publicznego udostępnienia kodu przygotujemy osobny pakiet bez materiałów NASK, również w historii Git. Zewnętrzne źródła wymagają odnotowania pochodzenia i warunków korzystania.

B1 sprawdza trzy ID Biblioteki reklam Meta z lokalnego korpusu. Jeśli rekord biblioteki dostarcza osobne, możliwe do zweryfikowania pole celu, zapisuje ID emisji, adres wpisu, pole i czas odczytu. Inny udokumentowany kanał to eksport lub dozwolony ręczny zapis z biblioteki reklam wraz z filtrem, datą i identyfikatorem. Strona zapisana obok zrzutu pozostaje osobną obserwacją do czasu potwierdzenia związku z emisją. W przypadku niedostępnej strony zachowujemy dane z istniejącego zapisu, czas i status dostępności. Pierwsza integracja korzysta z zapisanych danych lokalnych.

- **Obraz.** SHA-256 wykrywa ponowne użycie identycznego zasobu. pHash i odległość Hamminga wskazują podobieństwo wizualne. W odtwarzalnej próbie na dwóch pełnych zrzutach ImageHash 4.3.2 i Pillow 11.3.0 dały 16/64 bitów różnicy. Próg 6/64 z syntetycznego przykładu jest demonstracyjny. A1 testuje kadr i pełny zrzut na części rozwojowej.
- **Tekst.** TF-IDF `char_wb` 3–5 i podobieństwo cosinusowe porządkują pary. Cytat pokazany jako dowód musi występować w obu polach. Tekst przepisany ze zrzutu ma to samo źródło co obraz. Słownik i częstości dopasowujemy do zbioru referencyjnego.
- **Infrastruktura.** B1 normalizuje zapisane hosty i porty domyślne, zachowując znaczenie ścieżki i parametrów. Obserwowane przekierowanie lub charakterystyczny identyfikator wymaga udokumentowanego związku z daną reklamą i zakresu jego użycia. Wspólny popularny parametr jest wskazówką do przeglądu.

## Reguła pary, grupy i nowego materiału

1. **Para.** Zapisz porównywalne rodziny, trafienia i braki. Dwa zgodne ślady z różnych rodzin i niezależnych obserwacji po obu stronach, w tym przynajmniej jeden specyficzny, dają `strong`. Pozostałe podobieństwa dają `similar`, a brak trafień `none`. Do sortowania licz po 2 punkty za specyficzną i po 1 za pomocniczą obserwację. Współdzielone źródło policz raz.
2. **Grupa.** Rozpatruj mocne krawędzie malejąco według punktów, przy remisie według uporządkowanych ID. Scalaj tylko wtedy, gdy każda para między grupami jest mocna. Przy mocnych A–B i B–C oraz słabym A–C pozostaw grupę dwóch reklam i dodatkową relację do przeglądu. Grupa ma co najmniej dwie emisje. Jej profil podaje ślady, liczbę wspierających emisji i ich ID. Podobieństwa między odrębnymi grupami można pokazać przez wspólne cechy ich profili i wskazanie par, które je uzasadniają.
3. **Zapytanie.** Dokładnie jedna grupa z mocnym powiązaniem wobec każdego członka daje `probable_match`. Kilka pełnych grup, częściowe podobieństwo lub pojedyncza podobna emisja prowadzą do `review_needed`, o ile nie ma dokładnie jednej pełnej grupy. Bez kandydatów i bez wystarczającego pokrycia wynikiem jest `insufficient_evidence`. Bez kandydatów, przy co najmniej jednej parze z wystarczającym pokryciem, `no_match` wskazuje **możliwy nowy wzorzec do sprawdzenia**. Utworzenie nowej kampanii wymaga dalszych powiązanych emisji.
4. **Wyjaśnienie.** Dla każdej pary UI pokazuje ID emisji, obie wartości, pola, pierwotne obserwacje, metodę, metrykę i przyczynę decyzji. Panel grupy pokazuje również częściowe sugestie i brakujące rodziny. Braki nie dodają punktów za podobieństwo.

## Integracja w 24 godziny

| Czas | Punkt integracji i warunek odbioru |
| --- | --- |
| 0–1 h | A2 i B2 wydzielają przypadki finałowe, w tym wariant znanej kampanii i materiał z innej kampanii. Przechowują je wraz z etykietami poza zbiorem roboczym. C1 dostaje część rozwojową. Zespół uzgadnia `Ad`, `Feature` i `origin_id`. |
| 1–4 h | B1 przekazuje jeden poprawny rekord i jeden z brakami. A oddaje cechy obrazu, B cechy tekstu, C pokazuje w GUI pierwszy **obliczony** dowód z obu reklam. |
| 4–10 h | C1 zwraca grupy i cztery statusy. A2 weryfikuje podwójne liczenie OCR, B2 sprawdza wariant tekstowy i popularne parametry. C2 łączy niezmienne zapytanie z panelem dowodów. |
| 10–17 h | Testy na części rozwojowej, porównanie rodzin i próby błędnego scalenia. Najwyżej jeden eksperyment po działającym P0. Zamrażamy konfigurację, ekstraktory, korpus referencyjny i instrukcję środowiska. |
| 17–24 h | Po zamrożeniu obu wariantów A2 i B2 uruchamiają je na odłożonym zbiorze i przekazują C1 wyniki do raportu. C2 sprawdza nowy katalog z innymi ID, czas wykonania i instalację na czystym stanowisku. Przegląd, próba offline i pełny pokaz. |

## Walidacja i pakiet dla jury

Organizator przeprowadzi własne testy na dodatkowym, wcześniej nieudostępnionym zbiorze. Znajdą się w nim warianty znanych kampanii i materiały innych kampanii. Adapter wczytuje nowe ID i źródła. Progi, ścieżki i reguły nie mogą zależeć od nazw przykładów startowych.

- **Podział i etykiety.** Zanim zacznie się strojenie, A2 i B2 oddzielają rozwój od testu oraz zapisują uzasadnione etykiety poza danymi dostępnymi silnikowi. Identyczne pliki i niemal identyczne kopie tej samej emisji pozostają w jednej części. W teście nowego wariantu grupa referencyjna zawiera inne emisje znanej kampanii. W teście odrębnej kampanii wszystkie jej emisje pozostają poza referencją. Niepewne etykiety służą ocenie jakościowej.
- **Pomiary.** W wariancie tekstowym krawędź powstaje, gdy cosinus wektorów TF-IDF pary osiąga próg dobrany osobno na części rozwojowej. W wariancie pełnym krawędź powstaje zgodnie z regułą niezależnych rodzin. Oba warianty używają tego samego podziału danych i tej samej procedury scalania grup po wyznaczeniu krawędzi. Na odłożonym teście raportuj TP, FP i FN par po grupowaniu, precision, recall oraz liczebność i pochodzenie próby. Osobno podaj poprawne, błędne i wstrzymane przypisania zapytań znanych oraz nowych kampanii. Przy zerowym mianowniku oznacz wynik jako niemierzalny.
- **Próby odporności.** Sprawdź powtórny import, brak OCR, pusty tekst, nieczytelny lub za duży obraz, różne formaty wejścia, niedostępną stronę, generyczny parametr, wspólny wizerunek, dwie konkurujące grupy i słabe A–C. Dla każdego błędu UI wskazuje przyczynę i pozwala wykonać następną analizę.
- **Oddanie.** C2 przekazuje dostępny jury kod, metodykę z parametrami, raport z wzorcami i źródłami metadanych, instrukcję instalacji, konfiguracji, startu i testów oraz listę zależności, modeli, usług, licencji i ograniczeń. Wersję kontenerową sprawdza na nowej maszynie. Jeśli wybrana usługa wymaga autoryzacji, dokumentujemy sposób uzyskania dostępu i zapewniamy weryfikowalny przebieg oceny bez udostępniania prywatnych kluczy lub certyfikatów.
- **Pokaz.** Wczytaj zbiór, wyodrębnij cechy i pokaż wynik grupowania. Dodaj odłożoną reklamę, otwórz oba źródła dowodu, a następnie podaj materiał z innej kampanii lub z brakami. Zamknij pokaz liczebnością i rzeczywistym wynikiem względem metody tekstowej. Przykłady syntetyczne potwierdzają zachowanie reguł w izolacji. Ocena jakości na rzeczywistych kampaniach wymaga osobnych, wiarygodnych etykiet.

## Po działającym P0

Parafrazy mogą uzasadnić eksperyment z embeddingiem tekstowym, zmiana kadru eksperyment z embeddingiem obrazu. Do demonstratora włączamy metodę po poprawie recall na części rozwojowej bez wzrostu liczby fałszywych powiązań. Automatyczne wyszukiwanie w bibliotece reklam, cykliczny import i rozpoznawanie wizerunków są rozszerzeniami. Dla modeli i baz referencyjnych zespół sprawdza pochodzenie i licencje. Rozszerzenia nie opóźniają testu całego przepływu.

## Materiały dla programistów

W repozytorium zacznij od `README.md` i `docs/DATA_CONTRACT.md`. Transkrypcje otrzymanych PDF są w `docs/NASK_ZADANIE.md` oraz `docs/NASK_REGULAMIN.md`, a pochodzenie danych w `docs/NASK_DATA.md`. Katalog korpusu dla lokalnego demonstratora to `data/nask-hacknation-2026/`.

- [Materiały konkursowe HackNation](https://hacknation.pl/zadania) · [Techniczne inspiracje NASK](https://science.nask.pl/hacknation/)
- [ImageHash](https://github.com/JohannesBuchner/imagehash) · [Modele Tesseract](https://tesseract-ocr.github.io/tessdoc/Data-Files.html) · [TF-IDF w scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html)
