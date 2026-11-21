# Jak zbudować i odebrać ScamGraph

W repozytorium są korpus, zapisane obserwacje i laboratorium modeli. Silnik dopasowania, GUI i kontener aplikacji są zaplanowane do wykonania. Pierwszy cel integracji to dodanie wcześniej niewidzianego pliku i przejście od obliczonego podobieństwa do dwóch oryginalnych obserwacji. [Plan MVP i terminy](MVP.md) · [Kontrakt danych i decyzji](DATA_CONTRACT.md)

## Co można sprawdzić przed implementacją

W prywatnej kopii projektu uruchom poniższe polecenia w **PowerShell z katalogu głównego**. Pierwszy blok używa standardowej biblioteki Pythona. Liczba poprawnie zweryfikowanych obrazów w obecnym korpusie powinna wynieść 13. Błąd sumy lub powiązania przerywa weryfikację.

```powershell
@'
from pathlib import Path
from hashlib import sha256
import json

root = Path("data/nask-hacknation-2026")
def rows(path):
    return [json.loads(s) for s in (root / path).read_text(encoding="utf-8").splitlines() if s.strip()]

ads = rows("ads.jsonl")
shots = rows("observations/screenshots.jsonl")
by_id = {s["ad_id"]: s for s in shots}
assert len(ads) == len(shots) == len(by_id) == len({a["ad_id"] for a in ads})
for ad in ads:
    image = (root / ad["image_path"]).read_bytes()
    assert sha256(image).hexdigest() == by_id[ad["ad_id"]]["sha256"], ad["ad_id"]
print("Zweryfikowane obrazy:", len(ads))
'@ | py -3 -B -
```

```powershell
py -3 -B -m unittest discover -s testowanie_modeli/tests -v
```

Druga komenda uruchamia cztery testy mechanizmu pomiarowego. Wynik oczekiwany to `OK`. Do pomiaru modeli potrzebne są Bash, Docker dla Linuksa i wagi pobrane na etapie budowy obrazu. [Uruchomienie benchmarku CPU](../testowanie_modeli/README.md)

## Pierwszy wspólny przebieg

| Kto | Co dostarcza na integrację | Jak druga para odbiera pracę |
| --- | --- | --- |
| **A · dane i źródła** | Importer lokalnego korpusu, dwa rekordy z odwołaniami do źródeł, jedną obserwację strony, raport błędów i pokrycia. | B otwiera obraz po ID. Ponowny import zachowuje liczbę emisji. Dwa odrębne ID biblioteki mogą korzystać z tego samego zasobu. |
| **B · ekstrakcja i pomiar** | SHA-256 z bajtów, pHash, opcjonalny lokalny OCR i TF-IDF. Dla każdej wartości zapisuje metodę, źródło oraz wskazanie pola albo kadru. | C pokazuje rzeczywistą odległość między obrazami oraz obie wartości. Podmiana jednego pliku przelicza wynik. |
| **C · korelacja i GUI** | Testy i Streamlit wywołują wspólny silnik, który buduje referencję i analizuje zgłoszenie. GUI pokazuje dowody i decyzję. | A dodaje własny plik. Po otwarciu relacji widzi, które dwa rekordy porównano, co je łączy i jakich pól brakuje. |

**21 listopada do 18:00** zespół odbiera pierwszy przebieg. Do 20:00 przygotowuje robocze zgłoszenie, a o północy odbiera pełną bazę CPU. **22 listopada o 07:00** zamraża parametry. Złożenie projektu zaplanowano na 10:30 przed terminem 11:00. Godziny obowiązują w Polsce. [Harmonogram i podział pracy](MVP.md)

### A · import i powiązania ze źródłami

1. Czytaj manifest, a następnie wiersze JSONL. Obsługuj obce ID, pliki z brakującym obrazem oraz materiał podany przez formularz. Ścieżka mediów powinna po rozwiązaniu wskazywać plik w katalogu dozwolonym dla danego korpusu. Zwróć identyfikator, pole i przyczynę błędu. Zachowaj użyteczne pola poprawnych rekordów. [Pola i typy relacji](DATA_CONTRACT.md)
2. Osobno śledź rekord emisji, treść pliku, obserwację strony i rodzaj związku z emisją. Dołącz infrastrukturę do reklamy po udokumentowanym wskazaniu źródłowym. Wspólny katalog archiwum pozwala pokazać hipotezę do sprawdzenia. Trzy ID Biblioteki reklam Meta dają początek weryfikacji. Jeżeli organizator przekaże `DANE.zip`, zachowaj jego skrót, pochodzenie i warunki, obejrzyj strukturę i dopiero wtedy dobierz adapter. Zawartość tego archiwum nie została lokalnie potwierdzona. [Materiały, obserwacje i duplikaty](NASK_DATA.md)
3. Oddaj prywatny zestaw referencyjny i osobną próbę ewaluacyjną z uzasadnionymi etykietami. Kopie tej samej emisji pozostają razem. Dla znanego wariantu w referencji powinny zostać inne emisje z tej kampanii. Dla kampanii nowej odłóż wszystkie jej emisje. Dwóch oceniających osobno zapisuje podstawę etykiety. Spory trafiają do uzgodnienia lub do puli nieustalonej. Silnik nie otrzymuje etykiet oceny.

### B · cechy i wybór modelu

1. Użyj Pythona, Pillow i ImageHash. Zweryfikuj format i wymiary obrazu, uwzględnij orientację i zachowaj współrzędne wykorzystanego kadru. pHash obliczaj ze znormalizowanego obrazu. SHA-256 licz z oryginalnych bajtów. Dla problematycznych przycięć porównaj z lokalnymi punktami OpenCV ORB i sprawdź zgodność rozmieszczenia dopasowań. Warstwa wizualna powinna wskazać analitykowi obszar wspólny obu materiałów.
2. Tesseract 5 z polskim i angielskim pakietem językowym odczytuje tekst i umożliwia zapisanie obszaru odczytu. Domyślna baza tekstowa to scikit-learn `TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5))`. Słownik dopasuj do referencji. Zgłoszenie porównuj za pomocą `transform`. Pokazuj rozpoznane frazy i odnośnik do obrazu także przy skromnym pokryciu. OCR, jego transkrypcja i embedding tego samego kadru dziedziczą tę samą obserwację.
3. Wydobądź lokalnie pola zapisanych URL, HTML i HAR. Zachowuj wartość oryginalną, znormalizowany host, znaczące części ścieżki, wartości identyfikatorów, stan odpowiedzi i źródło. Oddziel popularne usługi platformy od specyficznych integracji. Zgrupuj powtórzenia tej samej obserwacji. Wykaż na kontrprzykładzie wpływ wspólnego parametru reklamowego.
4. Mierz koszt całej ścieżki na CPU. Czas zimnej budowy referencji i odczytu OCR raportuj oddzielnie. Porównaj wariant tekstowy z pełnym klasycznym. Eksperyment na RTX 3050 Laptop 4 GiB ma sens po ustaleniu, czy błąd powodują kadry (DINOv2-small) czy parafrazy (E5-small). Decyzję o włączeniu jednego modelu podejmij na części rozwojowej. [Warunek jakości, budżet CPU i plan GPU](../testowanie_modeli/README.md)

### C · od wyniku pary do pracy analityka

1. Każda porównywalna para zwraca cechy, wartości z obu stron, pochodzenie, wynik metryki i braki. Odróżniaj ponowne użycie pliku, wariant kreacji i hipotezę kampanii. Przy kwalifikowaniu mocnej relacji uwzględnij niezależność obserwacji po obu stronach. Warunki i kolejność decyzji dla nowych zgłoszeń określa jedna tabela w [kontrakcie](DATA_CONTRACT.md).
2. Zbuduj referencję z wszystkich par. Dla 13 rekordów koszt to 78 porównań. Rozpatruj mocne krawędzie w deterministycznej kolejności. Połącz grupy, jeśli każda para między nimi jest mocna (complete-link). Przy mocnym A–B i B–C oraz słabym A–C analityk powinien widzieć też relację pozostałą do sprawdzenia. Zapytanie porównaj ze wszystkimi emisjami poza samym zgłoszeniem. Referencja pozostaje stała pomiędzy zapytaniami. Przy jej zmianie oblicz odcisk danych, parametrów i metod ponownie.
3. Ekran w Streamlit ma przyjąć katalog lub zgłoszenie, otworzyć oba źródła, pokazać wynik i przesłanki. Połącz Cytoscape.js i vis-timeline w jednym lokalnym komponencie. Wybór w grafie podświetla odpowiednie obserwacje na osi czasu i odwrotnie. Błąd odczytu lub pusty wynik ma prowadzić do następnej analizy. Po wyłączeniu sieci skrypty i style muszą nadal działać. [Interakcje i próby odbiorowe](PLAN_GRAF_I_OS_CZASU.md)

## Planowane uruchomienie demonstratora

C przygotowuje jeden kontener CPU, przypina przetestowane zależności i dołącza program Tesseract oraz języki `pol` i `eng`. Kod GUI, silnika, ewaluacji i plik definicji obrazu aplikacji są do wytworzenia. **Docelowe punkty wejścia**, dostępne po dostarczeniu aplikacji, to uruchomienie testów projektu i lokalny start Streamlit w katalogu głównym. C uzupełni ostateczną instrukcję o sprawdzone na czystym stanowisku polecenia instalacji i kontenera.

```bash
python -m pytest
python -m streamlit run app.py --server.address 127.0.0.1
```

Zamontuj prywatny korpus tylko do odczytu. W czystym środowisku sprawdź `tesseract --list-langs`, zbuduj referencję, przeanalizuj dwa różne pliki i ponownie pierwszy z nich. Przy tej samej konfiguracji jego wynik i dowody powinny się powtórzyć. Odbierz także tryb CPU z wyłączonym GPU oraz przypadek brakującego OCR. Przedstaw p95 od przyjęcia obrazu do wyniku po zbudowaniu indeksu i liczebność pomiaru. Projektowy cel wynosi 5 s.

## Odbiór i pakiet konkursowy

- Na odłożonych materiałach zmierz trafność i kompletność połączeń po grupowaniu, poprawne i błędne przypisania nowych emisji, wstrzymania, odzyskane warianty w top-3 i pokrycie. Podaj liczby TP/FP/FN, mianowniki i rodzaj etykiet. Przy zerowym mianowniku oznacz wynik jako niemierzalny. Dane syntetyczne służą próbie zachowania reguł. Jeżeli brak niezależnych etykiet rzeczywistych kampanii, przedstaw jakość rozpoznawania kreacji i pozostaw ocenę kampanii otwartą.
- Przeprowadź pokaz od importu do otwarcia dowodu dla duplikatu pliku, odłożonego wariantu znanej grupy, odrębnej kampanii i materiału z brakami. Dodaj obcy katalog z innymi ID, konkurujące grupy, błędny obraz, generyczny parametr i zawodny odczyt OCR. Osoba spoza autorów danego modułu sprawdza wynik przez GUI oraz dokumentuje problemy. [Zasady przeglądu](../AGENTS.md)
- Przekaż jury działający kod, instrukcję instalacji i odtworzenia pomiaru, konfigurację, metodykę, rejestr źródeł, raport o wzorcach i ograniczeniach oraz wykaz komponentów i licencji. Odróżnij prawa do wkładu zespołu od warunków bibliotek i wag. Pakiet dla jury przygotuj w dostępie ograniczonym. Publiczny pokaz oprzyj na własnych danych, a eksport sprawdź również pod kątem plików wynikowych i historii Git. [Wymagania](NASK_ZADANIE.md) · [Regulamin](NASK_REGULAMIN.md)
