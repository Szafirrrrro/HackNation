# Ekran analityka — graf, dowód i oś czasu

Analityk ma móc przejść od zdania „ten post przypomina kampanię” do dwóch materiałów, które może samodzielnie porównać. Na planowanym ekranie **graf odpowiada na pytanie „co jest powiązane?”, panel z prawej „na jakiej podstawie?”, a oś pod grafem „kiedy to zaobserwowano?”**. Właścicielem ekranu jest para C. Źródłem wyników jest silnik opisany w [kontrakcie danych](DATA_CONTRACT.md).

Poniżej zachowano projekt interakcji zespołu. W dostarczonej wersji analityk klika węzeł lub linię na grafie pyvis albo wybiera połączenie z listy węzła. Pełne źródła porównania są dostępne na liście par pod grafem. Wykres Plotly filtruje zdarzenia według kampanii i pokazuje liczbę materiałów z brakującymi datami. Dwukierunkowe klikanie między wykresami pozostaje elementem planu. [Obsługa wersji demonstracyjnej](../graph/README.md)

## Jeden przebieg pracy

1. **Wczytaj zbiór.** W nagłówku wybierz lokalny korpus. Pod nazwą pokaż wersję indeksu, liczby emisji, powtórzonych plików, niezależnych zapisów stron i kampanii oraz dostęp do błędów importu. Wybór grupy w wykazie po lewej wyróżnia jej członków i zawęża oś do jej zdarzeń.
2. **Przejrzyj graf.** Jeden węzeł oznacza jedną emisję, obwiednia z nazwą i liczebnością oznacza proponowaną kampanię. Linia ciągła łączy mocno powiązaną parę. Przerywana wskazuje podobieństwo do przeglądu, także między grupami. Identyczna grafika może wystąpić w dwóch różnych postach. Legendę i listę par da się odczytać bez rozróżniania kolorów.
3. **Otwórz połączenie.** Kliknięcie krawędzi lub tej samej pary na liście pokazuje dwa ID i dwa odpowiadające sobie źródła. Przy obrazie są miniatury i porównany obszar, przy tekście wspólny fragment, przy infrastrukturze wartość i pole zapisu. Poniżej podaj metodę, zmierzoną wartość, próg, pochodzenie oraz wpływ na decyzję. Gdy OCR i tekst przepisany pochodzą z tego samego kadru, panel wskazuje wspólne źródło.
4. **Sprawdź historię.** Kliknięcie zdarzenia na osi podświetla post na grafie i otwiera szczegóły jego daty. Wybór postu na grafie wyróżnia wszystkie jego zdarzenia na osi. Przycisk „Wszystkie kampanie” przywraca widok zbioru.
5. **Porównaj nowy post.** W formularzu umieść obraz PNG/JPEG/WebP, tekst lub znany URL wraz z pochodzeniem. Po analizie pokaż na górze decyzję, przyczynę i zakres porównania. Oznacz zgłoszenie osobnym symbolem i pokaż trzy najwyżej ocenione propozycje z dostępem do reszty wyników. Grupy pochodzą z zapisanej referencji. Kolejne zapytanie korzysta z tej samej wersji.

## Jak czytać oś czasu

| Informacja w źródle | Prezentacja |
| --- | --- |
| Potwierdzony czas publikacji | Zdarzenie „Publikacja” z ID postu, wartością źródłową, jej strefą i odnośnikiem do pola. Porządek wyznacza wspólna skala czasu. |
| Czas pozyskania rekordu | Osobne zdarzenie „Pozyskanie”. Przy braku daty publikacji post ma adnotację „data publikacji nieustalona”. Tak przedstawiamy obecne reklamy z korpusu NASK. |
| Obserwacja powiązanej strony | Zdarzenie „Obserwacja strony” z ID zapisu i udokumentowanym powiązaniem z emisją. Samodzielne zapisy stron można porównywać w panelu źródeł. |
| Sam dzień, nieznana strefa lub brak daty | Pokaż precyzję obserwacji. Zachowaj datę dzienną bez dopisywania godziny. Przy niejednoznacznym czasie oznacz niepewność, a materiały bez daty wyświetl na liście pod osią. |

**Przykład kontrolowany.** Dwie syntetyczne emisje mają oddzielne daty publikacji, ale zostały zaimportowane tego samego dnia. Wybranie kampanii powinno pokazać osobno publikacje i pozyskania. Zawężenie przedziału czasu zmienia widoczność i licznik, np. „2 z 3 postów”. Skład grupy i obliczone dowody są stałe.

## Trudne przypadki na ekranie

| Stan | Co może zrobić analityk |
| --- | --- |
| Brak kampanii w zbiorze | Obejrzeć samodzielne posty i podobne pary, np. p3/p4. Otworzyć porównanie osobnych zapisów stron p1/p7. Ekran wyjaśnia brak niezależnego dowodu łączącego post ze stroną. |
| Konkurencyjne dopasowania | Wybrać każdą kandydaturę i obejrzeć jej źródła. Pokazać także częściowe podobieństwa i liczbę nieporównywalnych grup. Decyzję zwraca silnik według tabeli w kontrakcie. |
| Brak porównywalnych pól | Odczytać, których obserwacji brakuje i jaka część zbioru została sprawdzona. Formularz zachowuje użyteczne pola po błędzie pliku lub OCR. |
| Podobieństwo między kampaniami | Włączyć warstwę relacji przerywanych, kliknąć konkretną parę i obejrzeć wspólną cechę. Obwiednie kampanii pozostają osobne. |
| Brak danych do kalibracji | Odczytać typ relacji, miarę i przesłanki. Widok MVP używa opisowych decyzji. Wyświetlanie procentowych szans wymaga odrębnej próby kalibracyjnej i oceny na niezależnych kampaniach. |

## Implementacja i próba odbiorowa

Python i Streamlit obsługują import, formularz i wybór wyników. Jeden lokalnie dostarczony komponent JavaScript łączy **Cytoscape.js** dla grafu i **vis-timeline** dla osi. Oba widoki współdzielą identyfikatory kampanii, emisji i wybranego porównania. Oddzielnymi elementami stanu są bieżące zapytanie i filtr czasu. Przefiltrowanie widoku ani pozycja węzła na ekranie nie zmieniają decyzji silnika. Biblioteki komponentu pakujemy do aplikacji na potrzeby pokazu offline. [Cytoscape.js](https://js.cytoscape.org/) · [vis-timeline](https://visjs.github.io/vis-timeline/docs/timeline/) · [Komponenty Streamlit](https://docs.streamlit.io/develop/concepts/custom-components/overview)

Odbiór przeprowadza osoba spoza autorów UI. Wczytuje materiał z nowymi ID, wybiera kampanię i otwiera jedną parę z listy oraz z grafu. W obu miejscach musi zobaczyć te same źródła. Potem wybiera zdarzenie na osi, wskazuje jego post i rodzaj daty, zmienia filtr czasu i wraca do pełnej grupy. Na koniec wnosi obcą reklamę oraz materiał z brakami i tłumaczy różnicę między wynikami, korzystając wyłącznie z ekranu. [Scenariusz pokazu jury](MVP.md)
