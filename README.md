# ScamGraph

ScamGraph ma pomóc analitykowi NASK odpowiedzieć na pytanie „Czy tę reklamę widzieliśmy już w innej odsłonie?”. Analityk wczyta zbiór postów, zobaczy proponowane kampanie na grafie, wybierze grupę i prześledzi jej historię na osi czasu. Po dodaniu nowego materiału będzie mógł otworzyć dwa porównywane źródła i ocenić podstawę przypisania.

## Wyszukiwanie reklam i panel znalezisk

W trybie live ScamGraph odczytuje publiczną Bibliotekę reklam Meta przez Chrome i Playwright, bez API i tokenu Meta. Panel i PowerShell uruchamiają ten sam adapter. Działający scheduler domyślnie powtarza wyszukiwanie co 30 minut. System obsługuje również import lokalnego korpusu NASK.

Aby wykonać jeden przebieg odpowiadający przyciskowi **Uruchom teraz**, otwórz PowerShell w katalogu projektu. Dla przygotowanego lokalnie profilu z limitem 40 kart na frazę użyj poniższej komendy. Na nowej instalacji podaj zamiast niego własny profil `discovery.local.json` przygotowany według instrukcji poniżej.

```powershell
.\.venv\Scripts\python.exe -m scamgraph.live --config .private-discovery/browser-40.json run --source meta
```

Domyślny profil live zapisuje pakiety reklam w `.private-discovery/browser-live/captures/`, a pliki z wizyt na stronach docelowych w `.private-discovery/browser-live/pages/`. Instrukcja pokazuje, jak uruchomić demo lub tryb live i przejść od reklamy w panelu do jej HTML-a, zrzutu ekranu i pliku HAR. [Instrukcja obsługi panelu reklam](docs/PANEL_REKLAM.md)

## Od pliku do wyniku

Streamlit przyjmuje też link do strony: `python -m pip install -r graph/requirements-app.txt`,
następnie `python -m streamlit run graph/app.py`. Wklej publiczny URL i kliknij
**Przechwyć stronę**, aby pobrać stronę i automatycznie wczytać jej dane do analizy oraz grafu. Ręcznie podany URL jest pobierany niezależnie od rankingu popularności domen. Ranking nie potwierdza bezpieczeństwa treści. Wymagany jest Google Chrome. [Zapis URL i pliki wynikowe](graph/README.md#przechwycenie-strony-przez-url)

Wybierz w panelu demo syntetyczne, korpus organizatora lub własne źródło lokalne. Prześlij zdjęcie PNG/JPEG/WebP albo podaj URL. Karta wyniku pokazuje decyzję względem wybranej referencji, braki i dowody. SHA-256 rozpoznaje kopię pliku, pHash porównuje wygląd, a lokalny OCR udostępnia tekst. [Obsługa zdjęć i lokalizowanie dowodów](graph/README.md#analiza-zdjęcia-lub-zrzutu-reklamy)

### Uruchomienie na CPU w Dockerze

W katalogu projektu zbuduj obraz dla Linux amd64 i uruchom panel. Budowa pobiera biblioteki, Google Chrome i Tesseract z językami polskim i angielskim. Wbudowane demo i pomiar działają lokalnie po zbudowaniu obrazu.

```powershell
docker build -f graph/Dockerfile -t scamgraph-analyst .
docker run --rm -p 127.0.0.1:8501:8501 -v scamgraph-state:/opt/scamgraph/.private-discovery scamgraph-analyst
```

Otwórz `http://127.0.0.1:8501/`. Aby odczytać własny katalog, dodaj przed nazwą obrazu opcję `--mount "type=bind,source=C:\dane\korpus,target=/korpus,readonly"`, wybierz „Korpus lokalny” i podaj `/korpus`. Do pomiaru na danych syntetycznych służy `docker run --rm --network none scamgraph-analyst python scripts/evaluate_campaigns.py`. [Metodyka i wyniki](graph/eval/README.md) · [Komponenty i licencje](docs/KOMPONENTY.md)

Z katalogu projektu uruchom `python -m scamgraph.live --config discovery.demo.json serve`, aby otworzyć panel schedulera z lokalnymi kartami demonstracyjnymi. Domyślny profil `discovery.live.json` uruchamia Chrome przez Playwright i wyszukuje do 40 kart na frazę. Aby zachować opis uprawnienia lokalnie, skopiuj profil do `discovery.local.json`, uzupełnij `sources.meta.permission` i uruchom `python -m scamgraph.live --config discovery.local.json serve`. Panel otworzysz pod adresem http://127.0.0.1:8527/. Listą zaufanych domen dla wybranego profilu zarządza polecenie `trusted-domains`. [Instalacja i konfiguracja](docs/AD_DISCOVERY.md)

| Krok | Technologia i wynik | Wymaganie NASK |
| --- | --- | --- |
| 1. Wczytaj materiały | Panel przyjmuje katalog, manifest, emisje, obserwacje stron lub karty JSONL. Nowe zgłoszenie może zawierać zdjęcie PNG/JPEG/WebP, tekst i znany adres celu. Pobranie URL zapisuje HTML i HAR. Raport importu pokazuje błędy i duplikaty. SHA-256 rozpoznaje kopie pliku, a ID dostawcy rozróżnia emisje. | Import, deduplikacja, obsługa niepełnych danych |
| 2. Znajdź podobne kreacje | Pillow i pHash porównują wygląd całego obrazu. ORB pozostaje metodą laboratoryjną. Tesseract odczytuje polski i angielski tekst, a znakowy TF-IDF w scikit-learn porównuje jego fragmenty. Analityk zobaczy oba kadry lub wspólną frazę. | Automatyczna ekstrakcja cech i rozpoznawanie wariantów |
| 3. Porównaj strony | Python odczytuje hosty i ścieżki z adresów, nagłówki z zapisanych stron oraz piksele śledzące z logów HAR. Udokumentowane połączenie reklama–strona pozwala wykorzystać znalezisko przy ocenie postu. | Różnorodne ślady i możliwość wskazania źródła |
| 4. Zbuduj grupy | Silnik ocenia pary postów. Przy scalaniu dwóch grup każda para między grupami musi mieć mocne powiązanie (*complete-link*). Pojedynczy post może pozostać poza grupą. | Korelacja i klastrowanie materiałów |
| 5. Sprawdź nową reklamę | Nowy post jest porównywany z zamrożonym zbiorem odniesienia. Wynik obejmuje proponowaną kampanię, sugestie do przeglądu, niewystarczające dane albo możliwy nowy wzorzec. | Rozpoznawanie wariantów znanych i odrębnych kampanii |
| 6. Otwórz dowód | W Streamlit graf pyvis pokazuje posty i grupy. Wybór pary otwiera jej dowody, a wykres Plotly pokazuje zdarzenia wybranej kampanii. | Proste GUI, czytelna prezentacja i interpretacja |

Za korelację i grupowanie jury przyznaje 30% oceny, a za użyteczność cech i źródeł kolejne 30%. Graf i oś czasu to wybrane przez zespół sposoby prezentacji. [Pełna treść zadania NASK](docs/NASK_ZADANIE.md) · [Zakres i kryteria odbioru](docs/MVP.md)

## Pierwszy kwadrans w projekcie

**1. Sprawdź lokalną kopię.** W prywatnej kopii repozytorium otwórz PowerShell w katalogu zawierającym ten README. Ćwiczenie korzysta z wbudowanych poleceń i działa offline.

```powershell
$korpus = 'data/nask-hacknation-2026'
$reklamy = @(Get-Content -Encoding utf8 (Join-Path $korpus 'ads.jsonl') | ForEach-Object { ConvertFrom-Json $_ })
$zrzuty = Get-Content -Encoding utf8 (Join-Path $korpus 'observations/screenshots.jsonl') | ForEach-Object { ConvertFrom-Json $_ }
$sumy = @{}
foreach ($zrzut in $zrzuty) { $sumy[$zrzut.ad_id] = $zrzut.sha256 }
$zgodne = @($reklamy | Where-Object {
    $plik = Join-Path $korpus $_.image_path
    (Get-FileHash -LiteralPath $plik -Algorithm SHA256 -ErrorAction Stop).Hash -eq $sumy[$_.ad_id]
})
"SHA-256: $($zgodne.Count)/$($reklamy.Count)"
```

Oczekiwany wynik dla tej wersji to **`SHA-256: 13/13`**. Inny wynik oznacza, że warto sprawdzić pliki mediów oraz zgodność rekordów z manifestem, zanim zacznie się porównywać metody. [Manifest korpusu](data/nask-hacknation-2026/manifest.json)

**2. Rozróżnij plik, emisję i kampanię.** Otwórz karty p3 i p4. Mają różne ID Biblioteki reklam, ale pokazują ten sam krajobraz i napis. To dwie **emisje** podobnej **kreacji**. Identyczny plik w p1 i p2 można rozpoznać po sumie SHA-256. **Kampania** jest szerszą hipotezą o wspólnym działaniu, która wymaga dodatkowych przesłanek. [Karta p3](data/nask-hacknation-2026/media/p3-123146.png) · [Karta p4](data/nask-hacknation-2026/media/p4-123420.png)

**3. Odszukaj drugi rodzaj dowodu.** W zapisach stron p1 i p7 powtarzają się tytuł, nagłówki i identyfikator Meta Pixel mimo różnych hostów. Strona p15 zachowuje tytuł, a ma inny piksel. To przykład podobnego szablonu i różnego śladu infrastrukturalnego. W 13 rekordach reklam brak potwierdzonych adresów celu. Przy obecnych danych można więc pokazać te zależności między stronami, a związek z konkretnym postem pozostaje otwarty. [Przewodnik z przykładami](docs/NASK_DATA.md)

## Gdzie zacząć pracę

| Twoja rola | Pierwsza lektura | Pierwszy wynik do przekazania |
| --- | --- | --- |
| A · dane i źródła | [Korpus NASK](docs/NASK_DATA.md) i [kontrakt danych](docs/DATA_CONTRACT.md) | Dwie emisje i zapis strony z identyfikatorami źródeł |
| B · ekstrakcja i pomiar | [Laboratorium modeli i testy](models/README.md) | Porównanie dwóch kadrów z miarą i informacją o pochodzeniu |
| C · korelacja | [Kontrakt i reguła decyzji](docs/DATA_CONTRACT.md) | Ocena pary odtwarzalna z obu źródeł |
| C · demonstrator | [Scenariusz grafu i osi czasu](docs/PLAN_GRAF_I_OS_CZASU.md) | Pierwszy wynik obliczony po przesłaniu materiału przez formularz |

Kolejność integracji i testy każdej warstwy opisuje [instrukcja budowy](docs/INSTRUKCJA_BUDOWY.md). Przed zmianami przeczytaj [zasady pracy i przeglądu](AGENTS.md). Korpus i jego historię udostępniamy wyłącznie zespołowi i uprawnionym oceniającym. Na publiczny pokaz przygotowujemy własne dane syntetyczne. [Zasady danych w pkt 8 zadania](docs/NASK_ZADANIE.md) · [Regulamin NASK](docs/NASK_REGULAMIN.md)
