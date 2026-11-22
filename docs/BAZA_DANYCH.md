# Baza danych ScamGraph

Dokument opisuje dwie rzeczy: **stan obecny**, czyli bazy SQLite i pliki, które dziś zapisuje scraper `scamgraph.discovery`, oraz **projekt bazy dla silnika**, czyli PostgreSQL z pgvector jako jedno trwałe źródło danych dla `ftf_graph`. Projekt jest decyzją zespołu z 2026-11-21. Wersja MVP jest wdrożona jako opcjonalny zapis obok plików, opis w sekcji [Uruchomienie](#uruchomienie). Reguła grupowania odpowiada [kontraktowi](DATA_CONTRACT.md#reguła-silnika-ftf_graph-decyzja-zespołu-2026-11-21): wynik pary 0–1 z uzasadnieniami i HDBSCAN.

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
                         silnik ftf_graph (Scorer, HDBSCAN)
                                       ▼
                               [4] przebiegi: krawędzie, kampanie
                                       │
                                       ▼
                     Neo4j (widok, odbudowywany) + Streamlit
```

Neo4j jest widokiem jednego przebiegu i zawsze da się go odbudować z warstwy 4. Pliki mediów i paczek stron leżą na dysku. Baza przechowuje ich sumy SHA-256 i ścieżki.

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
| `graph/export.sqlite3` | `exports(mode, revision)`: skrót ostatniego eksportu JSONL dla trybu. |
| `graph/analysis.sqlite3` | `reports(mode, revision)`: skrót JSONL, z którego policzono ostatni raport kampanii. |
| `captures/<capture_id>/` | Pakiet obserwacji: `manifest.json` z sumami SHA-256, `extracted.json`, `ad/card.json`, `landing/`. |
| `pages/<id_pobrania>/` | Paczka wizyty: `page.html`, `page_files/`, zrzuty, `network.har`, `metadata.json`. |
| `archives/<źródło>/` | Materiał źródłowy adaptera, np. zrzuty kart i ekranów błędu. |
| `graph/<tryb>.jsonl` | Karty w formacie `ftf_graph`: ostatnia obserwacja każdej pary dostawca–ID. |
| `graph/<tryb>.campaigns.json` | Raport silnika: kampanie, krawędzie z powodami, `unassigned`, `feed_sha256`, `computed_at`. |

Ograniczenia obecnego stanu: wyniki silnika są nadpisywane przy każdym przeliczeniu (brak historii przebiegów), każdy tryb i profil ma osobną bazę, a cechy z laboratorium modeli (`models/`) żyją w osobnych plikach.

## Projekt: PostgreSQL + pgvector

### Dlaczego PostgreSQL

| Potrzeba | Jak ją spełnia baza |
| --- | --- |
| Idempotentny import | Unikalne klucze `(dataset_id, ad_id)`, `(provider, ad_ref)` i `payload_sha256` odrzucają duplikaty. Konflikty trafiają do raportu importu. |
| Jedno źródło prawdy | Scraper, preprocesor, laboratorium modeli, silnik i Streamlit czytają i piszą w jednym miejscu, z transakcjami i wieloma jednoczesnymi czytelnikami. |
| Odtwarzalność wyniku | Każdy przebieg silnika ma `run_id`, konfigurację, wersję kodu i odcisk zbioru kart. Stare wyniki zostają. |
| Pochodzenie cech | Każda cecha ma `origin_id` i wersję ekstraktora (kontrakt, sekcja „Pochodzenie”). |
| Wektory | pgvector przechowuje embeddingi binarnie i pozwala wyszukiwać najbliższych sąsiadów (HNSW), gdy reklam będą tysiące. |

Alternatywy: SQLite nie obsłuży wygodnie jednoczesnego zapisu scrapera i odczytu GUI i nie ma wyszukiwania wektorowego. DuckDB nadaje się do analiz, ale nie jako baza, do której scraper dopisuje dane na bieżąco. Neo4j zostaje widokiem grafu: nie jest dobrym miejscem na surowe dane, wersje i historię przebiegów.

### Wersja minimalna (MVP): 6 tabel

```sql
-- [1] Wejście: surowe rekordy, tylko dopisywanie
CREATE TABLE raw_record (
    id              bigserial PRIMARY KEY,
    import_batch    text        NOT NULL,          -- np. run_id scrapera albo nazwa importu
    kind            text        NOT NULL CHECK (kind IN ('ad', 'page', 'link')),
    source_line     integer,                       -- numer wiersza lub lokalizator w oryginale
    payload         jsonb       NOT NULL,
    payload_sha256  char(64)    NOT NULL UNIQUE,   -- ten sam rekord nie wejdzie dwa razy
    received_at     timestamptz NOT NULL DEFAULT now()
);

-- [2] Emisje
CREATE TABLE ad (
    dataset_id      text        NOT NULL,
    ad_id           text        NOT NULL,
    provider        text        NOT NULL,
    ad_ref          text,                          -- ID u dostawcy, np. Biblioteki reklam
    source_kind     text        NOT NULL CHECK (source_kind IN ('library', 'organizer', 'synthetic', 'upload')),
    collected_at    timestamptz NOT NULL,
    published_at    timestamptz,                   -- puste, gdy źródło nie podaje daty
    text            text,
    landing_url     text,
    image_sha256    char(64),                      -- plik na dysku, nazwa = suma
    audio_sha256    char(64),
    origins         jsonb       NOT NULL DEFAULT '{}',  -- image_origin, text_origin, url_origin, audio_origin
    raw_record_id   bigint      REFERENCES raw_record(id),
    PRIMARY KEY (dataset_id, ad_id),
    UNIQUE (provider, ad_ref)
);

-- [2] Zapisy stron
CREATE TABLE page_capture (
    capture_id      text        PRIMARY KEY,
    url             text        NOT NULL,
    fetched_at      timestamptz NOT NULL,
    status          text        NOT NULL CHECK (status IN ('success', 'partial', 'failed')),
    http_status     integer,
    sections        jsonb       NOT NULL DEFAULT '{}',  -- html, document, har, dns_tls, assets
    package_path    text        NOT NULL,               -- pages/<id_pobrania>/ lub captures/<capture_id>/
    raw_record_id   bigint      REFERENCES raw_record(id)
);

-- [3] Karty dla silnika: dokładnie JSON przyjmowany przez ftf_graph.card.parse_card
CREATE TABLE card (
    dataset_id      text        NOT NULL,
    ad_id           text        NOT NULL,
    adapter_version text        NOT NULL,          -- np. 'feature-join-v2', 'graph-feed/3'
    card            jsonb       NOT NULL,
    built_from      char(64)    NOT NULL,          -- skrót danych wejściowych karty
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (dataset_id, ad_id, adapter_version, built_from),
    FOREIGN KEY (dataset_id, ad_id) REFERENCES ad
);
CREATE VIEW card_current AS
    SELECT DISTINCT ON (dataset_id, ad_id) *
    FROM card ORDER BY dataset_id, ad_id, created_at DESC;

-- [4] Przebiegi silnika
CREATE TABLE engine_run (
    run_id          uuid        PRIMARY KEY,
    created_at      timestamptz NOT NULL DEFAULT now(),
    code_version    text        NOT NULL,          -- commit
    config          jsonb       NOT NULL,          -- Config ze scoring.py, min_cluster_size, min_samples, min_edge
    backend         text        NOT NULL,          -- np. 'hdbscan 0.8.40' albo 'sklearn.cluster.HDBSCAN'
    cards_sha256    char(64)    NOT NULL,          -- odcisk zbioru kart wejściowych
    card_count      integer     NOT NULL,
    frozen          boolean     NOT NULL DEFAULT false  -- referencja dla zapytań o nowe emisje
);

-- [4] Wyniki przebiegu
CREATE TABLE run_result (
    run_id          uuid        NOT NULL REFERENCES engine_run ON DELETE CASCADE,
    kind            text        NOT NULL CHECK (kind IN ('edge', 'member', 'campaign', 'query')),
    key             text        NOT NULL,          -- 'A|B' dla krawędzi, ad_id dla członka, CMP-n, ID zapytania
    payload         jsonb       NOT NULL,          -- format edges.json / campaigns.json / MatchResult
    PRIMARY KEY (run_id, kind, key)
);
```

`run_result.payload` przechowuje to, co silnik już zwraca:

| `kind` | `payload` |
| --- | --- |
| `edge` | `{a, b, score, has_hard_evidence, reasons: [{group, kind, hard, strength, detail}]}` |
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
| `graph/<tryb>.jsonl` | `card` (`adapter_version='graph-feed/4'`) |
| `graph/<tryb>.campaigns.json` | `engine_run` + `run_result` |
| `graph/export.sqlite3`, `graph/analysis.sqlite3` | `card.built_from` i `engine_run.cards_sha256` |
| `runs`, `schedules`, `page_jobs`, `trusted_domains` | Zostają w SQLite scrapera: to stan operacyjny zegara, nie dane silnika |

## Integracja z silnikiem

Silnik nie wymaga zmian w logice. Obok `load_cards(path)` dochodzi wczytanie z bazy:

```python
from ftf_graph.card import parse_card

def load_cards_db(conn, dataset_id: str):
    rows = conn.execute("SELECT card FROM card_current WHERE dataset_id = %s ORDER BY ad_id", (dataset_id,))
    return [parse_card(card) for (card,) in rows]
```

Po obliczeniu zapis trafia do `engine_run` i `run_result`, a `neo4j_store.write` dostaje dane wybranego `run_id`. Eksport do JSONL zostaje na potrzeby ewaluacji i powtórzenia wyniku.

Samo przeniesienie kart do bazy nie przyspieszy obliczeń, bo `psycopg` i tak parsuje JSONB do słowników. Przyspieszenie dają: przyrostowe liczenie nowej emisji wobec zamrożonego przebiegu (`frozen`), wektory zapisane binarnie (`embedding`) i wybór kandydatów przez kNN.

## Uruchomienie

Z katalogu głównego projektu w PowerShell, przy działającym Dockerze i zainstalowanych zależnościach z `requirements-capture.txt`:

```powershell
docker compose -f graph/docker-compose.yml up -d --wait postgres
$env:DATABASE_URL = 'postgresql://scamgraph:scamgraph@127.0.0.1:5432/scamgraph'
.\.venv\Scripts\python.exe -c "from scamgraph.db import connect; c = connect(); print('Wersja schematu:', c.execute('SELECT version FROM schema_version').fetchone()[0]); c.close()"
```

Panel lub scheduler uruchom z tej samej sesji PowerShell, aby odziedziczył `DATABASE_URL`. Usługa `pgvector/pgvector:pg17` słucha na `127.0.0.1` i zapisuje dane w woluminie `postgres_data`. Przy pierwszej inicjalizacji własne hasło można ustawić przez `POSTGRES_PASSWORD` w środowisku Compose i użyć jego odpowiednika zakodowanego do URL w `DATABASE_URL`. Schemat zakłada `scamgraph.db` przy pierwszym połączeniu. Obecny zapis korzysta ze schematu w wersji 3, także w istniejącym woluminie. Przyszłe zmiany struktury tabel wymagają migracji. [Schemat SQL](../db/schema.sql)

Zapis działa w `scamgraph/discovery/graph_feed.py`, w tych samych miejscach, w których powstają pliki:

| Krok | Pliki | Baza |
| --- | --- | --- |
| `export_graph()` | `graph/<tryb>.jsonl` | `raw_record`, `ad`, `card` z opublikowanego pliku oraz `page_capture` dla dostępnych pakietów z zakończoną wizytą. Przy braku karty `ad.unavailable` zawiera powód. `feed_export` pamięta ostatni zapisany eksport i wersję zapisu SQL. |
| `update_campaigns()` | `graph/<tryb>.campaigns.json` | `engine_run` i `run_result` z tego samego raportu, czyli już z opisami poprawionymi dla `TEXT_METHOD`. |

Bez `DATABASE_URL` zmieniają się tylko dwie rzeczy: raport dostaje pola `engine_config` i `code_version`, a `graph/export.sqlite3` zapisuje czas eksportu w tabeli `export_times`. Zapis do bazy odbywa się po zwolnieniu blokad SQLite, z limitami: połączenie 3 s, zapytanie 30 s, blokada 5 s (`connect_timeout`, `options` i ustawienia keepalive w URL-u mają pierwszeństwo). Keepalive TCP kończy połączenie po zerwaniu sieci. Nie obejmuje serwera, który przyjął połączenie, a potem zamarzł (np. wstrzymany kontener): wtedy wątek grafu czeka, ale nie trzyma blokad SQLite. Zostaje to jako ograniczenie MVP. Przy niezmienionym eksporcie i raporcie każdy tick zegara kończy się jednym zapytaniem na każdy z nich. Błąd bazy nie zatrzymuje pipeline'u: pliki powstają, a traceback trafia na stderr i do `graph/<tryb>.feed.db-error` lub `graph/<tryb>.run.db-error`. Znacznik znika po udanym zapisie. Raport policzony przed włączeniem bazy trafia do niej przy następnym przebiegu zegara. Odczyt: `scamgraph.db.load_cards(conn, tryb)` i `scamgraph.db.latest_run(conn, tryb)`.

Testy: `TEST_DATABASE_URL=postgresql://... python -m unittest tests.test_db`. Każdy test czyści schemat `public` wskazanej bazy, więc wskazuj pustą bazę testową.

### Decyzje wdrożenia MVP (zespół, 2026-11-21)

- `dataset_id` = tryb źródła (`live`, `replay`, `import`), a `ad_id` = `provider/ad_ref`, jak w `graph_feed`.
- Unikalność `(provider, ad_ref)` obowiązuje w obrębie `dataset_id`, bo ta sama reklama bywa w kilku trybach.
- `source_kind`, skróty mediów i pochodzenie pól pochodzą z pakietu. Gdy brakuje informacji o rodzaju źródła, używamy `library` dla trybu `live` i `upload` dla pozostałych.
- `page_capture.capture_id` to stały identyfikator wizyty (`landing_visit.page_id`). `package_path` wskazuje zapis z pakietu dowodowego, a `sections.ad_page_links` zawiera dostępne dowody relacji przy pierwszym zapisie. Status i czas pochodzą z metadanych pobrania. Zapis dotyczy wizyt obecnych w pakietach bieżącego feedu, także zakończonych jako `partial` lub `failed`. Kolejny eksport uzupełnia te dane także dla istniejącego feedu. HTML, HAR i zrzuty pozostają w pakietach na dysku.
- `engine_run` ma kolumny `dataset_id`, `computed_at` (z raportu) i `seq`. `cards_sha256` to SHA-256 pliku JSONL (`feed_sha256` raportu). `config` (`ENGINE_CONFIG`, przekazywane jawnie do `ftf_graph`) i `code_version` (`git describe --always --dirty`) są zapisywane w raporcie w chwili liczenia, nie w chwili zapisu do bazy.
- Nowy przebieg nie powstaje, gdy najnowszy przebieg trybu ma to samo wejście, konfigurację i wersję kodu albo gdy jest nowszy od raportu. Kolejność ustala `computed_at`, a przy remisie `seq`. Dzięki temu `latest_run` odpowiada bieżącemu plikowi raportu.
- Eksporty porządkuje czas zapisu pliku (`export_times` w `graph/export.sqlite3`). Starszy eksport, który dotrze później, jest pomijany.
- `card_current` to karta z ostatniego eksportu (`ad.card_built_from`). Reklamy niedostępne przy tym eksporcie nie mają karty. `load_cards` zwraca karty w kolejności pliku JSONL.
- `card` i `raw_record` dostają nowy wiersz przy każdej nowej obserwacji reklamy, bo karta zawiera `last_seen` i `provenance`. To zamierzona historia.
- Jedna baza obsługuje jeden katalog stanu. Dwa katalogi z tym samym trybem (np. `scripts/e2e_pipeline.py` z produkcyjnym `DATABASE_URL`) nadpisują sobie `ad`, `feed_export` i `latest_run`. Testy i e2e uruchamiaj na osobnej bazie.

### Jeszcze niezrobione

- Panel, Streamlit i Neo4j nadal czytają pliki. Przepięcie na `latest_run` to następny krok.
- `frozen`, zapytania `query`, tabele `feature` i `embedding` (rozszerzenia po MVP).

## Otwarte decyzje

1. Kto przejmuje schemat: import (para A) czy silnik i karty (para C). Zmiana na granicy modułów wymaga uzgodnienia kontraktu.
2. ~~Czy scraper pisze do bazy bezpośrednio, czy importer wsadowo czyta jego katalog stanu.~~ Rozstrzygnięte: zapis w `graph_feed`, obok plików.
3. Czy wektory z `models/vectors/` trafiają do bazy, czy baza trzyma tylko odnośniki.
