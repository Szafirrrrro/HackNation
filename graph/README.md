# ftf-graph — łączenie fałszywych reklam w kampanie (Follow the Fake)

Silnik bierze **karty reklam** (jedna reklama = jeden obiekt JSON z danymi z crawlera i analizatorów),
porównuje każdą parę reklam, wylicza **wynik podobieństwa z uzasadnieniem**, grupuje reklamy w **kampanie**
algorytmem HDBSCAN, a wynik zapisuje do JSON i opcjonalnie do **Neo4j**. Demonstrator w Streamlicie
pokazuje graf kampanii, oś czasu i to, gdzie trafia nowo wgrana reklama.

```
karty.jsonl
   │  card.py      każda karta → artefakty (dyskretne wartości) + wektory/odciski
   ▼
   │  scoring.py   każda para kart → ślady twarde i miękkie → max na grupę → noisy-OR → score 0..1
   ▼
macierz score N×N  ──►  edges.json / krawędzie :SIMILAR (score ≥ min_edge, z listą powodów)
   │  cluster.py   HDBSCAN na odległości 1 − score
   ▼
kampanie  ──►  campaigns.json  ──►  Neo4j (neo4j_store.py)  ──►  Streamlit (app.py)
```

---

## Szybki start

Wymagania: Python 3.10+ (testowane na 3.12 i 3.13), opcjonalnie Docker (dla Neo4j).

```bash
pip install -r requirements-app.txt            # silnik + Streamlit (sam silnik: requirements.txt)

python tools/gen_sample_cards.py               # 27 syntetycznych kart  -> data/sample_cards.jsonl
python tools/make_new_ad_examples.py           # 3 przykładowe "nowe reklamy" -> data/new_ad_*.json

python -m ftf_graph data/sample_cards.jsonl --query B03     # raport w konsoli + out/*.json
streamlit run app.py                                         # demonstrator w przeglądarce
```

Z zapisem do Neo4j:

```bash
docker compose up -d                           # Neo4j 5; Browser: http://localhost:7474 (neo4j / hackathon123)
python -m ftf_graph data/sample_cards.jsonl --neo4j bolt://localhost:7687 --neo4j-password hackathon123 --wipe
```

Opcje CLI (`python -m ftf_graph KARTY.jsonl ...`):

| Opcja | Domyślnie | Znaczenie |
|---|---|---|
| `--out DIR` | `out` | katalog na `edges.json` i `campaigns.json` |
| `--min-cluster N` | 3 | minimalna liczba reklam w kampanii (HDBSCAN `min_cluster_size`) |
| `--min-samples K` | 2 | HDBSCAN `min_samples` |
| `--min-edge X` | 0.25 | minimalny score krawędzi zapisywanej do `edges.json` / Neo4j; także minimalne powiązanie reklamy z jej kampanią |
| `--query AD_ID` | — | wypisuje kampanię reklamy i 5 najsilniejszych powiązań z powodami |
| `--neo4j URI` | — | zapis do Neo4j (np. `bolt://localhost:7687`) |
| `--neo4j-user`, `--neo4j-password` | `neo4j`, `""` | albo zmienne `NEO4J_USER`, `NEO4J_PASSWORD` |
| `--wipe` | wyłączone | czyści **całą** bazę Neo4j przed zapisem (do powtarzalnego demo) |

---

## Pojęcia

| Pojęcie | W kodzie | Znaczenie |
|---|---|---|
| **karta** | `Card` | jedna reklama; w Neo4j węzeł `:Ad` |
| **artefakt** | `Artifact(kind, value)` | dyskretna wartość z karty, która może się powtórzyć w innej (piksel, domena, telefon…); w Neo4j węzeł współdzielony przez reklamy |
| **ślad** | `Reason` | coś wspólnego dla **pary** kart, z siłą 0..1 |
| **ślad twardy** | `Reason.hard = True` | obie karty mają **ten sam** artefakt |
| **ślad miękki** | `Reason.hard = False` | karty są **podobne** w jakimś stopniu (wektory, odciski, daty) |
| **grupa** | `Reason.group` | kategoria spokrewnionych śladów; z każdej grupy liczy się tylko najsilniejszy |
| **krawędź** | `Edge`, `:SIMILAR` | wynik dla pary kart: `score` + lista śladów jako uzasadnienie |
| **kampania** | `Campaign`, `:Campaign` | klaster **reklam** wyznaczony przez HDBSCAN (artefakty nie są członkami kampanii) |
| **szum** | etykieta `-1`, `unassigned` | reklama bez kampanii — **nie** oznacza „bezpieczna” |

„Twardy” nie znaczy „mocny”: wspólny rejestrator to ślad twardy o sile 0.05, a podobna twarz to ślad
miękki o sile do 0.5.

---

## Format karty i co się dzieje z każdym polem

Jedna karta na linię pliku JSONL. Przykłady: `data/example_card.json`, z audio: `data/example_card_audio.json`.
Każde pole może być `null` albo go brakować.

Legenda: **T** = artefakt, z którego powstaje ślad twardy (i węzeł w Neo4j) · **M** = ślad miękki ·
**Z** = tylko zapisywane/wyświetlane · **—** = wczytywane, ale nieużywane.

| Pole | Użycie | Szczegóły |
|---|---|---|
| `ad_id` | Z | identyfikator reklamy |
| `provenance.source`, `.url`, `.fetched_at` | Z | właściwości `:Ad`, raport |
| `first_seen`, `last_seen`, `status` | Z | okres kampanii, liczniki aktywne/martwe, oś czasu |
| `infra.redirect_chain[]` | **T** `domain_hop` | każda domena łańcucha poza docelową; URL → sama domena (bez `www.`, ścieżki, parametrów) |
| `infra.final_domain` | **T** `domain_final` | gdy brak — ostatni element łańcucha |
| `infra.rdap.registrar` | **T** `registrar`, **M** | także do śladu „hurtowa rejestracja” |
| `infra.rdap.registered` | **M** | hurtowa rejestracja (z `registrar`) |
| `infra.rdap.nameservers[]` | **T** `nameserver` | |
| `infra.dns.ip`, `infra.dns.asn` | **T** `ip`, `asn` | |
| `infra.cert.id` | **T** `cert` | |
| `infra.cert.san[]` | Z | tylko relacje `(:Certificate)-[:COVERS]->(:Domain)` w Neo4j; **nie** wpływa na score |
| `infra.favicon.mmh3` | **T** `favicon` | tylko liczba całkowita |
| `infra.favicon.phash` | — | |
| `page.tracking_ids.meta_pixel`, `.ga` | **T** `tracking_id` | oba trafiają do tego samego rodzaju |
| `page.script_hashes[]` | **T** `script` | |
| `page.form_endpoint` | **T** `form_endpoint` | host + ścieżka, bez parametrów |
| `page.contacts.phones[]` | **T** `phone` | normalizacja: `+48 123-456-789` → `+48123456789` |
| `page.contacts.telegram[]` | **T** `telegram` | normalizacja: `https://t.me/X`, `t.me/X`, `@X` → `@x` |
| `page.contacts.crypto[]` | **T** `crypto` | bez normalizacji |
| `page.dom_template_hash` | **T** `template` | |
| `page.dom_template_minhash` | — | odcisk `dom-shingle-minhash-v1` z `scamgraph` (podobieństwo szablonu, nie równość); scorer go jeszcze nie czyta — zachowany w `Card.raw`, zob. [kontrakt](../docs/DATA_CONTRACT.md) |
| `page.hidden_text_hash` | **T** `hidden_text` | |
| `text.keywords[]` | **T** `keyword` | małe litery |
| `text.embedding` | **M** `text` | |
| `text.ad_text` | Z | podpisy, Neo4j |
| `text.ocr_text` | — | |
| `visual.phash` | **M** `phash` | 64-bit hex |
| `visual.clip_embedding` | **M** `visual` | |
| `faces[].embedding` + `.quality` | **M** `face` | brak `quality` → 0.5 |
| `faces[].person` | **T** `person` (waga 0) | węzeł `:Person` w Neo4j, ale **nie** wpływa na score |
| `faces[].similarity`, `.deepfake_score` | — | |
| `audio.transcript` | **T** `transcript` | normalizacja: małe litery, bez interpunkcji; > 300 znaków → hash |
| `audio.text_embedding` | **M** `audio_text` | |
| `audio.speaker_embedding` | **M** `voice` | |
| `audio.fingerprint.array` | **T** `audio_fp` + **M** `audio_fp_sim` | identyczny → twardy (hash tablicy); podobny → miękki |
| `audio.duration_s` | Z | `Ad.audio_duration_s` |
| `audio.segments`, `.asr_duration_s`, `fingerprint.key/shape/dtype/n_frames` | — | |
| `extensions`, `extraction` | — | zachowane w `Card.raw` |

Wszystkie wektory jednego rodzaju (np. każdy `speaker_embedding` w korpusie) muszą mieć ten sam wymiar,
inaczej analiza kończy się błędem `embeddingi mają różne wymiary`.

---

## Jak liczony jest score pary reklam

### 1. Ślady twarde: wspólny artefakt

```
siła = waga_rodzaju × rzadkość(df)          df = w ilu reklamach korpusu występuje artefakt
rzadkość(df) = log(N/df) / log(N/2)         N  = liczba reklam w korpusie
rzadkość = 0, gdy df ≤ 1, N ≤ 2 albo df > 0.30·N  ("hub", Config.max_df_frac)
```

Artefakt w 2 reklamach ma rzadkość 1.0, w ponad 30% korpusu — 0. Ślady o sile ≤ 0.005 są pomijane.

| Rodzaj | Waga | | Rodzaj | Waga |
|---|---|---|---|---|
| `tracking_id` | 0.90 | | `template` | 0.60 |
| `form_endpoint` | 0.90 | | `script` | 0.60 |
| `crypto` | 0.90 | | `transcript` | 0.55 |
| `phone` | 0.85 | | `ip` | 0.40 |
| `telegram` | 0.85 | | `nameserver` | 0.30 |
| `audio_fp` | 0.85 | | `keyword` | 0.15 |
| `cert` | 0.80 | | `asn` | 0.10 |
| `domain_final` | 0.75 | | `registrar` | 0.05 |
| `hidden_text` | 0.70 | | `person` | 0.00 |
| `domain_hop` | 0.65 | | inny (nieznany) | 0.20 |
| `favicon` | 0.60 | | | |

### 2. Ślady miękkie: podobieństwo

`ramp(x, lo, hi)` = 0 poniżej `lo`, 1 powyżej `hi`, liniowo pomiędzy. `cos` = podobieństwo cosinusowe.

| Rodzaj (`kind`) | Grupa | Siła | Warunek |
|---|---|---|---|
| `text` | `text` | `0.60 × ramp(cos, 0.75, 0.95)` | oba `text.embedding` |
| `audio_text` | `text` | `0.60 × ramp(cos, 0.75, 0.95)` | oba `audio.text_embedding` |
| `visual` | `visual` | `0.50 × ramp(cos, 0.80, 0.97)` | oba `clip_embedding` |
| `phash` | `phash` | `0.60 × (1 − ramp(h, 4, 12))` | h = liczba różnych bitów z 64, liczone gdy h < 12 |
| `face` | `face` | `0.50 × ramp(cos, 0.45, 0.85) × min(jakość_a, jakość_b)` | najlepsza para twarzy dwóch różnych reklam |
| `voice` | `voice` | `0.45 × ramp(cos, 0.55, 0.80)` | oba `speaker_embedding` |
| `audio_fp_sim` | `audio_fp` | `0.80 × ramp(1 − BER, 0.65, 0.85)` | BER = odsetek różnych bitów odcisku, najlepszy z przesunięć ±8 ramek, nakładka ≥ połowa krótszego |
| `regburst` | `regburst` | `0.50 × (1 − Δh / 2)` | ten sam `registrar` i daty rejestracji różne o mniej niż 2 h |

Twarz daje najwyżej 0.5, a głos najwyżej 0.45. Ten sam wizerunek lub sklonowany głos celebryty pojawia się
w wielu niezależnych kampaniach, więc sam nie może skleić dwóch reklam.

### 3. Grupy i łączenie

Ślady tej samej grupy opisują jedną informację, więc z każdej grupy liczy się **tylko najsilniejszy**.
Pozostałe są dopisywane w opisie jako `[+N podobnych śladów w tej grupie]`. Grupy wieloelementowe:

| Grupa | Rodzaje |
|---|---|
| `domain` | `domain_hop`, `domain_final` |
| `contact` | `phone`, `telegram`, `crypto` |
| `text` | `text`, `audio_text`, `transcript` |
| `audio_fp` | `audio_fp` (twardy), `audio_fp_sim` (miękki) |

Każdy inny rodzaj jest swoją własną grupą. Siły najsilniejszych śladów z różnych grup łączymy wzorem noisy-OR:

```
score = 1 − Π (1 − s_i)
```

Intuicja: `Π (1 − s_i)` to szansa, że **wszystkie** ślady są przypadkowe. Wynik zawsze mieści się w [0, 1],
każdy kolejny ślad podnosi go coraz mniej, a jeden słaby ślad nie da wysokiego wyniku. Przykłady:
0.5 i 0.5 → 0.75; 0.3 → 0.30; cokolwiek + 0.9 → co najmniej 0.90.

Para bez żadnego śladu ma score 0, czyli **brak dowodu, a nie dowód różnicy**. Silnik nie ma śladów ujemnych.

### 4. Co trafia dalej

- **HDBSCAN** dostaje pełną macierz `score` N×N (pary bez śladów = 0, przekątna = 1).
- **`edges.json` i Neo4j** dostają tylko krawędzie z `score ≥ min_edge` (domyślnie 0.25).

Wszystkie wagi i progi są w `Config` (`ftf_graph/scoring.py`). To ręcznie dobrane punkty startowe, a nie wartości wyuczone.

---

## Klastrowanie (HDBSCAN)

- Wejście: odległość `1 − score` (`ftf_graph/cluster.py`), `metric="precomputed"`.
- Biblioteka: pakiet `hdbscan`, a gdy nie jest zainstalowany — `sklearn.cluster.HDBSCAN`. Na danych testowych obie dają ten sam wynik.
- Parametry: `min_cluster_size` (`--min-cluster`, 3) i `min_samples` (`--min-samples`, 2).
- **Kampania musi mieć dowody.** Reklamy bez żadnych wspólnych śladów są od siebie równo odległe (odległość 1),
  a HDBSCAN potrafi uznać taką grupę za skupisko. Dlatego po klastrowaniu każda reklama musi mieć w swojej
  kampanii co najmniej jedną krawędź o score ≥ `min_edge`, inaczej trafia do szumu. Kampania, która po tym ma
  mniej niż `min_cluster_size` reklam, jest rozwiązywana. Bez tego zabezpieczenia wersja sklearn na danych
  testowych tworzyła fałszywą kampanię z trzech niezwiązanych reklam szumu.
- Wynik: etykieta kampanii albo `-1` (szum) oraz `strength` z `probabilities_` HDBSCAN-a. `strength` mówi, jak blisko „rdzenia” kampanii leży reklama — to **nie** jest pewność przypisania.
- Numeracja: kampanie są sortowane malejąco według liczby reklam i nazywane `CMP-1`, `CMP-2`, … **przy każdym uruchomieniu od nowa**, więc numer kampanii nie jest stały między przebiegami.

---

## Zaufane domeny

Domena z `data/trusted_domains.txt` (albo jej subdomena: `m.youtube.com` → `youtube.com`) **nie tworzy**
artefaktów `domain_hop`, `domain_final` ani `nameserver`, a w Neo4j nie powstaje dla niej węzeł `:Domain`.
Trafienia są zapisywane w `Card.trusted_hits` i `Ad.trusted_domains`. Lista **nie** wpływa na `ip`, `asn`,
`form_endpoint` ani kontakty.

Listę generuje `tools/build_trusted_list.py`:

1. pierwsze `--top` domen (domyślnie 10 000) z rankingu **Tranco** (`data/tranco_46YVX.csv`, format `pozycja,domena`),
2. dodaje `data/trusted_manual.txt` (ręczne uzupełnienia: CDN-y, trackery, polskie serwisy),
3. **usuwa platformy z treściami użytkowników** — wpisy z sekcji PRIVATE DOMAINS listy Public Suffix List
   (z pakietu `publicsuffixlist`) i każdą domenę, pod którą leży taki wpis (np. `s3.amazonaws.com` usuwa
   `amazonaws.com`). Na tych platformach subdomena (`krypto-bot.blogspot.com`) jest śladem oszusta,
4. usuwa domeny z Listy Ostrzeżeń CERT Polska, jeśli istnieje `data/cert_domains.txt`.

```bash
curl -o data/cert_domains.txt https://hole.cert.pl/domains/v2/domains.txt   # opcjonalnie
python tools/build_trusted_list.py --top 10000
```

Obecna wersja pliku: 9843 domeny, 158 platform usuniętych, bez listy CERT. Inną listę można wskazać zmienną
`FTF_TRUSTED_DOMAINS=ścieżka`.

---

## Puste pola i kompletność karty

- `null`, `""` i brak klucza nie tworzą artefaktu, a brakujący wektor nie bierze udziału w porównaniu.
  Dwie reklamy bez twarzy nie są przez to ani podobne, ani różne.
- `Card.signals()` zwraca, które z 8 rodzajów sygnałów karta ma: domeny, infrastruktura, śledzenie/skrypty,
  kontakty, tekst, wygląd, twarze, audio. W Neo4j to `Ad.signals` i `Ad.signals_present` (np. `"5/8"`).
  Demonstrator ostrzega, gdy nowa reklama ma 3 lub mniej rodzajów: brak kampanii może wtedy wynikać z braku danych.

---

## Wyniki

**Konsola:** liczba kart, krawędzi i kampanii; dla każdej kampanii okres, aktywne/martwe, liczba domen
docelowych, reklamy, osoby i 5 najczęstszych wspólnych artefaktów; lista reklam bez kampanii; przy `--query`
5 najsilniejszych krawędzi danej reklamy z powodami.

**`out/edges.json`** — lista krawędzi `score ≥ min_edge`:

```json
{"a": "A00", "b": "A02", "score": 1.0,
 "reasons": [{"kind": "audio_fp_sim", "hard": false, "strength": 0.8, "detail": "bardzo podobne nagranie audio (2% różnych bitów odcisku)"}, ...]}
```

**`out/campaigns.json`** — `campaigns` (dla każdej: `campaign`, `size`, `mean_edge_score`, `first_seen`,
`last_seen`, `alive`, `dead`, `sources`, `final_domains`, `persons`, `shared_artifacts`, `members` z `strength`),
`unassigned` i `clustering_backend`. `shared_artifacts` to artefakty z rzadkością > 0, które ma co najmniej
2 reklamy kampanii.

---

## Graf w Neo4j

| Węzeł | Właściwości | Skąd |
|---|---|---|
| `Ad` | `id`, `source`, `url`, `fetched_at`, `first_seen`, `last_seen`, `status`, `text`, `transcript`, `audio_duration_s`, `trusted_domains`, `signals`, `signals_present` | karta |
| `Domain` | `value` | łańcuch przekierowań, domena docelowa, SAN certyfikatu (bez zaufanych) |
| `IP`, `ASN`, `Registrar`, `Nameserver`, `Certificate`, `Favicon`, `TrackingID`, `Script`, `FormEndpoint`, `Phone`, `Telegram`, `CryptoAddress`, `Template`, `HiddenText`, `Keyword`, `Person`, `AudioFingerprint`, `Transcript` | `value`, `ads`, `rarity` | artefakty |
| `Campaign` | `id`, `size`, `mean_edge`, `first_seen`, `last_seen` | wynik HDBSCAN |

| Relacja | Właściwości |
|---|---|
| `(Ad)-[:USES]->(artefakt)` | `kind` |
| `(Ad)-[:STARTS_AT]->(Domain)` | pierwsza niezaufana domena łańcucha |
| `(Domain)-[:REDIRECTS_TO]->(Domain)` | `hop` |
| `(Ad)-[:LANDS_ON]->(Domain)` | domena docelowa |
| `(Certificate)-[:COVERS]->(Domain)` | |
| `(Ad)-[:SIMILAR]-(Ad)` | `score`, `has_hard_evidence`, `reasons` (lista tekstów) |
| `(Ad)-[:IN_CAMPAIGN]->(Campaign)` | `strength` |

Zachowanie przy kolejnych zapisach: węzły i relacje są tworzone przez `MERGE`, więc nic się nie dubluje,
a reklam i domen nic nie usuwa (stare kampanie łączą się z nowymi domenami przez wspólne piksele, favicony,
twarze). Usuwane są tylko wszystkie `IN_CAMPAIGN` (tworzone od nowa) oraz węzły `Campaign`, które zostały
bez reklam. `--wipe` czyści całą bazę.

Przydatne zapytania (Neo4j Browser):

```cypher
// kampanie i ich reklamy
MATCH (a:Ad)-[:IN_CAMPAIGN]->(k:Campaign) RETURN a, k;
// jedna kampania: reklamy i krawędzie podobieństwa między nimi
MATCH (a:Ad)-[:IN_CAMPAIGN]->(k:Campaign {id:'CMP-2'})<-[:IN_CAMPAIGN]-(b:Ad)
MATCH (a)-[s:SIMILAR]-(b) RETURN a, s, b;
// dlaczego reklama jest połączona z innymi
MATCH (a:Ad {id:'B03'})-[r:SIMILAR]-(b) RETURN b.id, r.score, r.reasons ORDER BY r.score DESC;
// rzadkie artefakty kampanii (uzasadnienie)
MATCH (k:Campaign {id:'CMP-1'})<-[:IN_CAMPAIGN]-(a:Ad)-[:USES]->(x) WHERE x.rarity > 0 RETURN k, a, x;
// pośrednicy w przekierowaniach
MATCH (s:Domain)-[:REDIRECTS_TO]->(d:Domain) RETURN d.value, count(s) AS wejscia ORDER BY wejscia DESC;
```

W Browserze kliknij etykietę `Ad` w wyniku i ustaw *Caption* na `id`, żeby widzieć `A00`, `B03` zamiast innych pól.

---

## Demonstrator (Streamlit)

`streamlit run app.py` (zależności: `requirements-app.txt`).

- **Nowa reklama:** wgranie `.json` (jedna karta albo lista kart) lub `.jsonl`, albo wybór z `data/new_ad_*.json`.
  Duplikat `ad_id` dostaje przyrostek (`-2`, `-3`…). Silnik przelicza cały korpus razem z nową reklamą
  i pokazuje jej kampanię albo informację, że nie pasuje, oraz 5 najsilniejszych powiązań z listą śladów.
  Przycisk **„Dopisz do korpusu”** dokleja kartę na koniec pliku JSONL; bez niego nic nie jest zapisywane.
- **Graf** (pyvis): ◆ kampanie, ● reklamy w kolorze kampanii (szare = szum), ★ czerwona = nowa reklama.
  Krawędź ciągła = jest co najmniej jeden ślad twardy, przerywana = tylko miękkie; grubość rośnie ze score.
  Dymki pokazują szczegóły i uzasadnienie.
- **Oś czasu** (plotly): każda reklama jako pasek `first_seen → last_seen` (brak lub błędne `last_seen` → +12 h),
  pogrupowane według kampanii. Reklamy bez `first_seen` nie są na osi.
- **Pasek boczny:** plik korpusu, `min_cluster_size`, `min_samples`, `min_edge`, pokazywanie krawędzi SIMILAR,
  pokazywanie szumu, ukrywanie reklam na zaufanych stronach, wysokość grafu.
- **Ukrywanie zaufanych:** reklama jest ukryta tylko wtedy, gdy jej domena docelowa jest zaufana **i** nie
  należy do żadnej kampanii **i** nie jest nowo wgrana. Film na YouTube powiązany z kampanią (np. tą samą twarzą) zostaje.

---

## Dane testowe

`tools/gen_sample_cards.py` tworzy 27 kart w zarezerwowanej domenie `.test`:

| Grupa | Reklamy | Co je łączy |
|---|---|---|
| A | 8 | różne domeny frontowe → wspólny pośrednik `track-hub.test`; wspólny piksel, endpoint formularza, telefon, skrypt; co druga ma twarz `prezenter_A` oraz to samo nagranie lektora (odcisk z drobnymi zmianami) i ten sam skrypt |
| B | 7 | **brak wspólnej infrastruktury**; ta sama twarz `prezenter_B`, podobny tekst, grafika (pHash, CLIP) i sklonowany głos |
| C | 6 | wspólny certyfikat, favicon, szablon, ukryty tekst, GA, skrypt, Telegram, serwery nazw; domeny zarejestrowane w odstępach 7 min; twarz `prezenter_A`; bez audio |
| N | 6 | szum: wspólny IP Cloudflare z grupą A, popularne słowa, losowe treści; część z rozmytą twarzą `prezenter_A`, część z losowym audio |

Wynik (`python -m ftf_graph data/sample_cards.jsonl`): **3 kampanie** (A, B, C), **6 reklam szumu**,
88 krawędzi. Między A i C są 24 krawędzie oparte **wyłącznie na twarzy** (score do 0.40), a wewnątrz kampanii
średnio 0.96 (A), 0.90 (B) i 1.00 (C), więc HDBSCAN ich nie skleja.

`tools/make_new_ad_examples.py` tworzy 3 nowe reklamy: `new_ad_krypto.json` trafia do kampanii C (favicon,
szablon, Telegram), `new_ad_usmiech.json` do kampanii B (twarz, głos, tekst, bez wspólnej infrastruktury),
a `new_ad_nieznana.json` zostaje bez kampanii.

---

## Struktura repozytorium

| Plik | Zawartość |
|---|---|
| `ftf_graph/card.py` | parsowanie karty, normalizacje, artefakty, zaufane domeny, `signals()` |
| `ftf_graph/scoring.py` | `Config` (wagi i progi), ślady twarde i miękkie, grupy, noisy-OR |
| `ftf_graph/cluster.py` | HDBSCAN + zabezpieczenie „kampania musi mieć dowody” |
| `ftf_graph/report.py` | podsumowanie kampanii, `edges.json`, `campaigns.json` |
| `ftf_graph/neo4j_store.py` | zapis do Neo4j (paczki `UNWIND`, `MERGE`) |
| `ftf_graph/__main__.py` | CLI |
| `app.py` | demonstrator Streamlit |
| `tools/gen_sample_cards.py`, `tools/make_new_ad_examples.py` | dane testowe |
| `tools/build_trusted_list.py` | generowanie listy zaufanych domen |
| `data/trusted_manual.txt` | ręczna lista zaufanych (edytuj ten plik) |
| `data/trusted_domains.txt` | wygenerowana lista zaufanych (nie edytuj ręcznie) |
| `data/tranco_46YVX.csv` | ranking Tranco (1 mln domen) |
| `docker-compose.yml` | Neo4j 5 |

---

## Znane ograniczenia

- **Wagi i progi są dobrane ręcznie.** Lepiej je wyuczyć (np. regresją logistyczną na ręcznie oznaczonych parach reklam).
- **Rzadkość karze też ślady tożsamościowe.** Piksel wspólny dla 8 z 27 reklam dostaje tylko 0.9 × 0.47 ≈ 0.42,
  a kampania obejmująca ponad 30% korpusu straciłaby wszystkie swoje ślady twarde (próg huba).
- **Pamięć i czas:** pełna macierz N×N i HDBSCAN na niej (ok. 200 MB przy 5000 reklam); porównanie odcisków audio to pętla po parach w Pythonie.
- **Pola nieużywane w wyniku:** `favicon.phash`, `text.ocr_text`, `faces[].deepfake_score`, `cert.san`
  (tylko w Neo4j), segmenty audio. Odcisk audio musi być w `fingerprint.array` — sam `key` nie jest obsługiwany.
- **Zaufane domeny działają na poziomie domeny.** Gdy `google.com` jest zaufane, strona na `sites.google.com`
  nie daje śladu domenowego (inne ślady, np. `form_endpoint` ze ścieżką, nadal działają). Popularność w rankingu nie oznacza bezpieczeństwa.
- **Numery kampanii** (`CMP-n`) zmieniają się między przebiegami.
- **Brak oceny ryzyka pojedynczej reklamy** (świeża domena, Lista Ostrzeżeń CERT, deepfake) — szum HDBSCAN-a to nie to samo.

---

## Licencje komponentów

numpy (BSD-3), scikit-learn (BSD-3), hdbscan (BSD-3), neo4j Python driver (Apache 2.0), Streamlit (Apache 2.0),
pyvis (BSD), plotly (MIT), pandas (BSD-3), publicsuffixlist (MPL 2.0; dane Public Suffix List — MPL 2.0),
ranking Tranco (cytowanie: Le Pochat i in., *Tranco: A Research-Oriented Top Sites Ranking Hardened Against
Manipulation*, NDSS 2019), Neo4j Community Edition (GPLv3, uruchamiany jako osobna usługa w Dockerze).
