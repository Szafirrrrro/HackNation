// IDs are stable anchors for links shared by team members.
export const modules = {
  corpus: {
    title: "Korpus reklam", type: "pliki wejściowe", owner: "B1", chapter: "import",
    action: "Manifest opisuje pochodzenie i wersję zbioru. Każdy wiersz ads.jsonl opisuje jedną emisję, a image_path prowadzi do jej pliku względem katalogu z manifestem.",
    input: "manifest.json, ads.jsonl i opcjonalny katalog media/",
    output: "Rekord źródłowy dla importera",
    failure: "Brak obrazu trafia do raportu importu. Jeżeli pozostało użyteczne pole, zachowaj emisję.",
    check: "Import tego samego katalogu po raz drugi zachowuje liczbę emisji."
  },
  captures: {
    title: "Obserwacje stron", type: "zapis offline", owner: "B1", chapter: "infrastruktura",
    action: "Zapis przeglądarki opisuje wizytę pod określonym adresem i o określonej godzinie. Jeden wpis o stronie może opisywać również błąd HTTP.",
    input: "Zapisane metadane HTML, HAR lub obserwacje stron",
    output: "Obserwacja strony z czasem i źródłem",
    failure: "Gdy strona jest niedostępna, zapisz stan i analizuj pozostałe pola.",
    check: "Dwa zapisy tego samego adresu z różnymi datami i odpowiedziami zachowują odrębną historię."
  },
  ingest: {
    title: "Import emisji", type: "Ad", owner: "B1", chapter: "import",
    action: "Adapter sprawdza pola i przypisuje stabilny identyfikator emisji. Grupuje ponowne importy według dostawcy i ID reklamy lub dokładnego odcisku rekordu.",
    input: "Wiersz JSONL, dane źródłowe, lokalne media",
    output: "Ad z ID, pochodzeniem i użytecznymi polami",
    failure: "Raport wskazuje błędny rekord i przyczynę. Poprawne rekordy pozostają dostępne.",
    check: "Dwie emisje tego samego obrazu z różnymi ID u dostawcy pozostają dwoma rekordami."
  },
  linkage: {
    title: "Związek z emisją", type: "pochodzenie celu", owner: "B1", chapter: "infrastruktura",
    action: "Dopiero udokumentowana relacja pozwala użyć adresu zapisanej strony jako celu konkretnej reklamy. Sąsiedztwo plików pozwala odszukać materiał do sprawdzenia.",
    input: "Obserwacja strony i informacja o powiązaniu z emisją",
    output: "Potwierdzony ślad infrastruktury albo osobna obserwacja",
    failure: "Przy niejasnym powiązaniu zostaw landing_url puste.",
    check: "Sama wspólna nazwa katalogu nie przenosi adresu do rekordu reklamy."
  },
  pixels: {
    title: "Obraz i OCR", type: "Pillow · Tesseract", owner: "A1 + A2", chapter: "obraz",
    action: "A1 sprawdza format i wymiary obrazu, a następnie liczy dokładny odcisk pliku i pHash. A2 odczytuje napis z pikseli. Obie metody zapisują pochodzenie.",
    input: "Zwalidowane bajty PNG/JPEG oraz ad_id",
    output: "Odciski i odczyt OCR połączone z obrazem przez origin_id",
    failure: "Brak modelu językowego wyłącza OCR. Wynik wskazuje dostępne metody.",
    check: "OCR i pHash tego samego obrazu nie dają dwóch niezależnych przesłanek."
  },
  wording: {
    title: "Tekst źródłowy", type: "pole tekstowe", owner: "B2", chapter: "tekst",
    action: "Zachowaj oddzielnie opis z biblioteki, tekst przepisany ze zrzutu i wynik OCR. Zanotuj, skąd pochodzi każdy z nich.",
    input: "Tekst reklamy i informacja o jego pierwotnym źródle",
    output: "Tekst ze wskazaniem pola i origin_id",
    failure: "Puste pole pomiń. Nieznane pochodzenie ogranicza możliwość uznania dowodu za niezależny.",
    check: "Zdanie przepisane ze zrzutu dziedziczy origin_id obrazu również po ręcznym wklejeniu."
  },
  urls: {
    title: "Adresy i metadane", type: "urllib.parse", owner: "B1", chapter: "infrastruktura",
    action: "Rozłóż znany adres na host, ścieżkę i parametry. Zachowaj oryginał do wyświetlenia. Porównuj wartości pochodzące z udokumentowanego zapisu.",
    input: "Cel reklamy lub potwierdzona obserwacja, opcjonalne zapisane przekierowania",
    output: "Porównywalne składniki adresu wraz z wartością źródłową",
    failure: "Przy braku potwierdzonego celu ta rodzina może pozostać niedostępna.",
    check: "Wspólny popularny parametr sam nie wystarcza do przypisania kampanii."
  },
  visualfeatures: {
    title: "Cechy wizualne", type: "Feature · visual", owner: "A1", chapter: "obraz",
    action: "SHA-256 wskazuje identyczne bajty, a różnica bitów pHash opisuje podobieństwo wyglądu. Wersja metody obejmuje sposób przygotowania obrazu.",
    input: "Odciski kreacji lub jej udokumentowanego kadru",
    output: "Feature z wartością odcisku, polem, origin_id i method_version",
    failure: "Zmiana kadru potrafi zwiększyć odległość. Zachowaj wariant i pełny oryginał do porównania.",
    check: "Ta sama wersja ekstraktora daje ten sam odcisk przy kolejnym uruchomieniu."
  },
  textfeatures: {
    title: "Cechy tekstowe", type: "Feature · text", owner: "B2", chapter: "tekst",
    action: "Dopasuj znakowy TF-IDF do tekstów korpusu. Dla pary policz cosinus, a jako uzasadnienie zwróć dokładny wspólny fragment z obu źródeł.",
    input: "Tekst źródłowy i dostępny OCR, oba z pochodzeniem",
    output: "Cechy tekstowe i słownik referencyjny do późniejszych zapytań",
    failure: "Pusty słownik oznacza brak dostępnej metody tekstowej dla tego przebiegu.",
    check: "Dodanie zapytania nie zmienia słownika ani wag dokumentów w indeksie."
  },
  infrafeatures: {
    title: "Cechy infrastruktury", type: "Feature · infrastructure", owner: "B1", chapter: "infrastruktura",
    action: "Przypisz porównywanej wartości zakres i pochodzenie. Specyficzny cel może wzmocnić obraz, jeżeli zapisano go niezależnie po obu stronach pary.",
    input: "Znormalizowane składniki celu i oryginalne pola",
    output: "Feature z wartością, rodziną, polem i źródłem",
    failure: "Wspólny tracker albo ogólny host pozostaje wskazówką do przeglądu.",
    check: "Ten sam identyfikator w dwóch miejscach jednego zapisu jest jedną obserwacją."
  },
  pairs: {
    title: "Dowody dla par", type: "PairAssessment", owner: "C1", chapter: "para",
    action: "Porównaj każdą nieuporządkowaną parę reklam. Zachowaj pola obu stron, metryki, braki i identyfikatory obserwacji. Sprawdź niezależność po lewej i po prawej.",
    input: "Cechy dwóch emisji i wersjonowane progi",
    output: "Evidence[] i PairAssessment z tier, rank_score i pokryciem",
    failure: "Brakująca cecha obniża pokrycie. Zmierzona różnica jest osobnym wynikiem.",
    check: "Mocna para wymaga zgodnych śladów z dwóch niezależnych rodzin, w tym jednego specyficznego."
  },
  groups: {
    title: "Budowa grup", type: "Campaign[]", owner: "C1", chapter: "grupy",
    action: "Uporządkuj mocne krawędzie według wyniku i stabilnych ID. Połącz dwie grupy dopiero po sprawdzeniu każdej pary między nimi. Policz wspólne ślady grupy.",
    input: "Tabela ocen par korpusu",
    output: "Grupy co najmniej dwóch emisji, profile i odnośniki do par",
    failure: "Mocne A–B i B–C przy słabym A–C pozostawiają dwie emisje w grupie i relację do sprawdzenia.",
    check: "Odwrócenie kolejności importu zachowuje wynik dzięki deterministycznym remisom."
  },
  index: {
    title: "Indeks referencyjny", type: "stan do odczytu", owner: "C1", chapter: "indeks",
    action: "Zbierz cechy, słownik tekstu, grupy i wersję konfiguracji dla jednego korpusu. Ten stan umożliwia wielokrotne porównanie nowych zgłoszeń bez ponownego grupowania.",
    input: "Korpus, ekstraktory i konfiguracja użyte do wyliczenia grup",
    output: "Wersjonowany stan referencyjny w pamięci",
    failure: "Zmiana danych, progów lub ekstraktora unieważnia odpowiedni zapis cache.",
    check: "Kolejne zapytania pozostawiają takie same grupy i statystyki korpusu."
  },
  upload: {
    title: "Nowe zgłoszenie", type: "formularz", owner: "C2", chapter: "zapytanie",
    action: "Analityk dodaje obraz, opcjonalnie opis i znany adres celu. Formularz rejestruje także, czy tekst lub adres zostały odczytane ze zrzutu.",
    input: "PNG lub JPEG oraz opcjonalne pola formularza",
    output: "Ad z nowym ID i source.kind=upload",
    failure: "Przy uszkodzonym obrazie UI wyjaśnia przyczynę i przyjmuje następny poprawny plik.",
    check: "Zgłoszenie pozostaje poza korpusem podczas oceny."
  },
  queryfeatures: {
    title: "Ekstrakcja zapytania", type: "Feature[]", owner: "A + B", chapter: "zapytanie",
    action: "Użyj tych samych ekstraktorów co przy budowie korpusu. Tekst zapytania przekształć wyłącznie słownikiem zapisanym w indeksie.",
    input: "Ad z formularza i konfiguracja referencyjna",
    output: "Cechy zapytania, ich pochodzenie oraz lista braków",
    failure: "Pominięcie metody zapisujemy jawnie, dzięki czemu można odróżnić brak danych od różnicy wartości.",
    check: "Zrzut i przepisany z niego URL mają wspólne pochodzenie."
  },
  members: {
    title: "Odczyt referencji", type: "grupy i ich członkowie", owner: "C1", chapter: "indeks",
    action: "Wczytaj członków istniejących grup, pojedyncze emisje i ich cechy. Zachowaj powiązanie każdego rekordu z jego źródłem.",
    input: "Indeks ustalonej wersji",
    output: "Referencyjne Ad, Feature i Campaign",
    failure: "Pusty korpus oznacza brak porównywalnych par. Pokaż brak wystarczających dowodów.",
    check: "Po zmianie korpusu nowe zapytanie wskazuje poprawny dataset_id."
  },
  querypairs: {
    title: "Porównanie 1 × n", type: "PairAssessment[]", owner: "C1", chapter: "para",
    action: "Każde zgłoszenie porównaj z każdym rekordem referencyjnym. W obu kierunkach użyj tych samych reguł rodzin, progów i pokrycia.",
    input: "Cechy zgłoszenia i n reklam referencyjnych",
    output: "n ocen par zawierających dowody i pokrycie",
    failure: "Wysoki wynik jednej pary sam nie wystarcza do przypisania całej grupy.",
    check: "Dla 13 referencji otrzymujesz 13 ocen zapytania, przy niezmienionych 78 parach w korpusie."
  },
  coverage: {
    title: "Pokrycie danych", type: "has_sufficient_coverage", owner: "C1", chapter: "para",
    action: "Sprawdź, czy istniała para z przynajmniej dwiema porównywalnymi, niezależnymi rodzinami. To ustala, ile można powiedzieć przy braku trafienia.",
    input: "Dostępne rodziny i origin_id obu stron każdej pary",
    output: "Informacja o wystarczającym pokryciu",
    failure: "Obraz bez drugiego niezależnego pola nie pozwala wykluczyć powiązania z kampanią.",
    check: "Brak drugiego pola różni się wynikiem od obecnego pola o innej wartości."
  },
  candidates: {
    title: "Pełne i częściowe grupy", type: "candidates · similar_ads", owner: "C1", chapter: "zapytanie",
    action: "Sprawdź wszystkich członków każdej grupy. Oddziel pełne dopasowania od częściowych i zachowaj interesujące pojedyncze reklamy spoza grup.",
    input: "Oceny par dla zapytania i skład grup",
    output: "Lista pełnych grup, sugestii oraz pojedynczych emisji",
    failure: "Dwie pełne grupy wymagają oceny analityka. Żadna nie dostaje automatycznego pierwszeństwa.",
    check: "Jedna pełna grupa z dodatkową częściową sugestią pozostaje prawdopodobnym przypisaniem."
  },
  decision: {
    title: "Decyzja", type: "MatchResult", owner: "C1", chapter: "zapytanie",
    action: "Najpierw policz pełne grupy i częściowe sugestie. Przy braku kandydatów użyj pokrycia, aby rozróżnić brak dowodów i możliwy nowy wzorzec.",
    input: "Kandydaci, similar_ads, pokrycie, identyfikator zbioru i konfiguracji",
    output: "Jeden z czterech statusów, reason_codes i referencje do dowodów",
    failure: "Możliwy nowy wzorzec trafia do dalszej weryfikacji. Potwierdzenie nowej grupy wymaga dalszych emisji.",
    check: "Przejdź przez cztery warianty SG-031 w przewodniku przykładowym."
  },
  panel: {
    title: "Panel analityka", type: "Streamlit", owner: "C2", chapter: "zapytanie",
    action: "Wyświetl status, grupę i najważniejsze powody decyzji. Dla dowodu pokaż oba rekordy, nazwy pól, oryginalne wartości, metrykę i pochodzenie.",
    input: "MatchResult oraz referencje do Evidence i Campaign",
    output: "Wyjaśnienie, które analityk może sprawdzić na obu materiałach",
    failure: "Przy wstrzymaniu decyzji pokaż brakującą rodzinę albo konfliktujące grupy.",
    check: "Z panelu decyzji da się wskazać oba źródła przynajmniej jednego obliczonego dowodu."
  },
  labels: {
    title: "Ocena przypadków", type: "etykiety poza silnikiem", owner: "A2 + B2", chapter: "walidacja",
    action: "Osoby oceniające zapisują uzasadnienia etykiet kampanii. Przypadki niepewne pozostają do opisowej oceny i nie powiększają mianownika metryk.",
    input: "Emisje, źródła i ocena analityków",
    output: "Etykiety z pewnością i udokumentowany podział",
    failure: "Duplikaty lub niemal identyczne kopie tej samej emisji w różnych częściach powodują przeciek.",
    check: "Sprawdź odciski i identyfikatory emisji przed strojeniem."
  },
  development: {
    title: "Część rozwojowa", type: "strojenie", owner: "C1", chapter: "walidacja",
    action: "Osobno dobierz próg tekstowy i konfigurację pełnej metody. W obu wariantach użyj tych samych przypadków oraz tej samej reguły scalania wyznaczonych krawędzi.",
    input: "Oznaczone przykłady rozwojowe",
    output: "Progi i konfiguracja gotowe do zamrożenia",
    failure: "Strojenie na końcowym teście zawyża ocenę przy następnym pokazie.",
    check: "Tekstowy wariant odniesienia może utworzyć krawędź na podstawie samego cosinusa."
  },
  holdout: {
    title: "Odłożony test", type: "nowe warianty i obce kampanie", owner: "A2 + B2", chapter: "walidacja",
    action: "Odłóż zgłoszenia z wariantami znanej kampanii oraz wszystkie emisje wybranej obcej kampanii. Ich etykiety pozostają u opiekunów testu do zamrożenia konfiguracji.",
    input: "Rozłączne przykłady z udokumentowanymi etykietami",
    output: "Zapytania testowe i osobny klucz oceny",
    failure: "Wariant testowy nie może wpływać na słownik tekstowy, częstości ani progi referencji.",
    check: "Pozostałe emisje znanej kampanii są w referencji, a emisje obcej kampanii są poza nią."
  },
  evaluation: {
    title: "Porównanie metod", type: "pełna metoda i TF-IDF", owner: "A2 + B2", chapter: "walidacja",
    action: "Po zamrożeniu uruchom oba warianty na identycznym teście. Osobno zbadaj pary w grupach i decyzje dla nowych zgłoszeń.",
    input: "Zamrożone konfiguracje oraz odłożony test",
    output: "TP, FP, FN, trafne, błędne i wstrzymane przypisania",
    failure: "Gdy mianownik wynosi zero, wynik pozostaje niemierzalny. Podaj również liczby bezwzględne.",
    check: "Do raportu dołącz wielkość próby, jej źródło, wersje konfiguracji i sprzęt."
  },
  report: {
    title: "Raport odbiorowy", type: "wyniki + próba instalacji", owner: "C1 + C2", chapter: "walidacja",
    action: "Zestaw precision i recall z przykładami fałszywych połączeń. Zmierz budowę indeksu i czas pojedynczego zapytania. Dodaj wynik czystego uruchomienia demonstratora.",
    input: "Zliczenia, dowody błędów, czasy i rejestr próby offline",
    output: "Odtwarzalny raport dla zespołu i oceniających",
    failure: "Syntetyczne przykłady sprawdzają reguły. Jakość na prawdziwych kampaniach wymaga potwierdzonych etykiet.",
    check: "Inna para potrafi odtworzyć wynik z tą samą konfiguracją i wersją danych."
  }
};

export const flows = {
  korpus: {
    title: "Budowa korpusu", initial: "ingest",
    summary: "Uruchamiasz po dodaniu materiałów lub zmianie metod. Z emisji, ich cech i ocen par powstaje indeks do późniejszych zapytań.",
    rows: [["corpus","captures"],["ingest","linkage"],["pixels","wording","urls"],["visualfeatures","textfeatures","infrafeatures"],["pairs"],["groups"],["index"]],
    edges: [["corpus","ingest"],["captures","linkage"],["ingest","pixels"],["ingest","wording"],["ingest","urls"],["linkage","urls"],["pixels","visualfeatures"],["pixels","textfeatures"],["wording","textfeatures"],["urls","infrafeatures"],["visualfeatures","pairs"],["textfeatures","pairs"],["infrafeatures","pairs"],["pairs","groups"],["groups","index"]]
  },
  zgloszenie: {
    title: "Nowe zgłoszenie", initial: "querypairs",
    summary: "Analityk dodaje materiał. System korzysta z tych samych ekstraktorów i odczytuje zapisane referencje. Wynik dotyczy tylko bieżącego zapytania.",
    rows: [["upload","index"],["queryfeatures","members"],["querypairs"],["coverage","candidates"],["decision"],["panel"]],
    edges: [["upload","queryfeatures"],["index","queryfeatures"],["index","members"],["queryfeatures","querypairs"],["members","querypairs"],["querypairs","coverage"],["querypairs","candidates"],["coverage","decision"],["candidates","decision"],["decision","panel"]]
  },
  walidacja: {
    title: "Walidacja", initial: "holdout",
    summary: "Najpierw oddziel dane do strojenia od prób końcowych. Dwie metody przechodzą ten sam test dopiero po zamrożeniu konfiguracji.",
    rows: [["labels"],["development","holdout"],["evaluation"],["report"]],
    edges: [["labels","development"],["labels","holdout"],["development","evaluation"],["holdout","evaluation"],["evaluation","report"]]
  }
};
