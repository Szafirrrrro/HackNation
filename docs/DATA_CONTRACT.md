# Kontrakt danych MVP

Kontrakt v0 określa wspólny format importu, silnika i interfejsu. Przykład poniżej jest syntetyczny. Sekcja „Lokalny korpus NASK” opisuje zastosowanie tych samych pól do rzeczywistych zrzutów reklam.

## Korpus wejściowy

Katalog korpusu zawiera `manifest.json`, `ads.jsonl` i opcjonalny podkatalog `media/`. Manifest zawiera `schema_version`, `dataset_id`, `source_description` i `collected_at`. W opisie źródła zapisz metodę pozyskania, zapytanie i filtry, jeśli występują, oraz warunki użycia lub wskazanie ich źródła. `ads.jsonl` zawiera jeden rekord `Ad` w każdym wierszu.

| Pole `Ad` | Wymagalność i znaczenie |
| --- | --- |
| `ad_id` | Wymagane. Stabilny wewnętrzny identyfikator w obrębie korpusu. |
| `source.kind`, `source.provider` | Wymagane. Rodzaj pochodzenia `library`, `organizer`, `synthetic` albo `upload` oraz nazwa źródła w ramach tego rodzaju. |
| `source.ad_ref`, `source.record_url` | Opcjonalny identyfikator reklamy u dostawcy i URL wpisu w bibliotece. `ad_ref` ma zakres danego dostawcy. `record_url` wskazuje stronę źródłową, a `landing_url` cel reklamy. |
| `source.collected_at` | Wymagane. Czas pozyskania z oznaczeniem strefy. Dla pliku od użytkownika zapisuje się moment dodania. |
| `text`, `image_path`, `landing_url` | Co najmniej jedno użyteczne pole w imporcie. `text` oznacza tekst z rekordu lub podany przez użytkownika. `image_path` jest ścieżką pod `media/` w tym korpusie. `landing_url` jest wartością zaobserwowaną, bez pobierania strony przez analizator. |
| `observed_redirect_urls`, `advertiser_ref` | Opcjonalne. Tylko wartości zapisane w źródle. Zakres `advertiser_ref` określa `source.provider`. |

```json
{
  "ad_id": "sample-001",
  "source": {
    "kind": "synthetic",
    "provider": "local-demo",
    "ad_ref": "example-001",
    "collected_at": "2026-11-21T11:30:00+01:00"
  },
  "text": "Przykładowa treść kreacji demonstracyjnej",
  "image_path": "media/sample-001.png",
  "landing_url": "https://one.example/preview"
}
```

Plik przesłany z formularza jest wejściem do analizy jednej reklamy. Adapter wypełnia `source.kind=upload`, nadaje ID i przekazuje obraz jako zwalidowane dane w pamięci. `image_path` dotyczy zapisanego korpusu. OCR wytwarza osobne pole pochodne z odwołaniem do obrazu. Brakujące wartości są pomijane albo jawnie oznaczane jako niedostępne. Etykiety ewaluacyjne przechowujemy w osobnym pliku mapującym `ad_id` na grupę i poziom pewności, poza wejściem silnika.

## Kontrakt między parami implementacyjnymi

Poniższe obiekty opisują proponowany interfejs Pythona. Istniejące pliki wejściowe pozostają zgodne z v0. Pochodzenie pól może pochodzić z obserwacji dołączonej do rekordu.

| Producent → odbiorca | Obiekt przekazywany | Reguła odbioru |
| --- | --- | --- |
| B1 → A i C | `Ad` i dostępne obserwacje źródłowe | Import zwraca stabilne ID, raport ponownych importów i błędów. Nieczytelny plik nie przerywa importu pozostałych rekordów. |
| A1/A2 i B1/B2 → C1 | `Feature(ad_id, family, field, value, origin_id, method_version)` | Każda cecha prowadzi do oryginalnego pola i metody. OCR trafia też do B2. Dla brakującego pola ekstraktor podaje przyczynę niedostępności. |
| C1 → C2 | `PairAssessment`, `Campaign`, `MatchResult` | Formularz przekazuje zapytanie i odczytuje wynik z niezmiennej wersji indeksu. Każda przesłanka prowadzi do lewej i prawej obserwacji. |

`origin_id` identyfikuje pierwotną obserwację w obrębie reklamy. Importer odczytuje istniejące `observation_group` lub przypisuje pochodzenie na podstawie udokumentowanego pola. Oryginał obrazu, jego kadr, pHash, tekst OCR i tekst przepisany z obrazu dziedziczą ten sam identyfikator. URL odczytany ze zrzutu też dziedziczy jego identyfikator. Adres celu w niezależnym polu z biblioteki może otrzymać odrębny identyfikator. Gdy pochodzenie jest niepewne, silnik wstrzymuje uznanie śladu za niezależny. Dowody użyte razem muszą mieć rozłączne obserwacje po obu stronach pary.

Wejście z nowego zbioru może mieć inne identyfikatory, niepełne dane i inne formaty. Adapter dokumentuje mapowanie do `Ad`, zachowuje dostępną oryginalną wartość i raportuje pominięte elementy. Ponowny import tego samego ID u tego samego dostawcy jest idempotentny. Przy braku ID dostawcy importer wykorzystuje dokładny odcisk stabilnych pól. Osobne ID emisji mają pierwszeństwo przed identycznym odciskiem zasobu. Część z etykietami pozostaje poza adapterem i indeksem referencyjnym.

## Lokalny korpus NASK

Katalog [nask-hacknation-2026](../data/nask-hacknation-2026/) jest gotowym wejściem v0. Poniższy przykład w Pythonie działa z katalogu głównego projektu. Wczytuje rekordy i sprawdza ich obrazy względem sum SHA-256 zapisanych dla oryginalnych plików organizatora.

```python
import hashlib
import json
from pathlib import Path

root = Path("data/nask-hacknation-2026")
def records(name):
    return [json.loads(line) for line in (root / name).read_text(encoding="utf-8").splitlines()]

ads = records("ads.jsonl")
origins = {row["ad_id"]: row for row in records("observations/screenshots.jsonl")}
for ad in ads:
    image = (root / ad["image_path"]).read_bytes()
    assert hashlib.sha256(image).hexdigest() == origins[ad["ad_id"]]["sha256"]
print(len(ads))  # 13
```

| Plik | Zawartość i sposób użycia |
| --- | --- |
| [manifest.json](../data/nask-hacknation-2026/manifest.json) | Wersja, identyfikator zbioru, czas zebrania lokalnej kopii do korpusu w UTC, źródła, ich sumy SHA-256 i wskazanie regulaminu. Ten sam czas jest w `source.collected_at` rekordów reklam. Czasy archiwizacji stron w październiku są zapisane przy obserwacjach. |
| [ads.jsonl](../data/nask-hacknation-2026/ads.jsonl) i [media/](../data/nask-hacknation-2026/media/) | 13 rekordów i 13 oryginalnych PNG. `ad_id` zawiera pierwsze 16 znaków SHA-256 obrazu, `source.kind` ma wartość `organizer`. W trzech rekordach `source.ad_ref` przechowuje ID odczytane z karty Meta. `text` to ręcznie przepisany fragment kreacji. |
| [observations/screenshots.jsonl](../data/nask-hacknation-2026/observations/screenshots.jsonl) | Połącz z reklamami przez `ad_id`. Każdy wiersz zawiera ścieżki w archiwum, pełny SHA-256, wymiary, rodzaj zrzutu i wyświetlaną nazwę profilu. `observation_group` obejmuje obraz i przepisany z niego tekst. Identyczna kopia z `p2` jest drugą ścieżką źródłową zrzutu z `p1`. |
| [observations/pages.jsonl](../data/nask-hacknation-2026/observations/pages.jsonl) | 14 różnych zapisanych stron i dodatkowa obserwacja błędu HTTP 502 w `p1`. `capture_id` identyfikuje zapis, `bundle_ids` jego podkatalogi w ZIP-ie. `html` zawiera tytuł, do czterech różnych nagłówków i fragment treści. `document` przechowuje adres bez zapytania i fragmentu, nazwy parametrów oraz wybrane liczbowe identyfikatory śledzące. Pełny źródłowy adres można odtworzyć z pliku pod `archive_paths`. |
| `har`, `dns_tls` i `assets` w zapisie strony | Dla 12 obserwacji `har` podaje m.in. status i czas żądania dokumentu, liczbę wpisów, liczbę żądań do poszczególnych hostów oraz zaobserwowane ID pikseli Meta. Dla błędu 502 zachowano też dane DNS/TLS. `assets[].file` prowadzi do pięciu grafik produktów i jednego zrzutu błędu w [observations/media/](../data/nask-hacknation-2026/observations/media/). Wszystkie ścieżki lokalne są względne wobec katalogu korpusu. |
| [observations/scam-links.txt](../data/nask-hacknation-2026/observations/scam-links.txt) | Wierna kopia odczytanego `scam_links.enc`. Do testu parsera wybierz trzy wiersze zaczynające się od `https://`. Sprawdź wspólne `gad_source` i różne `gad_campaignid`. |

Powiązanie reklamy z konkretną stroną docelową pozostaje do weryfikacji. Dlatego w `ads.jsonl` pominięto `landing_url` i `observed_redirect_urls`. Przykładowo `p1-http-502` i `p1-saved-page` opisują dwa pobrania tego samego adresu, z innym statusem i czasem. Identyfikatory z parametrów URL pozostają obserwacjami infrastruktury. Punkt 8 zadania ogranicza użycie materiałów przekazanych przez NASK do realizacji wyzwania i zabrania ich publicznego rozpowszechniania. Udostępniany publicznie przykład używa fikcyjnych rekordów. [Interpretacja dowodów z materiałów NASK](NASK_DATA.md#interpretacja-dowodów)

## Wyniki analizy

| Obiekt | Pola i znaczenie |
| --- | --- |
| `Evidence` | `family` (`text`, `visual`, `infrastructure`), `signal`, `strength` (`supporting`, `specific`), `left` i `right` z `ad_id`, `field`, `value` i `origin_id`, opcjonalne `metric` i `metric_value`. Pole `observation_group` pomaga odtworzyć wspólną obserwację cech pochodnych. |
| `PairAssessment` | `left_ad_id`, `right_ad_id`, `tier` (`strong`, `similar`, `none`), `rank_score`, `evidence`, `unavailable_families`, `has_sufficient_coverage` i `reason_codes`. `rank_score` służy do sortowania. Pokrycie jest wystarczające, gdy można porównać co najmniej dwie rodziny oparte na różnych obserwacjach. Zgodność tych obserwacji ocenia `tier`. |
| `Campaign` | `campaign_id`, `member_ad_ids`, `profile` i referencje do `PairAssessment`. Kampania jest hipotezą analityczną obejmującą co najmniej dwie reklamy. Profil przechowuje nazwy śladów, wspierające rekordy i liczbę różnych reklam potwierdzających daną cechę. |
| `MatchResult` | `query_ad_id`, `dataset_id`, `config_version`, `status`, `reason_codes`, `candidates` i `similar_ads`. Każdy kandydat wskazuje `campaign_id` i odpowiadające porównania par. `similar_ads` zawiera porównania z pojedynczymi reklamami spoza kampanii o statusie `strong` albo `similar`. |

Status `MatchResult` ustala się według poniższej kolejności. Obowiązuje pierwsza pasująca reguła.

- `probable_match` — dokładnie jedna grupa spełnia regułę dopasowania, również gdy są inne, częściowe sugestie.
- `review_needed` — kilka grup spełnia regułę albo jest co najmniej jedna częściowa sugestia z grupy lub z `similar_ads`.
- `insufficient_evidence` — brak kandydatów i żadna porównana para nie miała wystarczającego pokrycia.
- `no_match` — brak kandydatów i co najmniej jedna para miała wystarczające pokrycie. UI opisuje nowy materiał jako możliwy nowy wzorzec do weryfikacji. Tworzenie grupy wymaga co najmniej dwóch powiązanych emisji.

Każdy wyświetlony dowód musi wskazywać pola obu reklam. Kartę pełnego dopasowania pokazujemy przed częściowymi sugestiami. W ramach tej samej kategorii kolejność wyznacza najwyższa ocena pary w danej grupie, z rozstrzyganiem remisów według `campaign_id`. Reguła przypisania nadal uwzględnia wszystkich członków grupy.
