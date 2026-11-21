# ftf-graph — silnik łączenia reklam w kampanie (Follow the Fake)

Wczytuje **karty reklam** (JSONL, jedna reklama na linię), liczy krawędzie podobieństwa
**z uzasadnieniem**, grupuje reklamy w kampanie algorytmem **HDBSCAN** i eksportuje graf do **Neo4j**.

```
karty.jsonl ──► artefakty + wektory ──► krawędzie SIMILAR (score + powody) ──► HDBSCAN ──► kampanie
                                                                              └──► graph.cypher (Neo4j)
```

## Budowanie i uruchomienie

```bash
python3 tools/gen_sample_cards.py          # 27 syntetycznych kart -> data/sample_cards.jsonl
cmake -S . -B build && cmake --build build
./build/ftf-graph data/sample_cards.jsonl --query B03
```

Opcje: `--out DIR` (domyślnie `out`), `--min-cluster N` (3), `--min-samples K` (2),
`--min-edge X` (0.25), `--query AD_ID` (wyjaśnia, do której kampanii pasuje reklama i dlaczego).

Wynik:
- `out/edges.json` — każda krawędź: `score` + lista `reasons` (`kind`, `hard`, `strength`, `detail`)
- `out/campaigns.json` — kampanie: członkowie, okres aktywności, aktywne/martwe, domeny, osoby, wspólne ślady
- `out/graph.cypher` — skrypt do załadowania grafu

## Załadowanie do Neo4j

Neo4j nie ma oficjalnego sterownika C++, dlatego silnik generuje plik Cypher:

```bash
docker run -d -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/hackathon123 neo4j:5
cypher-shell -a bolt://localhost:7687 -u neo4j -p hackathon123 -f out/graph.cypher
```

Model grafu:

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
`(Domain)-[:REDIRECTS_TO]->(Domain)`, `(Ad)-[:LANDS_ON]->(Domain)`, `(Certificate)-[:COVERS]->(Domain)`,
`(Ad)-[:SIMILAR {score, reasons, has_hard_evidence}]-(Ad)`, `(Ad)-[:IN_CAMPAIGN {strength}]->(Campaign)`.
Każdy artefakt ma `ads` (w ilu reklamach występuje) i `rarity` (0–1).

Przykładowe zapytania:

```cypher
// kampania z jej śladami
MATCH (k:Campaign {id:'CMP-1'})<-[:IN_CAMPAIGN]-(a:Ad)-[:USES]->(x) WHERE x.rarity > 0 RETURN k,a,x;
// dlaczego reklama jest połączona z innymi
MATCH (a:Ad {id:'B03'})-[r:SIMILAR]-(b) RETURN b.id, r.score, r.reasons ORDER BY r.score DESC;
// wąskie gardła przekierowań (pośrednicy, do których prowadzi wiele domen)
MATCH (s:Domain)-[:REDIRECTS_TO]->(d:Domain) RETURN d.value, count(s) AS wejscia ORDER BY wejscia DESC;
// oś czasu kampanii
MATCH (a:Ad)-[:IN_CAMPAIGN]->(:Campaign {id:'CMP-1'}) RETURN a.first_seen, a.id, a.status ORDER BY a.first_seen;
```

Martwych reklam i domen **nie usuwamy** (`status`, `first_seen`, `last_seen`): nowe domeny łączą się
ze starymi kampaniami przez wspólne piksele, favicony, szablony i twarze.

## Jak liczony jest wynik krawędzi

Każdy wspólny ślad daje siłę `s ∈ [0,1]`, a ślady łączymy jak niezależne dowody (noisy-OR):

```
score = 1 − Π (1 − s_i)
```

**Ślady twarde** (ta sama wartość = wspólny węzeł): `s = waga_rodzaju × rzadkość`.
Rzadkość = `log(N/df) / log(N/2)`: artefakt w 2 reklamach ≈ 1, artefakt w ponad 30% korpusu
(Cloudflare, popularne słowa) = 0. Wagi rodzajów są w `Config::base` (`src/scoring.hpp`):
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
- Krawędzie poniżej `min_edge` nie trafiają do grafu.

Wszystkie progi i wagi to punkty startowe. Stroimy je na ręcznie oznaczonym zbiorze (purity, pairwise F1).

## HDBSCAN

Własna implementacja na grafie rzadkim (`src/hdbscan.hpp`), bez macierzy odległości N×N:
`d = 1 − score` → odległość core → mutual reachability → MST (Kruskal) → drzewo skondensowane →
wybór klastrów EOM. Rozłączne składowe grafu są zawsze osobnymi klastrami. Reklamy bez kampanii
trafiają do `unassigned`. `strength` w `IN_CAMPAIGN` mówi, jak „rdzeniowa” jest reklama w kampanii.

## Scenariusz testowy (`tools/gen_sample_cards.py`)

- **A** — różne domeny frontowe → wspólny pośrednik `track-hub.test`, wspólny piksel, formularz, telefon
- **B** — „siedem domen, ten sam uśmiech”: zero wspólnej infrastruktury, ta sama osoba, podobny tekst i grafika
- **C** — wspólny certyfikat (SAN), favicon, szablon, ukryty tekst, domeny kupione w ciągu godziny
- **N** — szum: Cloudflare, popularne słowa, rozmyta twarz

Wynik: 3 kampanie i 6 reklam szumu. **A i C pozostają rozdzielone**, choć obie używają tej samej
twarzy (`prezenter_A`). Między nimi jest 20 krawędzi ≈ 0.40 opartych wyłącznie na twarzy, a wewnątrz
kampanii krawędzie mają ≈ 0.96–1.00, więc HDBSCAN uznaje je za osobne skupiska.

## Format karty

Pełny przykład: `data/example_card.json`. Pola opcjonalne mogą być `null` albo pominięte.
Na hackathonie wektory można trzymać inline. Przy dużym korpusie lepiej trzymać je w osobnym
pliku `.npy` lub parquet z kolumną `ad_id` (wtedy trzeba dopisać ładowanie w `card.hpp`).

## Integracja z resztą (Python / Streamlit)

Ekstraktory (crawler, OCR, twarze, CLIP) zapisują karty do JSONL, a Streamlit wywołuje silnik:

```python
subprocess.run(["./build/ftf-graph", "cards.jsonl", "--query", ad_id], capture_output=True, text=True)
```

i czyta `out/campaigns.json` oraz `out/edges.json`.

## Skalowanie

Pary liczone są O(N²), co wystarcza do kilku tysięcy reklam. Przy większej skali: indeks odwrotny
artefaktów (ślady twarde) + kNN/FAISS na wektorach (ślady miękkie) zamiast wszystkich par.

## Licencje

- `third_party/nlohmann/json.hpp` — nlohmann/json 3.11.3, licencja MIT
- kod silnika — do ustalenia przez zespół (np. MIT)
