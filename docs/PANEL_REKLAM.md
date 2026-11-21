# Panel wyszukiwania reklam

Panel ScamGraph pozwala znaleźć reklamę po ID emisji, sprawdzić, dlaczego została zapisana, i obejrzeć materiały ze strony docelowej. Na pierwsze ćwiczenie wybierz demo. Dwie przykładowe karty wystarczą, żeby przejść od wyszukiwania do pakietu dowodowego.

## Pierwsze uruchomienie na Windows

Otwórz PowerShell w katalogu projektu. W tej instalacji to `C:\HackNation\HackNation`. Przy pierwszej instalacji przygotuj środowisko z Pythonem 3.12 lub nowszym. Jeśli projekt ma już działające środowisko `.venv`, przejdź do polecenia uruchamiającego panel.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-capture.txt
```

Uruchom demo i otwórz [panel w przeglądarce](http://127.0.0.1:8527/).

```powershell
.\.venv\Scripts\python.exe -m scamgraph.live --config discovery.demo.json serve --port 8527
```

Pozostaw PowerShell otwarty. Polecenie `serve` uruchamia też zegar wyszukiwań. Aby zakończyć pracę lub zmienić profil na tym samym porcie, naciśnij **Ctrl+C** w tym oknie. Zamknięcie karty przeglądarki pozostawia zegar uruchomiony. Zapisane wyniki można ponownie otworzyć z tym samym profilem.

## Od wyszukiwania do konkretnej reklamy

1. W **Zakres uruchomienia** wybierz źródło i kliknij **Uruchom teraz**. W **Stan źródeł** sprawdź tryb. W demo zobaczysz `replay`, czyli odczyt lokalnego przykładu. W profilu przeglądarkowym zobaczysz `live`.
2. Odczytaj liczniki. **Odczytane** podaje liczbę odczytanych kart, **Nowe** i **Znane** pokazują, które emisje pojawiły się po raz pierwszy, a **Braki w karcie** sygnalizują niepełne dane. Przy kolejnym przebiegu demo oczekiwany wynik to dwie znane karty i zero nowych.
3. Przewiń do **Kandydaci do przeglądu**. Przy reklamie zobaczysz nazwę, ID emisji i powód znalezienia. Kliknij **Otwórz znalezisko**, aby obejrzeć dowody. Dopasowanie frazy kwalifikuje reklamę do przeglądu przez analityka.
4. Aby obejrzeć tylko wyniki jednego wyszukiwania, w **Odczyt stron docelowych** wybierz **Przebieg i fraza**. Porównaj liczniki **Karty**, **Z celem CTA** i **Odczytane strony**. CTA oznacza tu przycisk lub link reklamy prowadzący do oferty. Wybierz ID z listy **Dowody reklamy z tego przebiegu** i kliknij **Otwórz pakiet reklamy**. Jeśli wizyta skończyła się już po otwarciu karty, użyj **Otwórz uzupełniony pakiet**.

## Wyszukiwanie rzeczywistych reklam

Panel i PowerShell korzystają z tego samego adaptera. Playwright otwiera publiczną Bibliotekę reklam Meta w lokalnym Chrome bez API i tokenu Meta. W tej instalacji przygotowano prywatny profil dla Polski z limitem do 40 kart na frazę. Po zatrzymaniu demo uruchom go i otwórz ten sam adres panelu.

```powershell
.\.venv\Scripts\python.exe -m scamgraph.live --config .private-discovery/browser-40.json serve --port 8527
```

Na nowej instalacji utwórz prywatną kopię `discovery.live.json` w katalogu projektu pod nazwą `discovery.local.json`. Uzupełnij w niej `sources.meta.permission` zakresem udzielonego uprawnienia do automatycznego odczytu Meta. W poleceniu powyżej podaj wtedy `--config discovery.local.json`.

Frazy ustawiasz w `sources.meta.phrases` wybranego pliku JSON, a maksymalną liczbę kart na frazę w `sources.meta.limit`. **Uruchom teraz** używa tej listy. Pole frazy w **Diagnostyka Meta** służy do osobnego sprawdzenia. Domyślny profil live sprawdza źródło co 30 minut. Liczba nowych reklam i liczba zapisanych stron mogą być mniejsze od limitu.

## Uruchom teraz z PowerShella

W katalogu projektu wykonaj poniższe polecenia. Wybierz ten sam plik konfiguracji co w panelu, żeby użyć tych samych fraz i zapisać wyniki w tej samej bazie.

```powershell
.\.venv\Scripts\python.exe -m scamgraph.live --config .private-discovery/browser-40.json run --source meta
```

To odpowiednik wyboru źródła Meta i kliknięcia **Uruchom teraz**. Dla opcji **Wszystkie źródła** pomiń `--source meta`. Komenda wykonuje jeden przebieg, obsługuje jego kolejkę wizyt na stronach docelowych, odświeża graf i wypisuje podsumowanie JSON. Panel może być zamknięty. W trybie live adapter nadal używa Chrome w tle.

Aby odczytać ostatni stan źródeł i listę reklam bez ponownego wyszukiwania, wykonaj w tym samym oknie:

```powershell
$wynik = .\.venv\Scripts\python.exe -m scamgraph.live --config .private-discovery/browser-40.json status | ConvertFrom-Json
$wynik.sources | Format-Table source_id, status, read_count, new_count, known_count, error -Wrap
$wynik.candidates | Select-Object ad_ref, capture_id
```

Na świeżej instalacji w obu poleceniach podaj po `--config` przygotowany wcześniej plik `discovery.local.json`. Do ćwiczenia offline wybierz `discovery.demo.json`.

## Gdzie są pliki

W tej instalacji dane profilu przeglądarkowego trafiają do `C:\HackNation\HackNation\.private-discovery\browser-live`, a demo do `C:\HackNation\HackNation\.private-discovery\demo`. Własny profil zapisuje wyniki w katalogu wskazanym przez `state_dir`, liczonym względem położenia jego pliku JSON.

| Ścieżka wewnątrz katalogu profilu | Co tam znajdziesz |
| --- | --- |
| `discovery.sqlite3` | Historia przebiegów, kandydaci, obserwacje emisji i stan kolejki wizyt. Panel czyta stąd liczniki i statusy. |
| `captures/<id_pakietu>/` | Pakiet obserwacji reklamy. `manifest.json` wymienia pliki i ich sumy kontrolne, `extracted.json` zawiera odczytane pola, a `landing/` zawiera materiał strony, jeśli został zebrany. |
| `pages/<id_pobrania>/` | Paczka jednej wizyty. Przy pełnym zapisie zawiera `page.html` (wyrenderowany dokument), `page_files/` (lokalne zasoby), `screenshot.png` (widok strony), `network.har` (ruch sieciowy) i `metadata.json` (adres, czas, status i błędy). |
| `archives/meta/` | Materiał źródłowy adaptera Meta, w tym dostępne zrzuty kart lub ekranu błędu. |
| `graph/` | Wyniki analizy kampanii, m.in. `live.campaigns.json` dla trybu live. |

Najkrótsza droga z ekranu na dysk prowadzi przez **Otwórz znalezisko**. W adresie panelu wartość parametru `znalezisko` wskazuje folder w `captures/`. Otwórz w nim `extracted.json`. Jeśli zapisano wizytę, wartość `landing_visit.page_id` wskazuje jej folder w `pages/`. ID emisji widoczne przy nazwie reklamy służy do rozpoznania jej w bibliotece Meta.

## Gdy brakuje wyników

- **HTTP 403 i zero kart.** W **Stan źródeł** przeczytaj **Przyczyna błędu**. Jeśli komunikat zaczyna się od „Dokument Meta HTTP 403”, serwer odmówił dostępu do strony wyników. Do takich prób nie powstają paczki nowych reklam. Jeśli zapisano zrzut, jego nazwę znajdziesz w komunikacie, a plik w `archives/meta/`.
- **Jest reklama, ale folder `landing/` jest pusty.** W **Odczyt stron docelowych** sprawdź kolumny **Wizyta**, **Powód** i **Strona**. Możliwe przyczyny to oczekująca wizyta, brak jednoznacznego adresu w karcie albo pominięcie zaufanej domeny. Przy częściowym pobraniu zajrzyj do `metadata.json` i sprawdź zachowane pliki. Błąd pobrania pozostawia ocenę bezpieczeństwa strony otwartą.
- **Widzisz tylko dwie przykładowe reklamy.** Sprawdź tryb i użyty plik konfiguracji. Demo i live mają osobne katalogi wyników, choć otwierasz je pod tym samym adresem panelu.
