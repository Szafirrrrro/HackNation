# Pakiet dowodowy schedulera

Jednostką importu jest jedna obserwacja. Prywatny katalog `data/captures/<capture_id>/` zawiera manifest, oryginały w `ad/`, `landing/` i `network/` oraz wynik `extracted.json`. Import akceptuje pojedynczy plik, zapis strony z katalogiem zasobów lub katalog obserwacji. Identyfikator pakietu uwzględnia źródło i inwentarz. Identyfikator emisji u dostawcy ma osobne pole. Czas importu ma strefę UTC. Czas zebrania źródła, jeżeli nie został przekazany, pozostaje nieustalony.

Manifest wymienia typ, rolę, ścieżkę i SHA-256 każdego pliku źródłowego, sumę wyniku, przyczyny braków i metodę importu. Odnośnik w wyniku wskazuje ścieżkę, wspólny dla pochodnych pliku `origin_id` oraz lokalizację w pliku. Wersja metody jest wspólna dla wyniku, metody medialne dodatkowo podają własną konfigurację. Pola reklamy i strony należą do odrębnych obserwacji. Wspólny import pozostawia listę `ad_page_links` pustą.

Wpis na stronie jest świadectwem treści opublikowanej przez autora strony. Liczniki opisują wartości wyświetlane. Tożsamość piszącego oraz zakup pozostają nieustalone. Brak wartości jest reprezentowany przez `null`. Dopasowanie tekstów między pakietami zachowuje obydwa wystąpienia.

Oryginały są prywatne. Panel wyświetla lokalne dowody w postaci neutralnego tekstu, obrazów i nagrań. Eksport analityczny zawiera wybrane dane z dowodów. Pomija nagłówki i ciała HTTP, wartości formularzy, parametry uwierzytelniające i kod skryptów. HTML, HAR i JS są analizowane bez odpytywania zarejestrowanych hostów.

## Import i odbiór

Z katalogu repozytorium uruchom polecenia w PowerShell z Pythonem 3.12 lub nowszym. Przy pierwszym przygotowaniu środowiska zależności instaluje się z `requirements-capture.txt`. Środowisko tej kopii projektu ma już Pillow i Streamlit.

```powershell
.venv/Scripts/python.exe -m scamgraph data/struct --store data/captures/panel
.venv/Scripts/python.exe -m scamgraph (Get-ChildItem data/struct/*.png).FullName --store data/captures/panel
.venv/Scripts/python.exe -m streamlit run scheduler_panel.py --server.address 127.0.0.1 -- --store data/captures/panel
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

Kliknij pozycję na liście obserwacji, otwórz zakładkę **Sygnały**, wybierz fragment i kliknij **Otwórz lokalny dowód**. Panel sprawdzi sumę pliku i pokaże dowód nad zakładkami. W **Opiniach i odpowiedziach** możesz otworzyć obie strony dopasowania między obserwacjami. Przycisk w zakładce **Materiały** eksportuje `extracted.json`. Katalog oryginałów pozostaje na prywatnym wolumenie.

Jedną kartę Meta można przekazać jako JSON z polami pojedynczego wpisu biblioteki lub odpowiedzią `{"data":[…]}` z jedną emisją. Karta TikToka może zawierać obiekty `ad` i `advertiser`. Zapisany HTML karty przyjmuje opcję `--ad-card`. W katalogu obserwacji można też użyć `ad/karta.html`, `ad/karta.json` i plików mediów. Pliki HTML na poziomie głównym ze znacznikiem kanonicznym biblioteki Meta są rozpoznawane jako karta. Płaski zapis strony z katalogiem `*_files` zachowuje nazwy i ścieżki względne. Jeden import dotyczy jednej emisji. Worker może wywołać `scamgraph.capture.capture` dla każdej zebranej obserwacji. Funkcja zwraca ścieżkę opublikowanego pakietu.

Operator może podać dostawcę przez `--provider` i znany czas pobrania przez `--collected-at` z przesunięciem strefowym. Bez metadanych dostawca ma wartość `unknown`. Manifest rozróżnia znany czas źródłowy `source_observed_at` i czas importu `imported_at`. Pole kontraktowe `collected_at` używa znanego czasu pozyskania, a przy jego braku czasu lokalnego przyjęcia. `observation_id` identyfikuje pochodzenie i bajty, `capture_id` także wynik zastosowanej analizy. Powtórny identyczny import weryfikuje istniejący pakiet. Uzupełnienie transkrypcji tworzy nową wersję tej samej obserwacji. Klucz emisji u dostawcy tworzą `provider` i `ad_ref`. Projekcja `extracted.ad` zawiera pola Ad v0 dla użytecznego materiału, karta wyłącznie katalogowa zachowuje metadane w `ad_fields`.

Ekstrakcja HTML obsługuje elementy semantyczne, klasy komentarzy i opinii, dane strukturalne Review/Comment/Product/Offer oraz lokalne znaczniki wątku. Reguły tekstowe oznaczają fragmenty do weryfikacji przez analityka. Nazwy własne i produkty rozpoznane z tekstu są kandydatami. Kwoty przytaczane w opowieści i ceny oferty mają osobne pola. Nowy szablon może wymagać kolejnego adaptera. Odczyt tekstu z obrazu używa lokalnego OCR Windows lub Tesseract z zainstalowanym językiem polskim lub angielskim. Wynik OCR zachowuje prostokąt i wersję silnika. Opcjonalne ASR wymaga lokalnie zainstalowanych faster-whisper, PyAV i modelu CTranslate2 przekazanego przez `--asr-model`. Brak modelu ma własną przyczynę w analizie.

Decyzja zespołu dla porównania opinii: po normalizacji Unicode, wielkości liter, interpunkcji i odstępów porównujemy każde wystąpienie z wypowiedziami z innych obserwacji. Dokładna zgodność działa dla dowolnej długości. Dla bliskiej kopii wymagamy co najmniej 20 znaków po obu stronach i wyniku `SequenceMatcher.ratio ≥ 0,88`. Progi służą do kierowania wpisów do przeglądu. Prywatny test sprawdza sumy artefaktów, treść pierwszej opinii z HTML i licznik, liczby wpisów i odpowiedzi, źródła oraz zachowanie po usunięciu HTML i HAR z wejścia.
