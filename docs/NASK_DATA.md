# Korpus NASK. Co można sprawdzić na materiałach organizatora

Korpus pozwala powtórzyć analizę reklamy i zapisanej strony offline. Najlepsze rzeczywiste przypadki pokazują, jak ten sam przekaz pojawia się w różnych emisjach lub na różnych hostach. Rozstrzygnięcie, czy dwie emisje należą do jednej kampanii, wymaga dodatkowych udokumentowanych powiązań. [Manifest korpusu](../data/nask-hacknation-2026/manifest.json) · [Kontrakt danych i decyzji](DATA_CONTRACT.md)

## Inwentarz

| Materiał | Co jest dostępne | Jak go wykorzystać |
| --- | --- | --- |
| Emisje i kreacje | 13 rekordów `Ad`, 13 różnych PNG i 13 ręcznych transkrypcji fragmentu zrzutu. Trzy karty mają `source.ad_ref` odczytane z Biblioteki reklam Meta. | Sprawdź SHA-256, porównaj kreacje i napisy. Transkrypcja dziedziczy pochodzenie zrzutu. [Rekordy emisji](../data/nask-hacknation-2026/ads.jsonl) · [Opisy zrzutów](../data/nask-hacknation-2026/observations/screenshots.jsonl) |
| Obserwacje stron | 15 zapisów, w tym dwa pobrania tego samego URL w `p1`. Dostępne pola obejmują tytuł, nagłówki, fragment treści, adres dokumentu bez zapytania i nazwy parametrów. Dla części zapisów zachowano wybrane liczbowe identyfikatory parametrów. | Zaimportuj jako samodzielne `PageCapture`. Łącz źródła w obrębie pobrania przez `capture_id`. [Zapisy stron](../data/nask-hacknation-2026/observations/pages.jsonl) |
| HAR i multimedia stron | 12 zapisów zawiera podsumowania HAR. Wskazują 13 ścieżek w archiwum, gdyż jeden HAR występuje w dwóch katalogach. Zarejestrowane listy przekierowań są puste. Osobno zachowano 5 grafik produktów i 1 zrzut błędu HTTP. | Sprawdź `document_status`, `document_started_at`, `meta_pixel_ids` oraz `assets[].kind`. Grafika opakowania produktu pochodzi ze strony. Plik kreacji wskazuje `Ad.image_path`. [Zasoby stron](../data/nask-hacknation-2026/observations/media/) |
| Katalog adresów | Trzy adresy z osobnego źródła mają tę samą wartość `gad_source` i trzy różne `gad_campaignid`. | Użyj jako testu lokalnego parsera i przykładu popularnego parametru. Oryginalne adresy pozostają tekstem. [Katalog źródłowy](../data/nask-hacknation-2026/observations/scam-links.txt) |

**Pokrycie.** W rekordach emisji liczba potwierdzonych `landing_url`, udokumentowanych związków emisja–zapis strony, etykiet kampanii i dat publikacji wynosi po zero. Pole `source.collected_at` oznacza czas utworzenia lokalnej kopii. Czasy żądań zapisane w HAR dotyczą konkretnych pobrań strony. Przy obecnych źródłach 0 z 78 par emisji ma dwie niezależne rodziny wymagane do silnej hipotezy kampanii. To przewidywanie z kontraktu i pokrycia danych. Skuteczność modelu na kampaniach wymaga osobnego pomiaru.

## Przypadki do odtworzenia

| Pytanie analityka | Obserwacja i granica wniosku |
| --- | --- |
| Czy dwie kopie zwiększają liczbę źródeł? | Zrzuty w `p1` i `p2` mają ten sam SHA-256. Wiersz zrzutu zachowuje obie ścieżki archiwalne. Również zapis strony i HAR mają wspólną kopię w tych katalogach. W profilu licz tę obserwację raz. |
| Czy różne emisje powtarzają kreację? | Karty `p3` i `p4` mają różne identyfikatory biblioteki, odpowiednio `2180909792525319` oraz `4100374890267408`. Widać ten sam krajobraz, profil „Exclusive Silver Group” i ten sam napis. Pełne zrzuty mają odległość pHash 16/64. Pokazuj podobieństwo kreacji i odrębne emisje. Przy przypisaniu do kampanii brakuje niezależnego źródła. |
| Jak zawodzi ranking pojedynczej cechy? | Wśród wszystkich 78 par pełnych ekranów najniższa odległość pHash występuje dla `p5/p8` i wynosi 14/64. Przepisane napisy są różne. Z kolei `p1/p7/p15` mają ten sam przepisany tekst, a obrazy `p1/p15` różnią się o 28/64 bitów. To przypadki do porównania pHash pełnego zrzutu, kadru i tekstu. Pomiar kontrolny używa 64-bitowego pHash po zamianie na szarość, skalowaniu Lanczos do 32 × 32 i progowaniu medianą bloku DCT 8 × 8. |
| Co naprawdę wspólnego mają dwa hosty? | Zapisy `p1-saved-page` i `p7-saved-page` mają zgodny tytuł, cztery zgodne nagłówki i ten sam identyfikator piksela Meta w HAR na różnych hostach. Zapis `p15-saved-page` powtarza ten tytuł i nagłówki, a jego HAR ma inny piksel. To porównanie szablonu i integracji trzech stron. Różne piksele pozostawiają otwarte pytanie o operatora i kampanię. |
| Gdzie kończy się dowód infrastrukturalny? | Ten sam piksel pojawia się w czterech różnych zapisach stron `p1/p3/p4/p7`. Kopia z `p2` oraz dwa sposoby zarejestrowania jednego piksela w HAR nie zwiększają liczby integracji. Na karcie reklamowej `p3` widać `AMAZON.COM`, podczas gdy HTML i HAR obok tej karty wskazują inny host. Nazwa katalogu jest tropem do weryfikacji. `AdPageLink` wymaga zapisu, który pozwala potwierdzić przejście z emisji do celu. |
| Co zostaje przy błędzie strony? | W `p1-http-502` pobranie zwróciło 502. Z tego zapisu pochodzą DNS/TLS oraz zrzut błędu. Późniejszy `p1-saved-page` odnotowuje 200 i artykuł. Pokazuj obie obserwacje z czasem i statusem. Dla `p10` rozdziel zrzut reklamy i `assets[].file` prowadzące do zdjęcia opakowania produktu na stronie. |

**Pokaz dla jury.** Na korpusie NASK pokaż dwie emisje z podobną kreacją oraz dwie strony z powtarzającą się integracją. Do zmierzenia trafności przypisań potrzebne są materiały z dozwolonego źródła i niezależne etykiety kampanii. Można ocenić emisje z osobnymi źródłami tekstu i obrazu także przy braku adresu celu. Wykorzystanie cech strony jako dowodu dotyczącego reklamy wymaga udokumentowanego związku emisja–cel. Kontrolowana próbka z własnymi danymi pozwoli sprawdzić przejście od zgłoszenia do decyzji także przy braku rzeczywistych etykiet. Wyniki dla danych rzeczywistych i kontrolowanych opisujemy oddzielnie. [Sposób oceny NASK](NASK_ZADANIE.md)

## Weryfikacja offline i pochodzenie

Zacznij od 13 obrazów i ich sum SHA-256 według [instrukcji w README](../README.md). Do sprawdzenia przykładów tekstowych porównaj `Ad.text`, do sprawdzenia stron odczytaj `html.title`, `html.headings` oraz `har.meta_pixel_ids` dla wymienionych `capture_id`. Pełne ścieżki do oryginałów i ich sumy SHA-256 są w obserwacjach. [Zapisy stron](../data/nask-hacknation-2026/observations/pages.jsonl)

W przypadku dostępu do pobranych wcześniej oryginałów porównaj ich sumy z manifestem. Z archiwum ZIP można wypisać wybrany zapis bez rozpakowywania całego pakietu. Dla pierwszego odczytu oczekiwany jest tytuł z `502: Bad gateway`, dla drugiego 26 wpisów HAR. Poniższe polecenia uruchamia się w PowerShell w katalogu z oryginalnymi plikami.

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath ___BACKUP.zip
Get-FileHash -Algorithm SHA256 -LiteralPath scam_links.enc
tar.exe --passphrase WSTAWAJSAMURAJU -xOf ___BACKUP.zip BACKUP/p1/archive_dorquesio.click_20261008_090940/archive_info.json
$har = tar.exe --passphrase WSTAWAJSAMURAJU -xOf ___BACKUP.zip BACKUP/p10/move-fitlum.top.har | Out-String | ConvertFrom-Json
$har.log.entries.Count
```

Odszyfrowana kopia `observations/scam-links.txt` ma 731 bajtów. Manifest podaje jej `decoded_sha256`. Hasło do ZIP i kod do katalogu wynikają z zagadek organizatora. Sposób odtworzenia opisano w [notatce z zagadek](ZAGADKI_NASK.html). [Manifest i sumy oryginałów](../data/nask-hacknation-2026/manifest.json)

**Warunki użycia.** Punkt 8 zadania ogranicza użycie materiałów NASK do realizacji wyzwania i zabrania ich publicznego rozpowszechniania. Korpus i prywatny pokaz są przeznaczone dla uprawnionych uczestników i jury. Publiczne przykłady należy przygotować z własnych materiałów. [Zasady korzystania z danych](NASK_ZADANIE.md)
