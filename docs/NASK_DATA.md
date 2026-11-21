# Dane NASK w ScamGraph

Do pracy z korpusem użyj plików w repozytorium. Archiwa organizatora są potrzebne do sprawdzenia pochodzenia lub ponownego pozyskania materiałów. [Korpus NASK](../data/nask-hacknation-2026/) · [Kontrakt v0 i przykład odczytu](DATA_CONTRACT.md#lokalny-korpus-nask)

## Wybór materiału

| Zadanie | Plik | Co potwierdza materiał |
| --- | --- | --- |
| Porównanie reklam | [ads.jsonl](../data/nask-hacknation-2026/ads.jsonl) i obrazy z `image_path` | 13 różnych zrzutów. Tekst każdego rekordu przepisano z jego obrazu. Trzy karty Biblioteki reklam Meta mają odczytany identyfikator w `source.ad_ref`. |
| Sprawdzenie emisji lub duplikatu | [screenshots.jsonl](../data/nask-hacknation-2026/observations/screenshots.jsonl) | Połączenie przez `ad_id` prowadzi do oryginalnych ścieżek i SHA-256. Zrzut z `p2` jest identyczny z kopią w `p1`. Karty z `p3` i `p4` mają tę samą treść i różne ID biblioteki. |
| Analiza stron i infrastruktury | [pages.jsonl](../data/nask-hacknation-2026/observations/pages.jsonl) | 15 obserwacji, w tym 12 z danymi HAR. Przy zapisie są tytuł, nagłówki, adres dokumentu bez parametrów i dostępne ślady sieciowe. Grafiki produktu i zrzut błędu są w `observations/media/`. |
| Test parsera parametrów URL | [scam-links.txt](../data/nask-hacknation-2026/observations/scam-links.txt) | Trzy adresy z osobnego katalogu NASK mają wspólne `gad_source` i różne `gad_campaignid`. Adresy przetwarzamy lokalnie jako tekst. |

## Interpretacja dowodów

`p1`–`p15` identyfikują podkatalogi archiwum. Wspólny podkatalog pozwala odnaleźć materiały do porównania. Przypisanie adresu docelowego reklamie wymaga potwierdzenia związku. Dlatego rekordy `Ad` mają pominięte `landing_url`, a etykiety kampanii pozostają nieustalone. Obraz i tekst odczytany z niego należą do jednej `observation_group`.

- **Podobieństwo kreacji.** Na kartach z `p3` i `p4` widać „Exclusive Silver Group”, ten sam krajobraz i napis „Temat, o którym mówi cała Polska”. ID biblioteki to odpowiednio `2180909792525319` i `4100374890267408`. Karta z `p3` pokazuje `AMAZON.COM`, podczas gdy HTML i HAR w tym katalogu wskazują inny host.
- **Wspólny piksel.** W HAR z `p1`, `p2`, `p3`, `p4` i `p7` powtarza się Meta Pixel `4567646436826205`. Ścieżka `/signals/config/4567646436826205` i parametr `id` żądania `/tr/` opisują tę samą integrację. Zapisy z `p1` i `p2` są duplikatami. Żaden z 13 źródłowych HAR nie zawiera niepustego `response.redirectURL` ani nagłówka odpowiedzi `Location`.
- **Dwa pobrania tej samej strony.** W `p1-http-502` główny dokument zwrócił 502. Z tego pobrania pochodzą metadane DNS/TLS oraz zrzut błędu. Późniejszy `p1-saved-page` dokumentuje odpowiedź 200 i artykuł o Brzosce. Porównuj `har.document_started_at` i `har.document_status`.
- **Zasoby strony.** W `p10` plik `Kardivix.html` odwołuje się do zdjęcia opakowania `Kardivix_files/product.png`. W tym samym katalogu reklamę pokazuje osobny plik `Zrzut ekranu 2026-10-08 131631.png`. Podobnie `p9/Cactus Recipe.html` dotyczy słuchu, a osadzony odtwarzacz należy do strony docelowej.

## Weryfikacja źródeł

[Manifest](../data/nask-hacknation-2026/manifest.json) podaje oficjalne adresy obu plików i ich sumy SHA-256. Poniższe polecenia uruchom w katalogu z pobranymi oryginałami. Do sprawdzenia korpusu już w repozytorium wystarczy [przykład w Pythonie](DATA_CONTRACT.md#lokalny-korpus-nask).

**Archiwum ZIP.** Pełny `___BACKUP.zip` ma 73 279 150 bajtów i 436 plików WinZip AES-256. Hasło `WSTAWAJSAMURAJU` powstaje przez odbicie każdego znaku w pionie z zachowaniem kolejności wierszy. Położenie kropki w polu klucza wskazuje lewą lub prawą literę. [Lusterko NASK](https://science.nask.pl/hacknation/lusterko) · [Klucz](https://science.nask.pl/hacknation/media/czekoladka.png) · [Obraz hasła](https://science.nask.pl/hacknation/media/_haslo.png)

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath ___BACKUP.zip
tar.exe --passphrase WSTAWAJSAMURAJU -xOf ___BACKUP.zip BACKUP/p1/archive_dorquesio.click_20261008_090940/archive_info.json
$har = tar.exe --passphrase WSTAWAJSAMURAJU -xOf ___BACKUP.zip BACKUP/p10/move-fitlum.top.har | Out-String | ConvertFrom-Json
$har.log.entries.Count
```

Oczekiwany wynik pierwszego odczytu to JSON z tytułem zawierającym `502: Bad gateway`. Drugi odczyt daje 26 wpisów HAR. Ich pełne sumy SHA-256 zawierają odpowiednio pola `archive_info.sha256` obserwacji `p1-http-502` i `har.sha256` obserwacji `p10-saved-page`.

**Katalog adresów.** Kod `93JNG` z filmu w stopce otwiera `scam_links.enc` po zapisaniu małymi literami. OpenSSL odtwarza 731-bajtowy plik tekstowy, którego sumę zawiera `sources[].decoded_sha256` w manifeście. [Strona zagadki NASK](https://science.nask.pl/hacknation)

```sh
openssl enc -d -aes-256-cbc -pbkdf2 -iter 10000 -md sha256 -a -in scam_links.enc -out decoded-catalog.txt -pass pass:93jng
```
