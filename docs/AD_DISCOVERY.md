# Wyszukiwanie reklam i panel schedulera

## Zegar live, demonstracja i kampanie

W prywatnej bazie `<state_dir>/discovery.sqlite3` tabela `trusted_domains(domain)` początkowo jest pusta. W poniższym przykładzie zastąp `sklep.example` nazwą zatwierdzoną przez zespół i wybierz ten sam plik konfiguracji co działający zegar.

```powershell
python -m scamgraph.discovery --config discovery.live.json trusted-domains add sklep.example
python -m scamgraph.discovery --config discovery.live.json trusted-domains list
python -m scamgraph.discovery --config discovery.live.json trusted-domains remove sklep.example
```

Filtr działa przy zapisie karty, przy podejmowaniu oczekującej wizyty i przed połączeniem z kolejnym hostem w łańcuchu przekierowań dokumentu. Domenę `www.sklep.example` można dodać osobnym wpisem. Pakiet karty i przyczyna pominięcia pozostają dostępne. Filtr dotyczy celów potwierdzonych w CTA, także po rozpakowaniu linku Meta. Zasoby innych stron oraz import offline zachowują dotychczasową obsługę.

Uruchom `python -m scamgraph.discovery --config discovery.live.json serve` w środowisku z zależnościami z `requirements-capture.txt`. Profil live używa adaptera przeglądarkowego Meta. Przed pierwszą wizytą uzupełnij `sources.meta.permission` opisem udzielonego uprawnienia, najlepiej w prywatnej kopii konfiguracji przekazanej przez `--config`. Chrome odczytuje do 40 kart na frazę w kraju PL co 1800 sekund. Pierwszy odczyt nowego źródła jest gotowy od uruchomienia. Wersja pokazowa `--config discovery.demo.json serve` powtarza co 30 sekund dwie syntetyczne karty i zachowuje osobny stan. Panel działa na `127.0.0.1:8527`. Polecenie `timer` działa bez panelu.

Karta trafia do panelu po zapisie paczki, także podczas trwającego wyszukiwania. Dla kart WWW z celem CTA osobna kolejka uzupełnia tę samą obserwację o paczkę strony i stan wizyty. Przy przerwaniu procesu zegar wznawia oczekujące wizyty, a po trzech przerwanych próbach zapisuje błąd. Przed każdą wizytą sprawdza aktualną konfigurację źródła.

Worker grafu sprawdza dane co trzy sekundy. Po zmianie publikuje `graph/<tryb>.jsonl` oraz przelicza kampanie i uzasadnienia par przy użyciu istniejącego modułu `ftf_graph`. Wynik w panelu odpowiada raportowi `graph/<tryb>.campaigns.json`. Podczas obliczeń widać ostatni ukończony wynik z czasem wyliczenia. Nowy błąd pozostawia dotychczasowy raport i sygnał w panelu. Tryby live, import i replay mają oddzielne wyniki. Odstęp między publikacją reklamy na platformie i jej wykryciem zależy od indeksowania, interwału i limitu wyników.

Jeden proces zegara sprawdza terminy zapisane w prywatnej bazie SQLite. CLI, timer i przycisk panelu uruchamiają ten sam przebieg. Rezerwacja w transakcji SQLite obejmuje wybrane źródła przed odczytem. Panel odczytuje bieżący stan, liczniki i historię powodów znalezienia. Odświeżenie widoku jest operacją odczytu.

Adapter dostaje frazę, kraj i limit wyników. Dla każdej odczytanej emisji przekazuje znormalizowaną kartę oraz lokalizację oryginału. Tożsamość emisji tworzy para dostawca i identyfikator. Powtórne wyszukanie tej emisji zachowuje powody znalezienia. Pakiet plikowy można otworzyć z wiersza kandydata. Zgodność frazy stanowi przesłankę do przeglądu. Związek reklamy ze stroną docelową wymaga oddzielnego dowodu.

Pierwsze dwa źródła to publiczna Biblioteka reklam Meta i lokalny korpus NASK. Historyczny odczyt biblioteki działa w trybie replay. Ręcznie zapisany wynik pracuje w trybie import. Tryb live wymaga zakresu uprawnienia operatora do automatycznego dostępu przez WWW. Korpus działa w trybie import i zachowuje pochodzenie organizatora.

## Strona otwierana przez przycisk reklamy

W trybie Meta live scheduler szuka odnośnika w obrębie konkretnej karty. Obsługuje m.in. „Kup teraz”, „Obejrzyj więcej”, „Watch more” i „Learn more”, także gdy etykietę podaje atrybut dostępności. Odczytuje jawny adres przycisku lub obejmującego go linku, w tym adres opakowany przez Meta. Może również wybrać jednoznaczny link w podglądzie kreacji. Pozostałe kwalifikujące się linki daje do potwierdzenia w panelu. Przyciski bez adresu i odmowy dostępu mają osobne statusy. Import i replay działają offline.

Każda wizyta tworzy prywatne `pages/<id_pobrania>/` w katalogu stanu. `page.html` zachowuje DOM, a `page_files/` zawiera pobrane pliki, w tym skrypty, arkusze i fonty. `screenshot.png` pokazuje pierwszy viewport 1280 × 720. Dodatkowo dla WWW może powstać `screenshot_full.png` lub ograniczony rozmiarem `page-partial.png`. Pierwotna odpowiedź trafia do `original/response.*`. W `network.har` są pierwotne URL-e z parametrami, nagłówki, czasy, przekierowania i treści odpowiedzi. Pola `_browserHeaders` i `_browserTimings` pozwalają odróżnić dane przeglądarki od pomiarów transportu HTTP. Metadane znajdują się w `metadata.json`. [Statusy i pochodzenie danych](DATA_CONTRACT.md#zapis-jednej-wizyty-http)

Główną odpowiedź zapisuje się przed uruchomieniem Chrome. Transport ogranicza wizytę do odczytów GET, 64 żądań, 8 MiB na główną odpowiedź, 4 MiB na zasób i 16 MiB materiału. Przejściowy timeout głównej odpowiedzi lub HTTP 5xx może uruchomić jedno ponowienie w tym samym budżecie. Po pierwszym zrzucie Chrome przewija maksymalnie 16 wysokości viewportu i pozostawia formularze i okna zgody w zastanym stanie. HAR zachowuje dostępne odpowiedzi błędów HTTP i ślad obu prób. Oryginał, pierwszy DOM, zrzut i już zapisane pliki pozostają dostępne po przerwaniu wizyty.

Publiczne posty, ogłoszenia Marketplace, rolki i filmy Facebooka wymagają potwierdzenia tożsamości obiektu w treści dokumentu. Zapis celu obsługuje też PDF, PNG, JPEG, GIF, WebP, WAV oraz MP4 z obrazem lub M4A z dźwiękiem do limitu głównej odpowiedzi. Dla innych typów, ekranów logowania, odmów i błędów panel pokazuje wynik z osobnym kodem przyczyny. Wyszukiwanie oraz odczyt celów wymagają zakresu uprawnienia do odpowiednich publicznych źródeł.

Scheduler zapisuje identyfikator paczki w `landing_visit.page_id` i kopiuje materiały do `landing/` obserwacji emisji, gdzie manifest zabezpiecza ich sumy SHA-256. W zakładce **Strona** widać identyfikator paczki i stan wizyty. Powiązanie wskazuje zarówno źródłowy przycisk na karcie, jak i odpowiedź końcowego dokumentu w HAR. Zebrany tekst strony można pobrać jako `landing/page.txt`. Starsze obserwacje zachowują własne ścieżki.

### Jednorazowy zapis URL-a

Status przebiegu w historii opisuje odczyt kart biblioteki. Kompletność strony sprawdzisz w jej `metadata.json`. Pusty `landing/` może oznaczać brak celu w karcie, odnośnik bez rozpoznanej etykiety CTA albo kilka różnych celów. Powód podaje `landing_visit.reason`. Odczyt obsługuje również przycisk „Subscribe”. Zapis HTML odpowiedzi 403 i zrzut mogą dokumentować ekran odmowy.

Limit całej wizyty to domyślnie 22 sekundy. Do 6 sekund przypada na zakończenie renderowania i eksport. Krótszy przydział z zegara zmniejsza także tę rezerwę. W HAR przy przerwanym żądaniu można odróżnić wyczerpanie czasu, liczby żądań i limitu bajtów.

W katalogu worktree, z zainstalowanym Chrome i zależnościami z `requirements-capture.txt`, można podać jeden lub kilka adresów. Kolektor wypisuje status i ścieżkę każdej wizyty. Ścieżkę otrzymanej paczki można również podać importerowi `python -m scamgraph`.

```powershell
python -m scamgraph.discovery.landing_visit https://example.org/ --store .private-discovery/pages
```

## Uruchomienie na Windows

Wykonaj polecenia w katalogu projektu. Panel nasłuchuje na interfejsie lokalnym. Po zamknięciu procesu pozostają baza, terminy i dowody.

```powershell
py -3 -m venv .venv
$py = '.\.venv\Scripts\python.exe'
& $py -m pip install -r requirements-capture.txt
& $py -m scamgraph.discovery --config discovery.demo.json serve --port 8527
```

Otwórz [panel](http://127.0.0.1:8527/) i kliknij **Uruchom teraz**. Drugie okno PowerShell w tym samym worktree może wywołać ten sam przebieg lub odczytać stan.

W oknie **Diagnostyka Meta** wpisz frazę i wybierz **Pokaż zapis adaptera**, aby odczytać z bazy ostatni przebieg live dla tej frazy oraz status HTTP utrwalony przy zapisanych kartach. **Sprawdź HTTP w Chrome** wykonuje osobny pomiar pierwszej odpowiedzi głównego dokumentu i kończy go na nagłówkach. Obie próby mają własną datę. **Uruchom teraz** używa listy fraz źródła pokazanej nad formularzem.

```powershell
$py = '.\.venv\Scripts\python.exe'
& $py -m scamgraph.discovery --config discovery.local.json run --source meta
& $py -m scamgraph.discovery --config discovery.local.json run --source meta --phrase 'Fraza do sprawdzenia'
& $py -m scamgraph.discovery --config discovery.local.json run
& $py -m scamgraph.discovery --config discovery.local.json status
```

Opcja `--phrase` wybiera frazę na jeden przebieg. Zegar nadal używa fraz zapisanych w konfiguracji. Źródło zachowuje aktywny tryb, widoczny w polu `mode` wyniku. Świeże reklamy pobiera tryb `live`.

W czystym checkout użyj `discovery.json`. Odczyta własne syntetyczne karty Meta i lokalny korpus. Zależności podstawowe instaluje `python -m pip install -r requirements-capture.txt` w środowisku Python 3.12+. Operator może skopiować konfigurację do prywatnego `discovery.local.json`. W tej instalacji plik ten wskazuje lokalny historyczny raport operatora Meta. Konfiguracja domyślna i demonstracja prywatna korzystają z różnych źródeł przykładu. Użyj osobnego `state_dir` dla odrębnych demonstracji, aby listy kandydatów były niezależne.

## Konfiguracja i źródła

Ścieżki w konfiguracji są względne wobec pliku JSON. Dla źródła ustaw `phrases` (1–50 fraz), `country`, `limit` (1–100 kart na frazę), `provider`, `adapter` i `mode`. Domyślne zapytanie Meta to dokładna fraza „Ciśnienie spada od razu”, kraj PL i limit dziesięciu wyników. Korpus NASK wyszukuje tę frazę w transkrypcji i oznacza brak filtra kraju. Numer wiersza prowadzi do oryginalnego rekordu, a zrzut ma oddzielną sumę. Brak obrazu lub identyfikatora biblioteki w korpusie zwiększa licznik rekordów z brakami. Dla Meta licznik obejmuje braki nazwy, tekstu kreacji, statusu lub dat emisji.

* **Ręczny import Meta** przyjmuje do 12 MiB zapisanego HTML wyników lub JSON w układzie raportu `wyszukiwania[].wybrane_karty[]`. Podaj frazę i kraj z zapisanego wyszukiwania. Importer sprawdza dostępne metadane zapytania. Zachowuje osobne pliki dla fraz i krajów, a kolejne przebiegi obejmują zaimportowane frazy aktywnego kraju. **Przywróć ustawienia źródła z konfiguracji** przełącza źródło z powrotem. Prześlij HTML jako plik lub wskaż w konfiguracji kompletny zapis lokalny z katalogiem zasobów obok HTML, aby dołączyć dostępne media karty. Pole `imports` mapuje frazy na pliki dla skonfigurowanego kraju. W `path` można wskazać cały raport albo HTML zawierający adres pierwotnego zapytania.
* **Meta live** używa publicznej strony wyników w świeżym kontekście lokalnej przeglądarki. Operator posiadający uprawnienie ustawia `mode: live`, `synthetic: false` i opis udzielonego zakresu w `permission`. Konfiguracja zapytań i interwału musi mieścić się w tym zakresie. Zainstaluj lokalnie Chrome i opcjonalny pakiet `playwright` w tym samym środowisku Pythona. Wariant z Chromium dostarczanym przez Playwright używa `channel: null`. Adapter archiwizuje odczyt wyrenderowanych elementów oraz zrzut karty, gdy można zweryfikować jej granice i ID. Odczyt wykonuje do trzech przewinięć. Chrome pobiera dokument i zasoby bezpośrednio. Adapter sprawdza adresy i zatrzymuje przekierowania przed otwarciem celu. Limit nawigacji wynosi 14 s, a budżet całej fazy odczytu 24 s. Przy karcie zapisuje status HTTP dokumentu. Dla błędnej odpowiedzi lub nierozpoznanej treści próbuje zapisać zrzut widoku w prywatnym archiwum źródła. Blokada, logowanie, przekierowanie i nierozpoznany układ prowadzą do błędu. Jawny komunikat o zerze wyników jest udanym pustym przebiegiem.
* **Nowy dostawca** udostępnia importowalną funkcję `fetch(options, query)` zwracającą obiekty `Finding`. Rekord zawiera ID emisji, kartę, powód, stan braków, oryginalny plik i lokalizator. Wpisz `pakiet.modul:fetch` w polu `adapter` nowego źródła. Funkcja działa w procesie z własnym limitem czasu. Zgłoś `SourceError` z bezpiecznym opisem błędu. Dla przyszłego adaptera TikTok zakres dostępu, zapytania, mapowanie pól i ograniczenia dokumentuje [projekt Commercial Content API](SCHEDULER.md).

## Czas, trwałość i dowody

Sekcja **Odczyt stron docelowych** pozwala wybrać wyszukiwanie według przebiegu i frazy. Tabela podaje liczbę kart, ustalonych celów i użytecznych zapisów. Przy każdej emisji pokazuje typ celu, dostępność treści, stan wizyty, liczbę ostrzeżeń, wykryty dialog cookies i rozpoznaną treść oferty. Oznaczenie jednolitego środka zrzutu opisuje piksele w wybranym obszarze. W szczegółach można obejrzeć zrzut, otworzyć dowód lub pobrać zapisany plik celu.

**Cel do potwierdzenia** pokazuje zapisane odnośniki, które wymagają oceny analityka. Wybierz cel, zaznacz **Pokaż odnośnik na karcie**, aby odczytać dowód przy wyborze, i dodaj cel do kolejki. Zlecenie zachowuje pierwotną obserwację oraz osobny pakiet uzupełnienia. CLI w polu `landing` podaje liczbę wszystkich kart w przebiegu live oraz rozkład `content` i `by_type`. W panelu kolumny **Treść celu**, **Wizyta** i **Ostrzeżenia zapisu** pokazują odrębne wyniki.

**Próg odbioru zespołu.** W świeżej próbie uwzględnij WWW, posty, Marketplace, wideo Facebooka i bezpośrednie pliki. Przed oceną scrapera potwierdź właściwy cel i publiczną dostępność w oddzielnej sesji bez logowania. Następnie porównaj zapis z treścią przypisaną do karty. Wynik to liczba trafnie zapisanych użytecznych treści podzielona przez liczbę potwierdzonych dostępnych celów. Warunek odbioru to co najmniej 90%. Zapisuj osobno liczebność całej próby, wynik według typu, odmowy i błędne przypisania. Zapisane karty „dieta” służą do regresji rozpoznawania odnośników i dokumentów WWW. [Kryteria testowania NASK, pkt 6](NASK_ZADANIE.md)

Zapisany przebieg można przeliczyć bez dostępu do sieci. Polecenie poniżej wykonaj w katalogu worktree z identyfikatorem przebiegu wybranym z historii. Zachowuje oryginalne pakiety, czasy pozyskania i liczniki wyszukiwania. Po przeliczeniu całej grupy panel otwiera nowe wersje analizy. Ponowienie z tą samą wersją ekstraktora zachowuje wynik.

```powershell
& $py -m scamgraph.discovery --config discovery.local.json reanalyze --run-id <ID_przebiegu> --phrase 'Dieta'
```

**Podgląd Chrome podczas odczytu Meta.** W `sources.meta` pliku `discovery.local.json` ustaw `"headless": false`. Chrome otwiera okno w sesji pulpitu, w której działa proces, i zamyka je po zakończeniu odczytu frazy. Domyślnie `headless` ma wartość `true`. Przy ustawianiu `"mode": "live"` wpisz w `permission` zakres faktycznie udzielonej zgody. Panel i zegar wczytują konfigurację ponownie; ustawienie dotyczy również kolejnych przebiegów cyklicznych. Jeśli wcześniej wybrano ręczny import, użyj przycisku **Przywróć ustawienia źródła z konfiguracji**. Aby obejrzeć demonstrację na danych syntetycznych, w poleceniach testowych poniżej użyj `$env:SCAMGRAPH_TEST_CHROME = 'headed'` oraz `& $py -m unittest discover -s tests -p test_meta_discovery.py -v`.

`serve` prowadzi zegar i panel, a `timer` pozwala uruchomić osobny proces zegara. Pierwszy termin nowego źródła wypada po `interval_seconds` (domyślnie 1800 s). Każdy ukończony przebieg przesuwa termin danego źródła o interwał. Zaległy termin po restarcie powoduje jeden przebieg. Rezerwacja jest wspólna dla GUI, CLI i zegara. Przerwany proces traci rezerwację najpóźniej po `timeout_seconds` (domyślnie 180 s). Każda zapisana karta jest od razu widoczna, także gdy później wystąpi błąd. Atomowe przesłanie wskaźnika pakietu do bazy odbywa się po zapisie plików. Limit czasu i ostatni sukces są osobne dla każdego źródła.

Prywatny katalog `.private-discovery` zawiera bazę SQLite, ręczne importy, archiwum odczytu i `captures/<capture_id>/`. Po otwarciu kandydata **Otwórz oryginalny zapis źródła** odczytuje zabezpieczony sumą fragment HTML, wiersz JSONL lub wskazany element raportu JSON. Widok rozróżnia czas wykrycia i datę zapisu źródłowego. Użyj pełnego HTML/HAR wyłącznie w prywatnym katalogu. Eksport z panelu udostępnia wynik analizy.

## Próby odbiorowe

Testy używają syntetycznych kart, dwóch niezależnych połączeń z bazą i rzeczywistych procesów Windows. Obejmują m.in. jednoczesny timer i kliknięcie, porzuconą rezerwację, zmianę układu, powtórne wyszukanie i restart zegara z interwałem dwóch sekund. Dwie zmienne środowiskowe włączają dodatkowo próbkę offline z pierwotnego katalogu i test generowania kart przez JavaScript w lokalnym Chrome. W tym worktree opcjonalny Playwright jest zainstalowany prywatnie.

```powershell
$env:SCAMGRAPH_STRUCT_FIXTURE = '.\data\struct'
$env:SCAMGRAPH_TEST_CHROME = '1'
& $py -m unittest discover -s tests -v
```

Proces pobierający Meta używa Playwright z aktywnego środowiska Pythona. Jeśli pakiet jest dostępny tylko w lokalnym katalogu `.private-discovery/playwright-runtime` tego worktree, proces dołącza go przy uruchomieniu odczytu live. Przycisk panelu i zegar korzystają z tego samego adaptera.

Wyszukiwanie i pakiety realizują rozszerzenie dotyczące nowych źródeł oraz udostępniają sprawdzalne dane dla wymagań ekstrakcji i GUI. Liczniki są kryterium odbioru zespołu. [Zadanie NASK, pkt 3–6 i zasady wykorzystania danych w pkt 8](NASK_ZADANIE.md)
