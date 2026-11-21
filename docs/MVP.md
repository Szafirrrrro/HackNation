# Plan MVP ScamGraph

## Cel na 24 godziny

Z jednej podejrzanej reklamy przejść do grupy powiązanych materiałów i pokazać, które ślady uzasadniają wspólną analizę. Na demo kluczowe są jakość podobieństwa, odporność na błędne połączenia i odtwarzalny dostęp do materiału.

## Podstawa zakresu

| Materiał NASK | Decyzja dla MVP |
| --- | --- |
| Pełna treść zadania, s. 1–2. Pozyskanie materiałów z bibliotek reklam i grupowanie na podstawie cech wizualnych, semantycznych oraz innych dostępnych śladów. | Jedna ścieżka pozyskania, trzy rodziny sygnałów tam, gdzie są dostępne, oraz test porównujący grupowanie z metodą tekstową. |
| Pełna treść zadania, s. 2. Prosty demonstrator oceniany 0/1. Forma wejścia, metoda podobieństwa i reprezentacja powiązań pozostają elastyczne. | Streamlit, jeden formularz dodania obrazu i lista grup z panelem dowodów. Wykres powiązań tylko wtedy, gdy pomaga czytać wynik. |
| Pełna treść zadania, s. 2. Wątek rozpoznawania osób z sugestią małej bazy referencyjnej. Scheduler to dodatkowy atut. | Identyfikacja osób i scheduler w P1. Jeśli mentor potwierdzi, że identyfikacja jest wymagana, pierwsza wersja obejmie małą, udokumentowaną bazę referencyjną i wynik „nie rozpoznano”. |
| Przykład organizatora „FakeCollector PRO™”. Deduplikacja, tekst, twarze, infrastruktura i wyjaśnienie krawędzi. Strona wskazuje film i plik `scam_links.enc`. | Wykorzystać odszyfrowany katalog do testu parametrów URL. Z pomysłów na stronie do P0 wybrać deduplikację i wyjaśnienie powiązań. |
| Regulamin, §2 i §4. Odrębnie publikowane kryteria oraz zasady dotyczące praw do wkładu. | Na starcie potwierdzić na platformie, czy opublikowano osobną punktację. W manifeście korpusu i dokumentacji zgłoszenia zachować pochodzenie materiałów, zależności i licencje. |

Strona przykładowa jest parodią i źródłem wskazówek. Podane na niej biblioteki są inspiracjami. Z ZIP-a powstał [lokalny korpus 13 reklam](../data/nask-hacknation-2026/), a `scam_links.enc` dostarczył trzy adresy do testów analizy URL. [Pochodzenie i weryfikacja danych](NASK_DATA.md) · [Przykład NASK](https://science.nask.pl/hacknation)

## P0 — przepływ od materiału do uzasadnienia

### 1. Korpus i odtwarzalne pozyskanie

- **Pierwsza integracja** korzysta z przygotowanego [korpusu NASK i opisu pól](DATA_CONTRACT.md#lokalny-korpus-nask). Osoba od danych wybiera z niego próbki do porównań. Katalog trzech URL-i służy jako osobny przypadek analizy parametrów.
- **Niezależna ścieżka** to ręczne wyszukanie po nazwie reklamodawcy lub witryny w publicznej bibliotece, a następnie zapis metadanych i dozwolonych kopii lokalnych. Pierwszy kandydat to Google Ads Transparency Center z filtrem regionu i czasu. Do próbki zapisz zapytanie, filtry, datę, identyfikator lub URL wpisu oraz dostępne pola. Sprawdź dostępność faktycznych przykładów i warunki użycia przed wyborem źródła. [Dokumentacja Google](https://support.google.com/adspolicy/answer/13733850?co=GENIE.CountryCode%3DPL&hl=en).
- Do pierwszej integracji wystarczy około 6–10 rekordów. W pierwszej godzinie wybierz też kandydatów na przypadek pozytywny i kontrprzykład. Sprawdź, czy odłożony zrzut i reklamy w grupie mają po dwie niezależne obserwacje potrzebne do dopasowania. Jeśli sam zrzut daje tylko jedną obserwację, dołącz zapisany adres lub tekst z osobnego pola źródłowego. Utrwal korpus demonstracyjny lokalnie. Gdy materiału brakuje, testuj przepływ na osobnym, jawnie syntetycznym zestawie. Materiał bez wiarygodnych etykiet może posłużyć do analizy jakościowej, a wyniki liczbowe zawsze opisuj wraz z pochodzeniem próbki.
- Importuje się JSONL z lokalnymi obrazami i manifestem źródła według [kontraktu danych](DATA_CONTRACT.md). Platformowy identyfikator reklamy służy do wykrywania ponownego importu. Przy jego braku stosujemy dokładny odcisk dostępnego rekordu. Podobny pHash jest przesłanką podobieństwa kreacji, a osobne emisje zachowują własne ID i źródło.

### 2. Sygnały, reguły i grupowanie

| Rodzina | Pierwszy wariant | Co pokazujemy analitykowi |
| --- | --- | --- |
| Tekst | Tekst źródłowy i lokalny OCR, jeśli jest dostępny. Znakowy TF-IDF (`char_wb`, n-gramy 3–5) do porównania, wspólny dokładny fragment do uzasadnienia. | Dopasowany cytat i jego pole źródłowe. Frazy częste w korpusie wspierają wyszukiwanie, a rzadkie fragmenty można dopuścić jako ślad specyficzny po sprawdzeniu zbioru rozwojowego. |
| Obraz | Pillow i pHash z odległością Hamminga. Zwykły SHA-256 pomaga rozpoznać identyczny plik. | Dwie kreacje obok siebie i odległość pHash. Identyczny plik potwierdza ponowne użycie zasobu. |
| Infrastruktura | Parsowanie zapisanych URL-i i metadanych. Porównanie pełnego adresu docelowego, charakterystycznej ścieżki lub identyfikatora z udokumentowanym znaczeniem i zakresem. | Oba pola w oryginalnej postaci, wartość porównana i źródło. Popularna domena, typowa ścieżka, `utm_source` i ogólny identyfikator reklamodawcy mają niewielką wagę. Zapisane przekierowania wykorzystujemy, jeśli zostały dostarczone. |

Lokalny OCR jest użyciem modelu w przepływie podstawowym. Jeśli OCR jest niedostępny, aplikacja pokaże aktywne metody i pozwoli podać tekst ręcznie. Embeddingi tekstu lub obrazu sprawdzamy jako osobny eksperyment. Progi, normalizacja, pochodzenie dowodów, grupowanie i decyzja o przypisaniu są jawne i wersjonowane. [TF-IDF](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html), [ImageHash](https://github.com/JohannesBuchner/imagehash).

1. **Ocena par.** Wylicz cechy każdej reklamy raz i porównaj pary w małym korpusie. Zapisz dostępność pól i listę dowodów. Mocna krawędź wymaga zgodności co najmniej dwóch rodzin opartych na różnych obserwacjach, w tym jednego śladu uznanego za specyficzny w konfiguracji. Cechy z tej samej obserwacji liczą się raz, np. obraz i OCR tego samego obrazu albo tekst z OCR przepisany do opisu. Punktacja do sortowania sumuje po 2 punkty za specyficzną i po 1 za pomocniczą obserwację, licząc tylko najsilniejszy sygnał z każdej obserwacji. Jeśli wykryto przesłanki bez spełnienia reguły mocnej krawędzi, para ma status `similar`. Sam temat, wizerunek lub domena mogą wskazać podobieństwo. Progi ustalamy na zbiorze rozwojowym i zamrażamy przed oceną.
2. **Grupowanie.** Sortuj mocne krawędzie według oceny, a remisy według ID. Scal dwie grupy tylko wtedy, gdy każda para między nimi spełnia regułę mocnej krawędzi. Przy `A–B` i `B–C` bez mocnego `A–C` pozostaw jedno wiarygodne połączenie w grupie, a drugie jako powiązanie do weryfikacji. To konserwatywny wariant na mały korpus. Ceną są mniejsze grupy przy niepełnych metadanych.
3. **Nowa reklama.** Porównaj ją z rekordami referencyjnymi bez zmiany korpusu. Pokaż prawdopodobne dopasowanie, jeśli spełnia regułę mocnej krawędzi względem wszystkich członków dokładnie jednej grupy. Jeśli kilka grup spełnia regułę lub znaleziono jedynie częściową zgodność lub podobieństwo, pokaż sugestie bez przypisania. Pojedyncza reklama spoza grupy może być wynikiem porównania, z własnymi dowodami. Status dla materiału bez kandydatów ustal według [kontraktu danych](DATA_CONTRACT.md).
4. **Profil grupy.** Zbierz wspólne ślady wraz z liczbą różnych reklam, w których występują, i pokaż rekordy źródłowe. To minimalne Campaign DNA. Profil można obliczyć z grupy w trakcie analizy.

### 3. Demonstrator i uruchomienie

- Jedna aplikacja Python + Streamlit. Rdzeń ma zwykłe funkcje niezależne od interfejsu. Moduły odpowiadają za `ingest`, `features`, `matching` i `evaluation`. Korpus ładuje się z plików, a cechy korpusu można zachować w pamięci między analizami.
- Jeden formularz przyjmuje bieżący obraz PNG/JPEG oraz opcjonalny tekst i znany adres docelowy. Rozmiar i format obrazu są walidowane przed odczytem. Pole URL traktujemy jako metadane. W trakcie dema analiza niczego z niego nie pobiera.
- Wynik pokazuje status, kandydatów i powody decyzji. Widok grupy zawiera listę reklam, a panel dowodów pokazuje oba rekordy, wartości i ich źródła. Podejrzane adresy pokazujemy jako tekst.
- Przy integracji zapisz wersje zależności, komendę startową i sposób uruchomienia testów w README. Przed finałem uruchom całość w czystym środowisku, a demo powtórz na lokalnym korpusie przy odłączonej sieci. [Dokumentacja Streamlit](https://docs.streamlit.io/develop/api-reference/widgets/st.file_uploader).

## P1 — pierwszeństwo według danych

1. **Jedna poprawka jakości wynikająca z pomiaru.** Sprawdź wielojęzyczne embeddingi tekstu przy parafrazach albo embeddingi wizualne przy zmianie kreacji. Włącz metodę, jeśli zwiększa wykrywalność powiązań względem wariantu podstawowego na zestawie rozwojowym bez zwiększania liczby błędnych scaleń. Przed końcowym testem zamroź wybrany wariant i jego progi. Podsumowania LLM pozostają poza ścieżką oceny powiązań.
2. **Wizerunek jako jeden ze śladów.** Gdy próbka zawiera wystarczająco dużo takich przypadków, sprawdź małą bazę referencyjną z odpowiednim pochodzeniem zdjęć. Przypisanie wizerunku ma obsługiwać niską jakość i niepewność. Wspólny wizerunek pozostaje sygnałem pomocniczym do porównania kampanii.
3. **Więcej danych lub wygody.** Jeśli potwierdzony kanał danych pozwala na automatyzację, można dodać zaplanowany import. Alternatywy przy gotowym P0 to prosta wizualizacja grafu lub eksport JSON dowodów. Integracja z DROZD jest kierunkiem po hackathonie. [Komunikat NASK](https://www.nask.pl/aktualnosci/polska-rzuca-wyzwanie-hakerom-nask-na-hacknation).

## Kryteria odbioru i pomiar

- [ ] Zapisano skąd pochodzi korpus i da się odtworzyć jego import. Interfejs rozróżnia materiały pozyskane, dostarczone przez NASK i syntetyczne.
- [ ] Dodanie odłożonej reklamy wywołuje rzeczywistą analizę i pokazuje właściwą grupę z dowodami. Panel wskazuje konkretne pola dla każdej wyświetlonej przesłanki.
- [ ] Przypadki z samą wspólną twarzą, tematem lub generycznym adresem pozostają bez przypisania. Test `A–B–C` ma mocne `A–B` i `B–C` oraz słabe lub niedostępne `A–C`. Wynik nie zawiera grupy wszystkich trzech reklam. Rekord bez metadanych, błędny obraz i brak OCR mają czytelne wyniki lub komunikaty.
- [ ] Przed strojeniem oddzielono zestaw rozwojowy od zestawu do końcowej oceny. Progi i wybór sygnałów ustala się na zestawie rozwojowym, a raportowany pomiar uruchamia dopiero po zamrożeniu konfiguracji. Etykiety pochodzą z udokumentowanej oceny, a przypadki nierozstrzygnięte pozostają osobno. Duplikaty tej samej kreacji trafiają do jednej części podziału. Przy symulacji nowej reklamy wariant testowy pozostaje poza korpusem referencyjnym i sam nie wpływa na statystyki tego korpusu.
- [ ] Raport podaje wielkość i źródło próbki oraz precision i recall par w klastrach, liczbę par z różnych kampanii błędnie zgrupowanych, a osobno trafne i błędne przypisania oraz wstrzymane decyzje dla nowych reklam. Porównanie z samym TF-IDF używa tego samego podziału i tej samej reguły grupowania, z progiem krawędzi dopasowanym osobno na zbiorze rozwojowym. Przy małej próbce pokaż też liczby bezwzględne.
- [ ] Demonstrator startuje według README i przechodzi próbę offline. Niezależny agent sprawdza finalny przepływ, dowody i scenariusz. Zespół usuwa blokery przed zgłoszeniem gotowości zgodnie z [AGENTS.md](../AGENTS.md).

## Harmonogram i właściciele

| Czas | Rezultat do sprawdzenia |
| --- | --- |
| 0–1 h | Sprawdzone materiały i kryteria. Wybór źródła lub jawnego wariantu zastępczego. Kilka rekordów i uzgodniony kontrakt. |
| 1–4 h | Pierwszy przepływ z aplikacji do silnika i z powrotem. Użytkownik dodaje obraz i widzi rzeczywiście obliczoną przesłankę. |
| 4–10 h | P0 na lokalnym korpusie. Porównywanie par, grupowanie, statusy nowej reklamy i panel dowodów. |
| 10–17 h | Strojenie na zestawie rozwojowym. Ewentualny eksperyment P1 ma własnego właściciela. Po zamrożeniu konfiguracji końcowy pomiar na odłożonych przypadkach i porównanie z tekstem. |
| 17–24 h | Zamrożenie zbioru demo, próba offline, niezależny przegląd i poprawki. Gotowy opis zgłoszenia, instrukcja uruchomienia i przećwiczone demo. |

Sześciu właścicieli odpowiada kolejno za **źródła i import**, **OCR i obraz**, **tekst i metadane URL**, **silnik i integrację**, **Streamlit** oraz **ewaluację i demo**. Po uzgodnieniu kontraktu agenci pracują równolegle nad przypisanymi modułami, testami i niezależnymi kontrprzykładami. Po każdym wierszu harmonogramu planujemy przegląd rezultatu przez agenta spoza implementacji tego etapu.

## Scenariusz demo

1. **0:00–0:20** — pokaż źródło zbioru i dodaj odłożony zrzut reklamy.
2. **0:20–1:10** — otwórz proponowaną grupę i wskaż dwie rzeczywiste przesłanki na dwóch reklamach. Przykładowa para przesłanek, jeśli istnieje w danych, to rzadka fraza i ten sam zapisany adres docelowy mimo różnych linków wejściowych.
3. **1:10–1:40** — dodaj reklamę o podobnej narracji lub z tym samym wizerunkiem. Pokaż uzasadniony brak automatycznego przypisania.
4. **1:40–2:00** — podaj zmierzony wynik względem wariantu tekstowego i wielkość próbki. Dwie minuty to cel dla przygotowanego dema zgodny z zaleceniem przewodnika uczestnika. [Przewodnik HackNation](https://hacknation.pl/przewodnik-uczestnika).
