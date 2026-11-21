# Zasady pracy nad ScamGraph

Pracę zacznij od [README](README.md). Sprawdź, które elementy są dostępne w repozytorium, co ma powstać oraz jak odtworzyć pierwsze ćwiczenie. Zakres zadania wyznacza oczekiwany wynik i ograniczenia podane przez użytkownika. W projekcie konkursowym odnoś decyzje do wymagań NASK i do kryteriów odbioru zespołu. [Plan MVP](docs/MVP.md) · [Zadanie](docs/NASK_ZADANIE.md) · [Regulamin](docs/NASK_REGULAMIN.md)

## Właściciele i źródła decyzji

| Obszar | Właściciel | Co przeczytać przed zmianą |
| --- | --- | --- |
| Import, emisje, strony, pochodzenie | Para A | [Przewodnik po danych](docs/NASK_DATA.md) i [kontrakt](docs/DATA_CONTRACT.md). Tu sprawdzisz, które relacje potwierdzają źródła. |
| Cechy obrazu i tekstu, doświadczenia z modelami, pomiar | Para B | [Laboratorium](models/README.md) i [kontrakt](docs/DATA_CONTRACT.md). Każdy wynik musi dać się powiązać z materiałem i wersją metody. |
| Pary, kampanie i zapytania | Para C | [Kontrakt](docs/DATA_CONTRACT.md). Tu utrzymujemy definicje niezależnego dowodu, grupowania i pierwszeństwa statusów. |
| Ekran analityka i pakiet jury | Para C | [Graf i oś czasu](docs/PLAN_GRAF_I_OS_CZASU.md) oraz [instrukcja budowy](docs/INSTRUKCJA_BUDOWY.md). Interfejs prezentuje decyzję tego samego silnika, z którego korzysta ewaluacja. |

Gdy zmienia się zachowanie na granicy modułów, zacznij od uzgodnienia kontraktu z odbiorcą. Uaktualnij przykłady, instrukcję integracji i testy, których dotyczy decyzja. Oryginalne wymagania konkursowe cytuj ze wskazaniem punktu. Własne progi, testy i założenia podpisuj jako decyzje zespołu.

## Prowadzenie zadania

1. Przed edycją sprawdź stan drzewa roboczego, instrukcje dla danego katalogu i aktualny kod, dokumentację oraz testy. Zachowaj zastane zmiany użytkownika. Ogranicz zakres diffu do zamówionego wyniku.
2. Główny agent odpowiada za realizację, integrację, sprawdzenia, przegląd i poprawki. Przy podziale pracy przypisz właściciela każdemu fragmentowi i ustal, co ma przekazać następnej osobie. Wybieraj rozwiązania możliwe do zweryfikowania, utrzymuj zgodność z dotychczasowymi odbiorcami i wykorzystuj istniejącą logikę.
3. Lokalne, odwracalne decyzje podejmuj na podstawie danych i odnotuj istotne założenia. Zwróć się do użytkownika, gdy wybór zmienia zakres albo wymaga osobnego upoważnienia. W tym czasie kontynuuj niezależne prace.
4. Materiały organizatora i prywatne wyniki pochodne przechowuj w dostępie ograniczonym do wyzwania. Uwzględnij historię Git i zawartość eksportów. Do publicznych przykładów używaj własnych materiałów. Przy nowym źródle zapisz pochodzenie i warunki wykorzystania. [Zasady użycia danych, pkt 8](docs/NASK_ZADANIE.md)
5. Dla zmian w dopasowaniu sprawdź deduplikację emisji, pochodzenie cech, brakujące pola i zachowanie na nowych ID. Obraz, jego kadr i OCR mają wspólne pochodzenie. Zbiory referencyjny, rozwojowy i końcowy muszą mieć opisany skład i zastosowanie. Etykiety końcowe służą ewaluacji.

## Sprawdzenia i niezależny przegląd

Weryfikuj małe, działające etapy. Zacznij od testu zmienionej reguły, następnie sprawdź wejście używane przez analityka i przypadki awarii lub zgodności. Gdy zmiana dotyka kilku modułów, uruchom szersze sprawdzenia. Dodaj test regresji dla konkretnego dotąd niepokrytego błędu lub gdy jest wymagany. Diagnozuj nieudane próby i ponawiaj je po usunięciu przyczyny.

**Punkt kontrolny** następuje po decyzji o architekturze lub kontrakcie, uzyskaniu działającego przebiegu, ryzykownej integracji i przed oddaniem wyniku. Drobne edycje można zebrać w jeden przegląd. Po każdym takim punkcie oddzielny agent, który nie wdrażał ocenianej zmiany, czyta rzeczywisty diff lub artefakt. Przekaż mu zadanie, kryteria odbioru, ograniczenia, dokładny zakres i wyniki wykonanych sprawdzeń. Recenzent przedstawia ocenę bez edycji recenzowanego materiału.

| Waga uwagi | Kiedy jej użyć | Co robi właściciel |
| --- | --- | --- |
| Blokująca | Brak wymaganego wyniku, niedziałający odbiór lub poważne ryzyko, np. utraty danych | Rozwiązuje problem przed pracą zależną i przed oddaniem. |
| Poważna | Istotna luka w poprawności, niezawodności, zgodności lub weryfikacji | Naprawia w zakresie zadania albo uzyskuje wyraźną zgodę użytkownika na odroczenie. |
| Drobna | Problem lokalny o ograniczonym wpływie | Ocenia koszt i wprowadza celową poprawkę. |
| Sugestia | Ulepszenie poza warunkiem odbioru | Rozważa je w kontekście zakresu. |

Recenzent porządkuje uwagi według wagi, wskazuje miejsce, skutek i sposób odtworzenia oraz podaje jawny werdykt, także przy braku uwag lub częściowej weryfikacji. Właściciel porównuje każde zgłoszenie z dowodami. Dokumentuje los otwartych i odrzuconych uwag oraz podstawę odrzucenia uwagi poważnej lub blokującej. Po ich naprawie powtarza odpowiednie testy i kieruje poprawkę do niezależnej weryfikacji.

## Oddanie wyniku

Przed zakończeniem przejrzyj ostateczny diff i potwierdź, że niezależny przegląd obejmuje ostatnie istotne zmiany. Zgłoś ukończenie po dostarczeniu wyniku, wykonaniu odpowiednich sprawdzeń oraz usunięciu wszystkich blokad. W podsumowaniu podaj rezultat, faktycznie wykonane testy, werdykt recenzenta, istotne założenia, uzgodnione odroczenia i pozostałe ograniczenia pomiaru. Jeśli dalszą pracę uniemożliwia zewnętrzna zależność, brak upoważnienia lub recenzenta, oznacz wynik jako oczekujący i wskaż, co konkretnie pozwoli kontynuować.
