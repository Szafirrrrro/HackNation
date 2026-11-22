# Baza danych ScamGraph

Scheduler zapisuje stan pracy w SQLite, a karty i raporty na dysku. Opcjonalny PostgreSQL przechowuje historię eksportów i przebiegów. Silnik `ftf_graph` ocenia pary i grupuje kampanie metodą complete-link. Zapytania analityka porównuje z zamrożoną referencją. [Uruchomienie](#uruchomienie) · [Kontrakt silnika](DATA_CONTRACT.md#reguła-silnika-ftf_graph-decyzja-zespołu)

Materiały NASK i wyniki pochodne zostają lokalnie. Baza działa w Dockerze na maszynie zespołu, bez usług chmurowych. [Zasady danych, pkt 8 zadania](NASK_ZADANIE.md)

## Przepływ danych

```
scraper (scamgraph.discovery) ──► [1] wejście: surowe rekordy, pliki po SHA-256
                                       │
                         preprocesor (capture, graph_feed)
                                       ▼
                               [2] encje: emisje, zapisy stron
                                       │
                                       ▼
                               [3] karty: JSON w formacie ftf_graph
                                       │
                         silnik ftf_graph (Scorer, complete-link)
                                       ▼
                               [4] przebiegi: krawędzie, kampanie
                                       │
                                       ▼
                     Neo4j (widok, odbudowywany) + Streamlit
```

Neo4j pokazuje wynik ponownej oceny w obrębie przekazanych materiałów. PostgreSQL przechowuje pełne wyniki każdego zapisanego przebiegu. Media i paczki stron leżą na dysku, a karty zawierają odnośniki i sumy SHA-256.

## Stan obecny: SQLite i pliki scrapera

Każdy profil scrapera ma katalog stanu `state_dir` (np. `.private-discovery/browser-live`). Katalog jest w `.gitignore`.

### `discovery.sqlite3`

| Tabela | Klucz | Co przechowuje |
| --- | --- | --- |
| `schedules` | `source_id` | Interwał, termin następnego przebiegu, ostatni przebieg i ostatni sukces źródła. |
| `runs` | `run_id` | Jeden przebieg źródła: wyzwalacz (`timer`, `cli`, panel), tryb (`live`, `replay`, `import`), czasy, status, fraza, błąd i liczniki `read_count`, `new_count`, `known_count`, `missing_count`. |
| `observations` | `seq` | Jedna odczytana emisja w danym przebiegu: `provider`, `ad_ref`, fraza, kraj, powód znalezienia, karta (`card` jako JSON), `capture_id` pakietu, `observed_at`, `found_at`, lokalizator w oryginale, flaga braków. Indeks `observation_identity(provider, ad_ref, phrase, reason)`. |
| `candidates` | `(provider, ad_ref)` | Wskazanie najnowszej obserwacji emisji (`latest` → `observations.seq`). |
| `reasons` | `(provider, ad_ref, phrase, country, reason)` | Historia powodów, dla których emisja została znaleziona. |
| `page_jobs` | `seq` → `observations.seq` | Kolejka wizyt stron z CTA: pakiet bazowy, status (`queued`, `running`, `success`, `partial`, `failed`, `skipped`, `superseded`), liczba prób, pakiet wynikowy, błąd. |
| `trusted_domains` | `domain` | Zaufane domeny pomijane podczas wizyt. Porównanie bez rozróżniania wielkości liter. |

### Pozostałe pliki stanu

| Ścieżka | Co przechowuje |
| --- | --- |
| `manual-imports.sqlite3` | `active(source, country)` i `files(source, country, phrase, path)`: ręcznie zaimportowane wyniki Biblioteki reklam. |
| `page-worker.sqlite3` | Wyłącznie blokada jednego workera wizyt. Brak danych. |
| `graph/export.sqlite3` | `exports(mode, revision)` przechowuje rewizję projekcji, a `export_times` czas zapisu eksportu. |
| `graph/analysis.sqlite3` | `reports(mode, revision)` przechowuje klucz złożony z odcisku kart i metody. |
| `captures/<capture_id>/` | Pakiet obserwacji: `manifest.json` z sumami SHA-256, `extracted.json`, `ad/card.json`, `landing/`. |
| `pages/<id_pobrania>/` | Paczka wizyty: `page.html`, `page_files/`, zrzuty, `network.har`, `metadata.json`. |
| `archives/<źródło>/` | Materiał źródłowy adaptera, np. zrzuty kart i ekranów błędu. |
| `graph/<tryb>.jsonl` | Karty w formacie `ftf_graph`: ostatnia obserwacja każdej pary dostawca–ID. |
| `graph/<tryb>.campaigns.json` | Kampanie, krawędzie z powodami, `unassigned`, `unavailable`, `feed_sha256`, `engine_fingerprint`, `domain_policy`, `analysis_revision` i `computed_at`. |

Plik raportu pokazuje ostatni ukończony przebieg danego trybu. Historię przebiegów zapisuje PostgreSQL, gdy jest włączony. Cechy laboratorium `models/` są zapisywane w osobnych plikach.

## PostgreSQL

| Potrzeba | Mechanizm |
| --- | --- |
| Idempotentny import | W obrębie `dataset_id` obowiązują unikalne klucze emisji `ad_id` i `(provider, ad_ref)`. Surowe rekordy mają unikalne `payload_sha256`. |
| Historia wyników | Każdy przebieg zapisuje `run_id`, konfigurację, wersję kodu oraz odciski kart i metody. |
| Pochodzenie cech | Karty przechowują `origin_id`, wersję ekstraktora i dostępne lokalizatory źródeł. |

### Schemat v4

| Tabela lub widok | Zawartość |
| --- | --- |
| `raw_record` | Surowa karta obserwacji źródłowej i jej SHA-256. |
| `ad` | Emisja w obrębie trybu, ostatnia obserwacja i wskazanie aktualnej karty lub powód jej braku. |
| `page_capture` | Miejsce na metadane samodzielnego zapisu strony. Scheduler zachowuje je w pakietach na dysku. |
| `card`, `card_current` | Zachowane wersje kart i widok aktualnej karty dla każdej dostępnej emisji. |
| `feed_export` | Rewizja i czas ostatniego eksportu każdego trybu. |
| `engine_run`, `run_result` | Konfiguracja, odciski i wyniki konkretnego przebiegu. |
| `schema_version` | Wersja zainstalowanego schematu. |

Definicje kolumn, kluczy i migracji zawiera [schemat SQL](../db/schema.sql).

`run_result.payload` przechowuje to, co silnik już zwraca:

| `kind` | `payload` |
| --- | --- |
| `edge` | Identyfikatory kart (`a`, `b`), wyniki (`score`, `campaign_score`) i uzasadnienia (`reasons`, `campaign_reasons`). |
| `member` | `{ad_id, campaign, strength}`, gdzie `campaign = null` oznacza reklamę poza kampaniami |
| `campaign` | `{campaign, size, mean_edge_score, first_seen, last_seen, alive, dead, sources, final_domains, persons, shared_artifacts}` |
| `query` | `MatchResult` z kontraktu: status, kampania, krawędzie zapytania, braki karty (jeszcze niezapisywane) |
| `unavailable` | `{ad_id, capture_id, reason}`: reklama pominięta, bo z pakietu nie dało się zbudować karty |

### Rozszerzenia po MVP

| Tabela | Kiedy ją dodać | Zawartość |
| --- | --- | --- |
| `ad_page_link` | Gdy powiązania reklama–strona mają być odpytywane SQL-em, a nie tylko zapisane w karcie | `ad_id`, `capture_id`, `origin_id`, `observed_at`, `source_ref jsonb`, `verified` |
| `feature` | Gdy cechy z `models/` mają trafiać do bazy wiersz po wierszu | Typ i ID obiektu, rodzina, pole, wartość i wartość znormalizowana, `origin_id`, ekstraktor z wersją, parametry; unikalne po `(obiekt, pole, origin_id, ekstraktor)` |
| `embedding` | Przy kNN lub liczeniu przyrostowym | `feature_id`, rodzaj, `vector(n)`, osobny indeks HNSW na rodzaj |
| `pair_assessment`, `campaign`, `campaign_member`, `match_result` | Gdy wyniki mają być filtrowane SQL-em | Rozbicie `run_result` na tabele z kolumnami |
| `eval.labels` | Do pomiaru purity i pairwise F1 | Etykiety kampanii w osobnym schemacie, bez dostępu silnika |

## Mapowanie ze stanu obecnego

| Obecnie | W projekcie |
| --- | --- |
| `observations.card`, oryginał w `captures/<id>/` | `raw_record` (`kind='ad'`) i `ad` |
| `pages/<id_pobrania>/metadata.json` | `raw_record` (`kind='page'`) i `page_capture` |
| `landing/` pakietu + `extracted.json.ad_page_links` | `raw_record` (`kind='link'`), na start pole w karcie |
| `graph/<tryb>.jsonl` | `card` (`adapter_version='graph-feed/5'`) |
| `graph/<tryb>.campaigns.json` | `engine_run` + `run_result` |
| `graph/export.sqlite3`, `graph/analysis.sqlite3` | `feed_export.revision` oraz `engine_run.cards_sha256` i `engine_run.engine_fingerprint` |
| `runs`, `schedules`, `page_jobs`, `trusted_domains` | Zostają w SQLite scrapera: to stan operacyjny zegara, nie dane silnika |

## Integracja z silnikiem

Opcjonalny zapis uruchamia się po publikacji plików. Odbiorca może odczytać najnowsze karty i raport przez `scamgraph.db`.

```python
from scamgraph import db

with db.connect() as conn:
    cards = db.load_cards(conn, "live")
    run = db.latest_run(conn, "live")
```

CLI silnika może zapisać wynik bieżącej analizy do Neo4j. Jedna transakcja wymienia krawędzie podobieństwa między ocenianymi materiałami i ich członkostwa w kampaniach. Wartość `Campaign.id` pochodzi z listy identyfikatorów członków, a `Campaign.campaign` to numer wyświetlany w raporcie. Jeżeli przeliczenie zmieni tylko część wcześniejszej kampanii, `size` podaje aktualną liczbę członków, a `projection_complete` przyjmuje `false`. Ponowny zapis usuwa odłączone węzły kampanii z zakresu aktualizacji. Surowy eksport JSONL pozostaje wejściem do ewaluacji.

Nowe relacje `REDIRECTS_TO` i `COVERS` mają `ad_id` powiązanej emisji. Relacje zapisane przez wcześniejszą wersję bez `ad_id` pozostają w bazie jako historyczny kontekst. Zapytania o aktualny przebieg mogą ograniczyć te relacje do identyfikatorów jego emisji.

## Uruchomienie

```bash
export POSTGRES_PASSWORD='ustaw-własne-długie-hasło'
docker compose -f graph/docker-compose.yml up -d postgres
export DATABASE_URL="$(python -c 'import os; from urllib.parse import quote; print("postgresql://scamgraph:" + quote(os.environ["POSTGRES_PASSWORD"], safe="") + "@127.0.0.1:5432/scamgraph")')"
```

W PowerShell ustaw zmienne przez `$env:POSTGRES_PASSWORD` i `$env:DATABASE_URL`. `POSTGRES_PASSWORD` ustala hasło podczas inicjalizacji nowego woluminu PostgreSQL. Przy istniejącym woluminie użyj aktualnego hasła użytkownika `scamgraph`. Usługi Compose słuchają na `127.0.0.1`. Zależność `psycopg[binary]` jest w `requirements-capture.txt`.

Przy pierwszym połączeniu kod tworzy schemat lub migruje wersję 3 do wersji 4 w transakcji. Migracja dodaje `engine_fingerprint` i odświeża `card_current`, zachowując poprzednie dane. Pole odcisku pozostaje puste w historycznych przebiegach obliczonych przed migracją. [Schemat SQL](../db/schema.sql)

Zapis działa w `scamgraph/discovery/graph_feed.py`, w tych samych miejscach, w których powstają pliki:

| Krok | Pliki | Baza |
| --- | --- | --- |
| `export_graph()` | `graph/<tryb>.jsonl` | `raw_record`, `ad`, `card` w wersji `graph-feed/5` i metadane w `feed_export`. Przy braku karty `ad.unavailable` podaje powód. |
| `update_campaigns()` | `graph/<tryb>.campaigns.json` | `engine_run` i `run_result` z dokładnie tego raportu. |

Pliki powstają również przy braku `DATABASE_URL` lub awarii PostgreSQL. Raport i dane wejściowe trafiają do bazy po zwolnieniu blokad SQLite. Domyślny limit połączenia to 3 s, zapytania 30 s, a blokady 5 s. Ustawienia w URL-u mają pierwszeństwo. Błąd zapisu trafia na stderr oraz do `graph/<tryb>.feed.db-error` lub `graph/<tryb>.run.db-error`. Termin następnego przebiegu pozwala ponowić zapis.

Testy: `TEST_DATABASE_URL=postgresql://... python -m unittest tests.test_db`. Każdy test czyści schemat `public` wskazanej bazy, więc wskazuj pustą bazę testową.

### Tożsamość eksportów i przebiegów

- `dataset_id` = tryb źródła (`live`, `replay`, `import`), a `ad_id` = `provider/ad_ref`, jak w `graph_feed`.
- Unikalność `(provider, ad_ref)` obowiązuje w obrębie `dataset_id`, bo ta sama reklama bywa w kilku trybach.
- `source_kind`: `library` dla trybu `live`, `upload` dla pozostałych. Graph_feed nie zna flagi `synthetic` z konfiguracji źródła.
- `cards_sha256` to SHA-256 pliku JSONL (`feed_sha256` raportu). `engine_fingerprint` uwzględnia kod silnika, wersje istotnych zależności, ustawienia i zawartość plików polityki domenowej, w tym własnej listy `FTF_TRUSTED_DOMAINS`. `code_version` podaje dodatkowo opis rewizji Git, gdy jest dostępny.
- Zmiana odcisku wejścia lub metody powoduje atomową publikację raportu i zapis nowego przebiegu z zachowaniem historii. Powtórka identycznego przebiegu korzysta z istniejącego `run_id`. `latest_run` wybiera rekord według `computed_at` i, przy remisie, `seq`.
- Eksporty porządkuje czas zapisu pliku (`export_times` w `graph/export.sqlite3`). Starszy eksport, który dotrze później, jest pomijany.
- `card_current` to karta z ostatniego eksportu (`ad.card_built_from`). Reklamy niedostępne przy tym eksporcie nie mają karty. `load_cards` zwraca karty w kolejności pliku JSONL.
- `card` i `raw_record` dostają nowy wiersz przy każdej nowej obserwacji reklamy, bo karta zawiera `last_seen` i `provenance`. To zamierzona historia.
- Jedna baza obsługuje jeden katalog stanu. Dwa katalogi z tym samym trybem (np. `scripts/e2e_pipeline.py` z produkcyjnym `DATABASE_URL`) nadpisują sobie `ad`, `feed_export` i `latest_run`. Testy i e2e uruchamiaj na osobnej bazie.

### Jeszcze niezrobione

- `page_capture` istnieje, ale nie jest zapełniana. Zapisy stron trafiają do bazy tylko przez kartę.
- Główne wejścia panelu i CLI korzystają z plików. Podłączenie `latest_run` i przechowywanie zamrożonej referencji oraz odpowiedzi na zapytania w PostgreSQL pozostają do wdrożenia.
- Wyszukiwanie wektorowe pgvector i tabele `feature` oraz `embedding` pozostają po MVP.

## Otwarte decyzje

1. Kto przejmuje schemat: import (para A) czy silnik i karty (para C). Zmiana na granicy modułów wymaga uzgodnienia kontraktu.
2. Czy wektory z `models/vectors/` trafiają do bazy, czy baza trzyma tylko odnośniki.
