# ftf-graph — silnik łączenia reklam w kampanie (Follow the Fake)

Wczytuje **karty reklam** (JSONL, jedna reklama na linię), liczy krawędzie podobieństwa
**z uzasadnieniem**, grupuje reklamy w kampanie algorytmem **HDBSCAN** i zapisuje graf do **Neo4j**.

```
karty.jsonl ──► artefakty + wektory ──► score par (z powodami) ──► HDBSCAN ──► kampanie
                                                                            └──► Neo4j (sterownik neo4j)
```

## Instalacja i uruchomienie

```bash
pip install -r requirements.txt
python tools/gen_sample_cards.py                       # 27 syntetycznych kart -> data/sample_cards.jsonl
python -m ftf_graph data/sample_cards.jsonl --query B03
```

Z zapisem do Neo4j:

```bash
docker compose up -d                                   # Neo4j 5, Browser: http://localhost:7474
python -m ftf_graph data/sample_cards.jsonl --neo4j bolt://localhost:7687 --neo4j-password hackathon123 --wipe
```

Opcje: `--out DIR` (domyślnie `out`), `--min-cluster N` (3), `--min-samples K` (2), `--min-edge X` (0.25),
`--query AD_ID` (wyjaśnia, do której kampanii pasuje reklama i dlaczego), `--neo4j URI`, `--neo4j-user`,
`--neo4j-password` (albo zmienne `NEO4J_USER` / `NEO4J_PASSWORD`), `--wipe` (czyści bazę przed zapisem — tylko do demo).

Wynik:
- `out/edges.json` — każda krawędź: `score` + lista `reasons` (`kind`, `hard`, `strength`, `detail`)
- `out/campaigns.json` — kampanie: członkowie, okres aktywności, aktywne/martwe, domeny, osoby, wspólne ślady

Użycie z kodu (np. ze Streamlita):

```python
from ftf_graph.card import load_cards
from ftf_graph.scoring import Scorer
from ftf_graph.cluster import cluster
from ftf_graph.report import summarize

cards = list(load_cards("cards.jsonl"))
sc = Scorer(cards)
scores, edges = sc.score_all()
res = cluster(scores)
campaigns, label_to_id = summarize(cards, scores, res, sc)
```

## Struktura

| Plik | Co robi |
|---|---|
| `ftf_graph/card.py` | parsowanie karty, normalizacja domen, wyciąganie artefaktów |
| `ftf_graph/scoring.py` | wagi, ślady twarde i miękkie, noisy-OR, uzasadnienia (numpy) |
| `ftf_graph/cluster.py` | HDBSCAN (`hdbscan`, a gdy go brak — `sklearn.cluster.HDBSCAN`) |
| `ftf_graph/report.py` | podsumowanie kampanii, zapis JSON |
| `ftf_graph/neo4j_store.py` | zapis grafu do Neo4j (paczki UNWIND, idempotentne MERGE) |
| `ftf_graph/__main__.py` | CLI |
| `tools/gen_sample_cards.py` | syntetyczny scenariusz testowy |

## Model grafu w Neo4j

| Węzeł | Skąd |
|---|---|
| `Ad` | jedna karta = jedna reklama |
| `Domain` | każda domena z łańcucha przekierowań + domeny z certyfikatu (SAN) |
| `IP`, `ASN`, `Registrar`, `Nameserver`, `Certificate`, `Favicon` | infrastruktura |
| `TrackingID`, `Script`, `FormEndpoint`, `Template`, `HiddenText` | strona |
| `Phone`, `Telegram`, `CryptoAddress` | kontakty |
| `Keyword`, `Person` | treść i twarze |
| `Campaign` | wynik HDBSCAN |

Relacje: `(Ad)-[:USES {kind}]->(artefakt)`, `(Ad)-[:STARTS_AT]->(Domain)`,
`(Domain)-[:REDIRECTS_TO {hop}]->(Domain)`, `(Ad)-[:LANDS_ON]->(Domain)`, `(Certificate)-[:COVERS]->(Domain)`,
`(Ad)-[:SIMILAR {score, reasons, has_hard_evidence}]-(Ad)`, `(Ad)-[:IN_CAMPAIGN {strength}]->(Campaign)`.
Każdy artefakt ma `ads` (w ilu reklamach występuje) i `rarity` (0–1).

Martwych reklam i domen **nie usuwamy** (`status`, `first_seen`, `last_seen`): nowe domeny łączą się
ze starymi kampaniami przez wspólne piksele, favicony, szablony i twarze. Przy każdym przeliczeniu
zmieniają się tylko przypisania `IN_CAMPAIGN` i węzły `Campaign`.

Przykładowe zapytania (Neo4j Browser):

```cypher
// kampania z jej rzadkimi śladami
MATCH (k:Campaign {id:'CMP-1'})<-[:IN_CAMPAIGN]-(a:Ad)-[:USES]->(x) WHERE x.rarity > 0 RETURN k,a,x;
// dlaczego reklama jest połączona z innymi
MATCH (a:Ad {id:'B03'})-[r:SIMILAR]-(b) RETURN b.id, r.score, r.reasons ORDER BY r.score DESC;
// wąskie gardła przekierowań (pośrednicy, do których prowadzi wiele domen)
MATCH (s:Domain)-[:REDIRECTS_TO]->(d:Domain) RETURN d.value, count(s) AS wejscia ORDER BY wejscia DESC;
// oś czasu kampanii
MATCH (a:Ad)-[:IN_CAMPAIGN]->(:Campaign {id:'CMP-1'}) RETURN a.first_seen, a.id, a.status ORDER BY a.first_seen;
```

## Jak liczony jest wynik krawędzi

Każdy wspólny ślad daje siłę `s ∈ [0,1]`, a ślady łączymy jak niezależne dowody (noisy-OR):

```
score = 1 − Π (1 − s_i)
```

**Ślady twarde** (ta sama wartość = wspólny węzeł): `s = waga_rodzaju × rzadkość`.
Rzadkość = `log(N/df) / log(N/2)`: artefakt w 2 reklamach ≈ 1, artefakt w ponad 30% korpusu
(Cloudflare, popularne słowa) = 0. Wagi rodzajów są w `Config.base` (`scoring.py`):
piksel/GA i endpoint formularza 0.90, telefon/Telegram 0.85, certyfikat 0.80, strona docelowa 0.75,
ukryty tekst 0.70, domena w łańcuchu 0.65, favicon/szablon/skrypt 0.60, IP 0.40, … rejestrator 0.05.

**Ślady miękkie** (stopień podobieństwa):

| Sygnał | Siła |
|---|---|
| tekst (embedding) | `0.6 × ramp(cos, 0.75, 0.95)` |
| wygląd (CLIP/SigLIP) | `0.5 × ramp(cos, 0.80, 0.97)` |
| pHash grafiki | `0.6 × (1 − ramp(bity_różnicy, 4, 12))` |
| twarz (ArcFace) | `0.5 × ramp(cos, 0.45, 0.85) × min(jakość_a, jakość_b)` |
| hurtowa rejestracja | ten sam rejestrator i różnica < 2 h: `0.5 × (1 − Δh/2)` |

Zasady:
- **Twarz sama daje najwyżej 0.5.** Celebryta pojawia się w wielu niezależnych kampaniach, więc
  łączy dopiero razem z narracją albo infrastrukturą. Rozmazana twarz (niska jakość) waży mniej.
- **Max na grupę.** Trzy wspólne domeny z jednego łańcucha to jeden dowód, a nie trzy
  (grupy `domain` i `contact`).
- Do grafu trafiają krawędzie `>= min_edge`. HDBSCAN dostaje pełną macierz `d = 1 − score`
  (pary bez wspólnych śladów mają `d = 1`).

Wszystkie progi i wagi to punkty startowe. Stroimy je na ręcznie oznaczonym zbiorze (purity, pairwise F1).

## Scenariusz testowy (`tools/gen_sample_cards.py`)

- **A** — różne domeny frontowe → wspólny pośrednik `track-hub.test`, wspólny piksel, formularz, telefon
- **B** — „siedem domen, ten sam uśmiech”: zero wspólnej infrastruktury, ta sama osoba, podobny tekst i grafika
- **C** — wspólny certyfikat (SAN), favicon, szablon, ukryty tekst, domeny kupione w ciągu godziny
- **N** — szum: Cloudflare, popularne słowa, rozmyta twarz

Wynik (identyczny dla `hdbscan` i `sklearn`): 3 kampanie i 6 reklam szumu. **A i C pozostają
rozdzielone**, choć obie używają tej samej twarzy (`prezenter_A`). Między nimi są krawędzie ≈ 0.40
oparte wyłącznie na twarzy, a wewnątrz kampanii ≈ 0.96–1.00.

## Format karty

Pełny przykład: `data/example_card.json`. Pola opcjonalne mogą być `null` albo pominięte.
Wszystkie wektory jednego rodzaju muszą mieć ten sam wymiar.

## Skalowanie

Ślady twarde liczone są przez indeks odwrotny, a miękkie przez mnożenie macierzy (numpy).
HDBSCAN dostaje gęstą macierz N×N, co wystarcza do kilku tysięcy reklam (5000 reklam ≈ 200 MB).
Przy większej skali: kNN (FAISS) na wektorach i HDBSCAN na grafie rzadkim albo Leiden w Neo4j GDS.

## Licencje komponentów

numpy (BSD-3), scikit-learn (BSD-3), hdbscan (BSD-3), neo4j Python driver (Apache 2.0),
Neo4j Community Edition (GPLv3, uruchamiany jako osobna usługa w Dockerze).
