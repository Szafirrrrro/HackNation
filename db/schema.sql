-- Schemat bazy ScamGraph, wersja MVP. Opis: docs/BAZA_DANYCH.md.
-- Plik jest idempotentny. scamgraph.db wykonuje go, gdy schema_version różni się od SCHEMA_VERSION.
-- Rozbieżności z pierwszym projektem (decyzje zespołu, 2026-11-21) są oznaczone "ZMIANA".

-- [1] Wejście: surowe rekordy, tylko dopisywanie
CREATE TABLE IF NOT EXISTS raw_record (
    id              bigserial PRIMARY KEY,
    import_batch    text        NOT NULL,          -- run_id scrapera albo nazwa importu
    kind            text        NOT NULL CHECK (kind IN ('ad', 'page', 'link')),
    source_line     integer,                       -- numer wiersza w oryginale, gdy jest
    payload         jsonb       NOT NULL,
    payload_sha256  char(64)    NOT NULL UNIQUE,   -- ten sam rekord nie wejdzie dwa razy
    received_at     timestamptz NOT NULL DEFAULT now()
);

-- [2] Emisje. dataset_id = tryb źródła (live, replay, import).
-- ZMIANA: unikalność (provider, ad_ref) w obrębie zbioru, bo ta sama reklama bywa w kilku trybach.
-- ZMIANA: unavailable (powód braku karty) i card_built_from (karta z ostatniego eksportu).
CREATE TABLE IF NOT EXISTS ad (
    dataset_id      text        NOT NULL,
    ad_id           text        NOT NULL,
    provider        text        NOT NULL,
    ad_ref          text,
    source_kind     text        NOT NULL CHECK (source_kind IN ('library', 'organizer', 'synthetic', 'upload')),
    collected_at    timestamptz NOT NULL,
    published_at    timestamptz,
    text            text,
    landing_url     text,
    image_sha256    char(64),
    audio_sha256    char(64),
    origins         jsonb       NOT NULL DEFAULT '{}',
    unavailable     text,                          -- powód braku karty; NULL = karta jest
    card_built_from char(64),                      -- card.built_from z ostatniego eksportu; NULL przy braku karty
    raw_record_id   bigint      REFERENCES raw_record(id),
    PRIMARY KEY (dataset_id, ad_id),
    UNIQUE (dataset_id, provider, ad_ref)
);

-- [2] Zapisy stron (jeszcze niezapełniane, patrz docs/BAZA_DANYCH.md)
CREATE TABLE IF NOT EXISTS page_capture (
    capture_id      text        PRIMARY KEY,
    url             text        NOT NULL,
    fetched_at      timestamptz NOT NULL,
    status          text        NOT NULL CHECK (status IN ('success', 'partial', 'failed')),
    http_status     integer,
    sections        jsonb       NOT NULL DEFAULT '{}',
    package_path    text        NOT NULL,
    raw_record_id   bigint      REFERENCES raw_record(id)
);

-- [3] Karty dla silnika: dokładnie JSON przyjmowany przez ftf_graph.card.parse_card
CREATE TABLE IF NOT EXISTS card (
    dataset_id      text        NOT NULL,
    ad_id           text        NOT NULL,
    adapter_version text        NOT NULL,
    card            jsonb       NOT NULL,
    built_from      char(64)    NOT NULL,          -- SHA-256 kanonicznego JSON-u karty
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (dataset_id, ad_id, adapter_version, built_from),
    FOREIGN KEY (dataset_id, ad_id) REFERENCES ad
);

-- Karty z ostatniego eksportu; reklamy niedostępne przy tym eksporcie nie mają karty.
DROP VIEW IF EXISTS card_current;
CREATE VIEW card_current AS
    SELECT c.*, a.provider, a.ad_ref
    FROM ad a JOIN LATERAL (
        SELECT * FROM card
        WHERE dataset_id = a.dataset_id AND ad_id = a.ad_id AND built_from = a.card_built_from
        ORDER BY created_at DESC, adapter_version DESC LIMIT 1
    ) c ON true;

-- Ostatni eksport zbioru zapisany w bazie (pomija powtórki i spóźnione starsze eksporty).
CREATE TABLE IF NOT EXISTS feed_export (
    dataset_id      text        PRIMARY KEY,
    revision        char(64)    NOT NULL,          -- rewizja z graph/export.sqlite3
    written_ns      bigint      NOT NULL,          -- czas zapisu pliku JSONL
    stored_at       timestamptz NOT NULL DEFAULT now()
);

-- [4] Przebiegi silnika
-- ZMIANA: dataset_id (przebiegi trybu), computed_at z raportu i seq do jednoznacznej kolejności.
CREATE TABLE IF NOT EXISTS engine_run (
    run_id          uuid        PRIMARY KEY,
    seq             bigserial   UNIQUE,
    dataset_id      text        NOT NULL,
    computed_at     timestamptz NOT NULL,          -- chwila policzenia raportu
    created_at      timestamptz NOT NULL DEFAULT now(),
    code_version    text        NOT NULL,          -- git describe w chwili liczenia raportu
    config          jsonb       NOT NULL,          -- min_cluster, min_samples, min_edge
    backend         text        NOT NULL,
    cards_sha256    char(64)    NOT NULL,          -- SHA-256 pliku JSONL wejścia (feed_sha256)
    card_count      integer     NOT NULL,
    frozen          boolean     NOT NULL DEFAULT false
);
-- Migracja v3 -> v4. Historyczne raporty nie zawierają odcisku metody.
ALTER TABLE engine_run ADD COLUMN IF NOT EXISTS engine_fingerprint char(64);
CREATE INDEX IF NOT EXISTS engine_run_latest ON engine_run (dataset_id, computed_at DESC, seq DESC);

-- [4] Wyniki przebiegu. ZMIANA: kind 'unavailable' dla reklam pominiętych przez brak karty.
CREATE TABLE IF NOT EXISTS run_result (
    run_id          uuid        NOT NULL REFERENCES engine_run ON DELETE CASCADE,
    kind            text        NOT NULL CHECK (kind IN ('edge', 'member', 'campaign', 'query', 'unavailable')),
    key             text        NOT NULL,
    payload         jsonb       NOT NULL,
    PRIMARY KEY (run_id, kind, key)
);

CREATE TABLE IF NOT EXISTS schema_version (version integer NOT NULL);
