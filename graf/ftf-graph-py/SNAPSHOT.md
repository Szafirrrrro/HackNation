# Ekstrakcja zapisanej strony offline

Moduł `ftf_graph.snapshot` jest adapterem zapisów stron do istniejącej karty
`ftf_graph.card.parse_card`. Nie tworzy emisji ani powiązania AdPageLink na podstawie
nazwy folderu. Wynik zachowuje `ad_id=null`; przy włączeniu do zbioru reklam trzeba
osobno udokumentować związek z emisją zgodnie z [kontraktem](../../docs/DATA_CONTRACT.md).

Z katalogu `graf/ftf-graph-py`, Python 3.10+:

```bash
python3 -m ftf_graph extract-snapshot /sciezka/do/snapshotu --out /sciezka/wynik.json
# Jawne wskazanie potwierdzonego zrzutu reklamy (ścieżka względem snapshotu):
python3 -m ftf_graph extract-snapshot /sciezka/do/snapshotu --screenshot 'Zrzut ekranu.png' --out /sciezka/wynik.json
# Opcjonalne pHash i mmh3, bez wag modeli:
python3 -m pip install -r requirements-snapshot.txt
python3 -B -m unittest discover -s tests -v
```

Podstawowy JSON wymaga tylko biblioteki standardowej. Nie ma żądań sieciowych,
wykonywania JS, `eval`, uruchamiania przeglądarki ani pobierania modeli.
CLI ekstrakcji nie importuje HDBSCAN, Neo4j ani scikit-learn.
CLI zapisuje czytelny JSON UTF-8; importer przyjmuje go obok dotychczasowego JSONL.
Zapisuj wynik poza folderem wejściowym. Zapis zastępuje wskazany plik wynikowy.

```python
from ftf_graph.snapshot import extract_snapshot, write_snapshot
from ftf_graph.card import parse_card
record = extract_snapshot('/sciezka/snapshot')
card = parse_card(record)  # obserwacja strony; card.id pozostaje pusty
write_snapshot('/sciezka/snapshot', '/sciezka/wynik.json')
```

Dotychczasowe wywołanie `python3 -m ftf_graph cards.jsonl` działa jak wcześniej.
Adapter karty pomija wspólne biblioteki oznaczone w `extensions.scripts` i nie
przekształca IP połączenia z HAR w dowód wspólnego serwera. Samo podobieństwo
stron nadal nie potwierdza wspólnej kampanii reklamowej.

## Decyzje ekstraktora v1

To decyzje implementacyjne zespołu, nie progi narzucone przez NASK.

- Pliki rozpoznajemy po zawartości, odwołaniach HTML i MIME HAR. Nazwy Unicode,
  `.pobrane` i brak rozszerzenia nie blokują odczytu. SHA-256 jest liczony na
  zdekodowanych bajtach HAR albo bajtach lokalnego skryptu; skrypt inline na UTF-8
  jego zawartości. Te same bajty mają jeden hash z wieloma źródłami.
- Dokument wybieramy z żądań nawigacji, następnie HTML MIME; komentarz saved-from-url
  i URL w `log.pages.title` pomagają rozstrzygnąć wybór. Jawny typ zasobu inny niż
  document wyklucza go z nawigacji. Łańcuch wymaga zarejestrowanych 30x i żądania
  celu w tym samym HAR/page, w kolejności wpisów. Skrypty, obrazki i piksele nie
  stają się przekierowaniami. Przy kilku dokumentach zapisujemy ostrzeżenie;
  snapshot powinien reprezentować jedno pobranie. Przekierowania JS/meta-refresh
  nie są rekonstruowane bez zapisu nawigacji. IP pochodzi z końcowego dokumentu.
- URL-e eksportujemy bez credentials, query i fragmentu, aby nie przenosić sesji.
  Tracking odczytujemy przed tą redakcją. Query nie jest eksportowane w evidence.
  `fetched_at` wymaga poprawnego czasu ze strefą z żądania głównego dokumentu.
  Tytuł gazety nie stanowi źródła domeny. Status HTTP jest historyczną obserwacją.
- `window.aio` jest czytane jako ograniczony literał JSON/JS: stringi, liczby,
  bool, null, tablice i obiekty. Wyrażenia i funkcje są odrzucane. Eksport ma
  allowlistę: `visit.fields.fb_{pixel,ad_id,campaign_id,ad_set_id}`, `campaign.uuid`,
  `campaign.owner_uuid` oraz trzy pola landing wskazane w zadaniu. Nie eksportujemy
  całej konfiguracji, cookies, nagłówków autoryzacji ani request.postData.
- `dom-structure-v1`: parser HTML zapisuje kolejno otwarcia/zamknięcia tagów
  i posortowane pary atrybutów `type`, `role`, `method` tylko dla jawnej listy
  semantycznych wartości w `Document.handle_starttag`. Pomija komentarze, tekst,
  zawartość script/style oraz wartości ID/class/URL. SHA-256 dotyczy zwartego JSON
  UTF-8 tej sekwencji. To odcisk struktury, nie pełny silnik renderowania HTML.
- `explicit-hidden-text-v1` obejmuje tekst potomków `hidden`, `aria-hidden=true`,
  inline `display:none` i `visibility:hidden`. Normalizacja to pojedyncze spacje
  i kolejność dokumentu, hash SHA-256 UTF-8. Brak wykrytego tekstu daje null.
  Zewnętrzne CSS, pozycjonowanie i dynamiczne zmiany nie są oceniane.
- `form_endpoint` oznacza deklarowane action formularza HTML, nie potwierdzone
  wysłanie leada. `fetch`/`.post` daje wyłącznie kandydata w extensions. POST HAR
  pozostaje telemetrią (heurystyka URL) albo niesklasyfikowanym POST-em. Kontakty
  to kandydaci z tekstu i linków HTML, z kontekstem; adresy crypto bez walidacji
  checksum. Numery odwiedzającego z postData nie są kontaktami operatora.
- Obrazy dostają cechy per plik/odpowiedź. `visual.phash` wymaga jawnego
  `--screenshot`; sama obecność jednego obrazu nie dowodzi, że to reklama.
  pHash to istniejąca konwencja laboratorium: ImageHash 4.3.1, 64 bity, szarość,
  Lanczos 32x32 i mediana DCT 8x8. Faviconę pobieramy z link rel=icon i HAR;
  wiele różnych kandydatów daje ostrzeżenie. SVG bez rasteryzacji daje ostrzeżenie.
  mmh3: signed x86 32-bit na MIME base64 (wiersze 76 znaków, końcowy LF),
  konwencja Shodan. Dotychczasowy projekt nie definiował konwencji mmh3.
- Limit pojedynczego pliku/body: 32 MiB, łącznie 256 MiB bajtów wejść i body HAR;
  obraz do 60 mln pikseli. Dowiązania i wyjścia poza snapshot są pomijane.
  Uszkodzony element daje ostrzeżenie i nie przerywa reszty ekstrakcji.

## Opcjonalne modele i granice pomiaru

`extract_snapshot(..., extractors=[...])` przyjmuje **już załadowane** instancje
laboratoryjnego `Extractor` z `testowanie_modeli/containers`. Sam nie wywołuje
`load()`. Obsługuje `ocr.text` (Tesseract/EasyOCR), `image.embedding` CLIP oraz
`text.embedding` (Embed E5/BGE). Konfigurację i lokalne wagi zapewnia wywołujący
w środowisku laboratorium; nie należy wywoływać sieciowego `load()` na niezaufanych
materiałach. Modele twarzy pozostają poza tym adapterem, bez identyfikacji osób.

OCR i CLIP uruchamiane są na lokalnych obrazach i zapisywane w `extensions.images`.
OCR wybranego zrzutu trafia do `text.ocr_text`, CLIP do `visual.clip_embedding`.
Dla samych obrazów z HAR pozostają cechy pHash, bez OCR/CLIP w tym adapterze.
Embedding tekstu strony trafia do `extensions.landing_embedding`, a tekst do
`extensions.landing_text`: nie są utożsamiane z tekstem reklamy. Nie skonfigurowano
modelu: null/pusta lista i ostrzeżenie. Błędy modelu są izolowane per plik.

Brak RDAP/ASN/certyfikatu, dat historii, tekstu reklamy czy tożsamości oznacza brak
dowodu; offline nie zastępujemy tego danymi online. Nie ma dodatkowego wzbogacenia
sieciowego w istniejącym pipeline. Evidence opisuje źródła, nie siłę korelacji.

## Odtwarzalny przykład

`tests/fixtures/snapshot` zawiera własne dane syntetyczne na domenach `.example`,
bez materiałów organizatora. Nie jest to snapshot z pytania użytkownika.

```bash
python3 -m ftf_graph extract-snapshot tests/fixtures/snapshot --out /tmp/scamgraph-synthetic-snapshot.json
```

Uzyskano: nawigację `front.example/start` → `evil.example/article`, czas
`2026-10-09T08:24:11Z`, IP połączenia `192.0.2.7`, trzy Meta Pixel, GA `G-ABC123`,
Ads `AW-123` oddzielnie, identyfikatory AIO, trzy SHA-256 skryptów, hash struktury,
hash jawnie ukrytego tekstu, telefon i Telegram. `fetch('/api/lead')` to kandydat,
POST Facebook to telemetria. Brak obrazu w tej próbce pozostawia pHash/faviconę
puste; osobny test generuje PNG i odtwarza faviconę base64 z HAR.

Weryfikacja: 11 testów regresji, również pełna ścieżka CLI, deterministyczność,
blokada socketów, base64, konflikty URL, brakujące pliki, uszkodzony HAR/obraz,
nieprawidłowe URL, puste atrybuty, DOM, bezpieczne AIO i izolacja bibliotek.

## Połączenie z laboratorium z commita 3053765

Trzy komendy z `graf/ftf-graph-py` tworzą jeden przepływ:

```bash
python3 -m ftf_graph extract-snapshot /folder/snapshot --screenshot 'Zrzut.png' --out ../../wyniki/snapshot.json
python3 -m ftf_graph prepare-model-input /folder/snapshot --screenshot 'Zrzut.png' --out ../../wyniki/model-input
```

Druga komenda tworzy korpus v0 (`manifest.json`, `ads.jsonl`, `media/`) dla istniejącego
`extract.sh`. ID `file-<sha256[:16]>` to lokalny identyfikator materiału, bez twierdzenia
o tożsamości emisji. Obraz i jego OCR zachowują `image_origin=sha256:<pełny hash>`.
Katalog wyjściowy musi być nowy. Uzupełnienie `text` w źródłowym `ads.jsonl` wymaga
faktycznego tekstu reklamy i jego pochodzenia. Nie wstawiamy tam tekstu landing page'a.

Następnie w środowisku z wcześniej zbudowanymi obrazami i lokalnymi wagami:

```bash
cd ../../testowanie_modeli
DATA=../wyniki/model-input OUT=../wyniki/model-features NEIGHBORS=0 bash extract.sh ocr image_embedding
# Opcjonalnie jawne modele odłożone/kandydaci; bez automatycznego pobierania:
DATA=../wyniki/model-input OUT=../wyniki/model-features NEIGHBORS=0 MODELS=multilingual-e5-small bash extract.sh text
# Tylko jeżeli skonfigurowano te modele oraz warunki użycia wag:
DATA=../wyniki/model-input OUT=../wyniki/model-features NEIGHBORS=0 MODELS=clip bash extract.sh image_embedding
DATA=../wyniki/model-input OUT=../wyniki/model-features NEIGHBORS=0 MODELS=opencv-yunet-sface bash extract.sh face
```

Każde wywołanie `extract.sh` korzysta z `--network none`, istniejącego kodu i obrazów
`tm-*`. Ten adapter nie buduje obrazów ani nie pobiera wag. Przy braku obrazów modele
pozostają niedostępne; sam snapshot nadal daje JSON. Po ekstrakcji:

```bash
cd ../graf/ftf-graph-py
python3 -m ftf_graph merge-features ../../wyniki/snapshot.json \
  --features ../../wyniki/model-features/model-input \
  --feature-ad-id 'file-ID_WYPISANE_PRZEZ_PREPARE' --out ../../wyniki/card.json
```

W przypadku kilku OCR/embeddingów dodaj np.:

```bash
--method 'text.embedding=text_embedding/multilingual-e5-small@DOKLADNA_WERSJA_Z_JSONL' \
--source 'text.embedding=ocr.text@DOKLADNA_METODA_OCR'
```

Nie ma wyboru na podstawie kolejności plików. Nieporównywalne metody/przestrzenie
wektorowe zostają nierozstrzygnięte z ostrzeżeniem. Import wymaga zgodnego SHA-256
obrazu (oryginalny korpus albo `image.sha256` z laboratorium), `origin_id`, metody
wiersza i przebiegu oraz `corpus_fingerprint`. Odrzuca konflikt istniejącego `ad_id`.
Wektory są odczytywane per referencja `value.vector` z `.npy` bez pickle, z walidacją
ścieżki, wymiaru, indeksu, typu i skończoności liczb. Uszkodzona cecha nie blokuje
innych poprawnych cech. Evidence zachowuje plik, wiersz, metodę, pochodzenie i fingerprint.

| Źródło | Pole finalnego JSON-a |
| --- | --- |
| `ads.jsonl:text` | `text.ad_text` |
| `ocr.text` | `text.ocr_text` |
| `text.embedding` (tekst reklamy lub OCR wskazany w evidence) | `text.embedding` |
| `image.embedding` CLIP | `visual.clip_embedding` |
| `image.embedding` DINOv2 | `extensions.image_embedding` |
| `image.phash` | `visual.phash` |
| `face.embedding` | `faces[].embedding`, ramka, face_index, det_score |
| QR, OCR URL, temat i dHash | odpowiednie pola `extensions` |

`person`, `similarity`, `quality`, `deepfake_score` są null, dopóki nie istnieją
odpowiednie metody i baza referencyjna. `det_score` nie jest jakością twarzy.
Detektor AI-generated nie jest detektorem deepfake konkretnej twarzy i nie wypełnia
tego pola. Słowa kluczowe to rzeczywiście występujące frazy z jawnego małego słownika
(`observed-phrase-lexicon-v1`); nie są predykcją modelu ani embeddingiem TF-IDF.

Historia emisji, obecny status alive/dead, RDAP, ASN i certyfikat nadal wymagają
osobnych obserwacji. Nie wynikają z modeli obrazu/tekstu ani z archiwalnego HTTP 200.
`provenance.source` pozostaje `provided_snapshot`. Puste pola są pełnoprawnym wynikiem
tego samego schematu, a nie miejscem na przykładowe liczby czy string `"..."`.

Parser AIO obsługuje też `JSON.parse(<literał string JSON>)` przez dekodowanie danych,
bez uruchamiania JS. Zawartość spoza allowlisty nie jest eksportowana. Telefony są
szukane w oddzielnych węzłach tekstu, z ostrożniejszym formatem numeru; może to pomijać
nietypowe formaty. Poprawiono realny przypadek błędnego scalenia roku i liczby osób.

Wynik jest czytelnym wielowierszowym JSON-em; `load_cards` obsługuje teraz zarówno
pojedynczy taki obiekt, jak i dotychczasowe JSONL. Ograniczenia historycznej instrukcji
powyżej dotyczą wcześniejszego jednowierszowego zapisu. Przy bezpośrednich adapterach
modeli `Out.reason` z nowego kontraktu jest traktowane jako niedostępność cechy.
