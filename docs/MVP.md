# Co oddajemy jury

Celem pierwszej wersji jest próba, którą juror może wykonać sam. Wczytuje zbiór referencyjny, dodaje wcześniej niewidzianą reklamę i sprawdza, czy sugerowana grupa wytrzymuje porównanie jej członków. Z wyniku przechodzi do pary źródeł i do chronologii kampanii. Przy braku rozstrzygających informacji widzi, jakich danych zabrakło. Wynik dla odłożonych scenariuszy syntetycznych i ograniczenia etykiet opisuje [pomiar](../graph/eval/README.md). Instalację i obsługę opisuje [README](../README.md).

## Kryteria NASK i sposób odbioru

| Kryterium jury | Waga | Co pokażemy i jak to sprawdzić |
| --- | --- | --- |
| Korelacja i grupowanie | 30% | Odłożony wariant znanej kampanii, przypadek obcy i konkurencyjne grupy. Podamy liczby poprawnych i błędnych połączeń po klastrowaniu oraz wstrzymane decyzje. Metodą odniesienia jest sam tekst. |
| Przydatność cech i źródeł | 30% | Dwa obrazy, wspólny fragment tekstu i udokumentowany ślad strony. Usunięcie wybranej rodziny cech pozwoli zobaczyć, który przypadek przestał być rozpoznawany lub które błędne połączenie zniknęło. |
| Kompletność demonstratora | 15% | Osoba spoza implementacji wczyta nowy zbiór, zbuduje grupy i doda własny plik w GUI. Powtórzy próbę z brakującym polem. |
| Czytelność i interpretowalność | 15% | Z grafu analityk otworzy obie strony dowodu i wyjaśni decyzję. Na osi wskaże czas wraz z jego znaczeniem i źródłem. |
| Potencjał wdrożeniowy, skala i przenośność | 10% | Uruchomienie z instrukcji na czystym stanowisku, lokalny kontener i eksport JSON z wersją metody. Podamy sprzęt, rozmiar indeksu, czas budowy i czas zapytania. |

Wagi określa pkt 9 zadania. GUI, metodyka, instrukcja i dostępny kod to wymagania formalne z pkt 4. Graf, oś czasu i *complete-link* są decyzjami zespołu. Preferowany przez NASK kontener umożliwi pokaz offline. Automatyczne przeszukiwanie bibliotek reklam pozostaje rozszerzeniem po odbiorze głównego przepływu. [Zadanie i warunki walidacji](NASK_ZADANIE.md)

## Trzy pary, jeden wynik

| Para | Co przygotowuje | Co odbiera kolejna para |
| --- | --- | --- |
| A · dane i źródła | Jedna osoba importuje emisje i usuwa powtórzenia importu. Druga opracowuje zapisy stron, dowody relacji emisja–strona i pochodzenie dat. | B i C dostają rekordy z oryginalnymi wartościami, wskazaniem źródeł oraz raportem braków. |
| B · ekstrakcja i pomiar | Jedna osoba porównuje obrazy i uruchamia OCR. Druga przygotowuje tekstowy punkt odniesienia, zestawia efekty dodawania cech i mierzy koszt. Jedna osoba z A i jedna z B niezależnie oznaczają przypadki, uzgadniają spory i odkładają test. | C dostaje cechy z pochodzeniem i metodą. Jury otrzymuje porównanie zamrożonych wariantów na tych samych zapytaniach. |
| C · korelacja i demonstrator | Jedna osoba oblicza pary, grupy i wynik nowej reklamy. Druga łączy GUI z silnikiem, eksportem oraz kontenerem i przygotowuje instalację. | A i B sprawdzają w interfejsie, czy wynik da się prześledzić od decyzji do pierwotnego pola. |

Decyzje o formacie, grupowaniu i statusach mają jedną definicję w [kontrakcie](DATA_CONTRACT.md). Punkty przekazania między modułami rozwija [instrukcja budowy](INSTRUKCJA_BUDOWY.md).

## Punkty integracji

Poniższe godziny to cele zespołu w czasie polskim. Oficjalny termin utworzenia zgłoszenia w HackTribe to **21 listopada 2026 o 20:00**, a końcowego złożenia **22 listopada o 11:00**. [Przewodnik uczestnika](https://hacknation.pl/przewodnik-uczestnika)

| Do kiedy | Warunek przejścia |
| --- | --- |
| 21 XI, 18:00 | Jeden import, jedna porównana para i dowód widoczny w GUI. Dodatkowy materiał dostaje osobny inwentarz i ocenę jakości etykiet. Brak dostępu do dodatkowej paczki pozwala kontynuować na korpusie z repozytorium. |
| 21 XI, 20:00 | Lider utworzył draft i wskazał odpowiednie zadanie. Zespół ma przypadki rozwojowe i odłożone oraz zapisane źródła etykiet. |
| 22 XI, 00:00 | Wersja klasyczna przelicza grupy, sprawdza nowe zgłoszenie i wyjaśnia wynik. Wybór ewentualnego eksperymentu GPU wynika z konkretnego przeoczenia na danych rozwojowych. |
| 22 XI, 07:00 | Konfiguracja, korpus referencyjny i modele są zamrożone. Zaczyna się jednokrotny pomiar końcowy. |
| 22 XI, 10:30 | Po niezależnym przeglądzie i próbie offline zespół składa kod, prezentację, raport, instrukcję i działające materiały dla jury. |

## Jak oceniamy trafność

Kopie oraz bliskie warianty tej samej emisji zostają po jednej stronie podziału. Dla zapytania o znaną kampanię referencja zawiera inne oznaczone emisje tej kampanii. Dla kampanii nowej wszystkie jej emisje pozostają poza referencją. W korpusie startowym brakuje potwierdzonych etykiet kampanii. Na tych danych mierzymy podobieństwo kreacji lub rozpoznanie udokumentowanego śladu. Przy braku wiarygodnych etykiet rzeczywistych kampanii pełne przypisanie demonstrujemy na podpisanej próbie kontrolowanej.

Na tym samym podziale porównujemy TF-IDF, pełną metodę klasyczną i ewentualny wariant z jednym embeddingiem. Raport podaje liczbę kampanii i zapytań, TP/FP/FN par po klastrowaniu, precyzję i czułość, trafienia w pierwszej trójce oraz poprawne, błędne i wstrzymane przypisania dla znanych i nowych kampanii. Pokazujemy liczniki i mianowniki. Przy braku mianownika wpisujemy „niemierzalne”. Koszt obejmuje czas budowy indeksu i p95 od wczytania obrazu do wyniku, z wydzielonym czasem OCR. [Laboratorium i warunek użycia modelu](../models/README.md)

## Scenariusz dwuminutowego pokazu

| Czas | Co robi analityk | Co ma zobaczyć jury |
| --- | --- | --- |
| 0:00–0:25 | Wczytuje prywatny korpus. Otwiera zapisy stron p1 i p7, następnie p15. | Wspólny tytuł i piksel na dwóch hostach oraz podobny tekst przy innym pikselu. Podstawą jest konkretny zapis strony. |
| 0:25–0:50 | Wybiera zbiór z udokumentowanymi kampaniami i wnosi odłożony wariant. Gdy używamy próby syntetycznej, etykieta zbioru jest stale widoczna. | Nowy post, obliczona decyzja, wyróżniona grupa na grafie. |
| 0:50–1:20 | Klika krawędź, porównuje źródła i wybiera zdarzenie na osi. | Widać, które dwie obserwacje uzasadniają powiązanie i z którego źródła pochodzi data. |
| 1:20–1:45 | Podaje reklamę obcej kampanii i przykład z brakami. | System rozróżnia możliwy nowy wzorzec od zbyt słabego pokrycia. |
| 1:45–2:00 | Otwiera tabelę z końcowej ewaluacji. | Liczebność próby, błędne przypisania, wstrzymania i zmiana wyniku po dodaniu cech. |

**Pakiet oceny** zawiera kod dostępny jurorom, instrukcję instalacji, konfiguracji, startu i testów, metodykę z progami, wykaz bibliotek, modeli, wcześniejszych zasobów, licencji i ograniczeń, eksport wzorców z dowodami oraz rzeczywiste wyniki pomiaru. Opiszemy sposób uzyskania dostępu do każdej użytej usługi wymagającej autoryzacji. Materiały NASK i wyniki pozwalające odtworzyć ich treść pozostają prywatne. Do pokazu publicznego używamy własnego materiału. [Zasady korzystania z danych i wymogi formalne](NASK_ZADANIE.md) · [Prawa autorskie, §4](NASK_REGULAMIN.md)
