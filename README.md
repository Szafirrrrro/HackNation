# ScamGraph

ScamGraph ma pomóc analitykowi NASK odpowiedzieć na pytanie „Czy tę reklamę widzieliśmy już w innej odsłonie?”. Analityk wczyta zbiór postów, zobaczy proponowane kampanie na grafie, wybierze grupę i prześledzi jej historię na osi czasu. Po dodaniu nowego materiału będzie mógł otworzyć dwa porównywane źródła i ocenić podstawę przypisania.

**Dziś w repozytorium** można zweryfikować prywatny korpus, obejrzeć obserwacje reklam i stron oraz uruchomić testy laboratorium modeli. **Do zbudowania** są importer aplikacji, silnik grupowania, ekran analityka i kontener demonstratora. Laboratorium ma własne kontenery CPU. Wyniki trafności przypisania do rzeczywistych kampanii pozostają do zmierzenia.

## Od pliku do wyniku

| Krok | Technologia i wynik planowanego systemu | Wymaganie NASK |
| --- | --- | --- |
| 1. Wczytaj materiały | Python przyjmuje manifest i rekordy JSONL, obraz PNG/JPEG/WebP, tekst, adres lub zapisany HTML/HAR. Raport podaje przyjęte rekordy, duplikaty i braki. SHA-256 rozpoznaje kopie pliku, a ID dostawcy pozwala zachować dwie emisje tej samej kreacji. | Import, deduplikacja, obsługa niepełnych danych |
| 2. Znajdź podobne kreacje | Pillow i pHash porównują obraz, OpenCV ORB dopasowuje punkty kadru. Tesseract odczytuje polski i angielski tekst, a znakowy TF-IDF w scikit-learn porównuje jego fragmenty. Analityk zobaczy oba kadry lub wspólną frazę. | Automatyczna ekstrakcja cech i rozpoznawanie wariantów |
| 3. Porównaj strony | Python odczytuje hosty i ścieżki z adresów, nagłówki z zapisanych stron oraz piksele śledzące z logów HAR. Udokumentowane połączenie reklama–strona pozwala wykorzystać znalezisko przy ocenie postu. | Różnorodne ślady i możliwość wskazania źródła |
| 4. Zbuduj grupy | Silnik ocenia pary postów. Przy scalaniu dwóch grup każda para między grupami musi mieć mocne powiązanie (*complete-link*). Pojedynczy post może pozostać poza grupą. | Korelacja i klastrowanie materiałów |
| 5. Sprawdź nową reklamę | Nowy post jest porównywany z zamrożonym zbiorem odniesienia. Wynik obejmuje proponowaną kampanię, sugestie do przeglądu, niewystarczające dane albo możliwy nowy wzorzec. | Rozpoznawanie wariantów znanych i odrębnych kampanii |
| 6. Otwórz dowód | W Streamlit graf Cytoscape.js pokazuje posty i grupy, a vis-timeline zdarzenia wybranej kampanii. Kliknięcie połączenia otwiera oba źródła. Kliknięcie zdarzenia wskazuje post na grafie. | Proste GUI, czytelna prezentacja i interpretacja |

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
