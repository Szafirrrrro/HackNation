# Kontrakt danych i decyzji ScamGraph

Moduł wyszukiwania przechowuje kandydatów i historię powodów w SQLite. Rekord znaleziska wskazuje lokalny pakiet z oryginałem, lokalizatorem i sumą SHA-256. Karta wyłącznie katalogowa jest częściowym wynikiem. [Integracja schedulera](AD_DISCOVERY.md) · [Format pakietu](PAKIET_DOWODOWY.md)

To specyfikacja planowanego demonstratora. Para A przekazuje korpus i pochodzenie obserwacji. Para B zwraca cechy i mierzy wpływ metod. Para C buduje referencję, porównuje nowe materiały i wyświetla dowody. Import, CLI i GUI mają korzystać z tego samego silnika. [Plan MVP](MVP.md)

## Wejście i zgodność z v0

### Publikacja podczas pracy zegara

Decyzja `trusted_domain` dotyczy wizyty w stronie docelowej. Scheduler sprawdza host ustalony z oryginalnego CTA oraz cele przekierowań HTTP głównego dokumentu. Porównuje dokładne nazwy DNS, zapisane w postaci ASCII IDNA w tabeli `trusted_domains(domain)` prywatnej bazy schedulera. Każdą zaufaną subdomenę wprowadza się osobno. Karta oraz źródłowy odnośnik zachowują pochodzenie. Wpis `landing_visit.trusted_domain` identyfikuje trafienie. Odebrane wcześniej przekierowania zostają w HAR. Ocena treści pominiętej strony pozostaje nieznana.

**Filtry pominięcia wizyty (decyzja zespołu 2026-11-22).** Przed wizytą scheduler stosuje filtry w poniższej kolejności. Każdy następny liczy się tylko wtedy, gdy poprzedni nie trafił.
1. `trusted_domain`, jak wyżej.
2. `verified_entity` (TLD instytucji, certyfikat OV/EV). Łączy się z hostem poza kolektorem, dlatego działa tylko w trybie `live` i tylko przy `network_trust_checks: true` w profilu źródła. Domyślnie jest wyłączony.
3. `ranked_corpus`: dotyczy tylko celów typu `web`. Posty, Marketplace i wideo Facebooka nie są oceniane rankingiem. Domena rejestrowalna hosta mieści się w pierwszych 5000 pozycji `scamgraph/discovery/data/top-100k.csv` (Tranco). Domenę rejestrowalną wyznacza Public Suffix List z sekcją prywatną, z migawki w `tldextract` 5.4.0, offline. Subdomena użytkownika platformy z sekcji prywatnej (np. `*.netlify.app`, `*.s3.amazonaws.com`) jest osobną domeną i nie dziedziczy pozycji platformy. Ranking nie nadaje zaufania hostom wymienionym w `NEVER_TRUST_BY_RANK` i `MULTI_TENANT_HOSTS` ani ich subdomenom. Te listy obejmują skracacze i przekierowania, formularze, pliki i hosting na domenach głównych (np. `docs.google.com`, `sharepoint.com`, `amazonaws.com`), kreatory stron, komunikatory oraz serwisy społecznościowe i ogłoszeniowe. Listy są wyliczeniem, nie regułą: host tej klasy, którego na nich brakuje, zostanie pominięty, jeśli jest w rankingu. Bloklista nie jest jeszcze podłączona. Gdy zostanie podłączona, błąd jej sprawdzenia będzie oznaczał pobranie strony. Pochodzenie i data migawki rankingu wymagają opisu przez autora listy.
4. `bidirectional_verify` (pliki `.well-known`, pętla Wikidata). Ma te same warunki co punkt 2: tryb `live` i `network_trust_checks: true`.

Każde pominięcie zapisuje `reason_code` i `reason` w `landing_visit` i nie tworzy `AdPageLink`. Ranking ocenia adres z CTA przed przekierowaniem. Znane ograniczenie: otwarte przekierowania na domenach z rankingu (np. `www.google.com/url?q=…`) są dziś pomijane. Decyzja po przekierowaniu, dla skracaczy i dla takich adresów, pozostaje do wdrożenia.

Wejście do grafu zawiera ostatnią obserwację każdej pary dostawca–ID w danym trybie. Wpis z brakującym pakietem nosi pole `unavailable`. Po przywróceniu pakietu scheduler ponawia projekcję. Raport wylicza podobieństwa na dostępnych dowodach i osobno wymienia brakujące paczki.

Decyzja zespołu dla tekstu karty z potwierdzonym pochodzeniem: co najmniej cztery słowa i 24 znaki pozwalają wyliczyć znormalizowany wektor znakowych n-gramów długości 3–5 w obrębie słów (1024 wymiary, podpisany hashing). Pole `text.origin_id` wskazuje plik źródłowy cechy, a `text.method` wersję obliczenia. Silnik stosuje własne progi podobieństwa kosinusowego. Zgodność tekstu daje jedną miękką przesłankę, również gdy wiele fragmentów pochodzi z tego samego opisu. Próg długości i podobieństwo leksykalne wymagają oceny jakości na rzeczywistych kampaniach. Raport zachowuje wersję metody przy uzasadnieniu tekstowym.

Scheduler zatwierdza obserwację karty i zlecenie pobrania jej udokumentowanego celu w jednej transakcji SQLite. Od tego momentu analityk może otworzyć pakiet karty. Po zebraniu strony worker publikuje nowy pakiet dowodowy i aktualizuje wskazanie tej samej obserwacji. Numer obserwacji, emisja i powody wyszukania zachowują tożsamość. Stan wizyty oraz stan wyszukiwania źródła mają oddzielne pola. Po przerwaniu procesu zegar podejmuje niedokończone zlecenia. Tryby import i replay działają lokalnie.

W `landing/3` pole `pages[].reading_text` przechowuje tekst w kolejności DOM oraz lokalizator HTML dla każdego fragmentu. Opcjonalne `reading_source` wskazuje pierwotną odpowiedź HTTP, gdy dostarczyła treści pominiętej w zapisanym widoku. Manifest wymienia eksport TXT i jego sumę kontrolną w `derived_files`. Pełny zrzut, początkowy widok i kadr ograniczony rozmiarem mają osobne nazwy. W starszych paczkach dla skryptu zapisanego w ZIP pola HAR `_artifact`, `_member` i `_sha256` identyfikują oryginalną odpowiedź.

Wersja analizy `landing/2` rozróżnia pełne wypowiedzi w `opinions`, odznaki ocen zbiorczych w `pages[].rating_badges`, ceny w `pages[].prices` oraz saldo w `pages[].cart_balances`. Produkt powiązany z ceną ma własny dowód. Etykiety kupującego, oceny, liczniki i deklaracje skuteczności są danymi opublikowanymi przez źródło. Każde wystąpienie sygnału ma lokalizator i kontekst. Panel grupuje równe fragmenty w obrębie tego samego kontekstu. Pole `landing_summary` wskazuje dostępne dowody treści oferty, okna cookies i ocenionego obszaru zrzutu.

Przeliczenie zapisanych materiałów zachowuje identyfikator obserwacji, skróty oryginałów i historię pobrania. Nowy manifest wskazuje poprzedni pakiet i jego SHA-256 w `reanalyzed_from`.

| Obiekt | Co przyjmuje importer |
| --- | --- |
| Manifest | `manifest.json` zawiera `schema_version`, `dataset_id`, opis pochodzenia w `source_description` i `collected_at`. Identyfikatory lokalne mają zakres korpusu. Adapter obcego formatu zgłasza zastosowane mapowanie oraz pominięte pola. |
| `Ad` — jedna emisja | Jeden wiersz `ads.jsonl` ma stabilne `ad_id`, `source.kind` (`library`, `organizer`, `synthetic` lub `upload`), `source.provider`, czas pozyskania ze strefą w `source.collected_at` oraz przynajmniej jedno użyteczne pole spośród `text`, `image_path`, `landing_url`, `audio_path`, `video_path` (dwa ostatnie: nagranie lub wideo ze ścieżką dźwiękową, decyzja zespołu 2026-11-21). Opcjonalne `source.ad_ref` i `source.record_url` wskazują wpis u dostawcy, `advertiser_ref` identyfikuje reklamodawcę w jego systemie, a `observed_redirect_urls` przechowuje już zaobserwowane przekierowania. |
| `PageCapture` — jeden zapis strony | Adapter `observations/pages.jsonl` rozpoznaje `capture_id` i dostępne sekcje `html`, `document`, `har`, `dns_tls`, `assets`. Można wczytać sam zapis strony i porównać go z innymi stronami. Zachowujemy czas, status odpowiedzi, pola źródłowe i ich lokalizację. `bundle_ids` służą do odnalezienia oryginału. |
| `AdPageLink` — związek emisji z zapisem strony | Opcjonalny wiersz `observations/ad_page_links.jsonl` wskazuje `ad_id`, `capture_id`, `origin_id`, czas obserwacji powiązania w `observed_at` oraz `source_ref` z lokalizacją, polem źródłowym i jego wartością. Dopiero zweryfikowane powiązanie udostępnia cechy tego zapisu do porównań reklam. |
| Zgłoszenie z GUI | Adapter nadaje ID i `source.kind=upload`, zachowuje zwalidowane bajty i źródło każdego dodatkowego pola. Przyjmuje dostępny materiał do analizy także wtedy, gdy brakuje obrazu lub celu. |

Dotychczasowy korpus v0 można wczytać bez migracji. Brak opcjonalnego pliku relacji oznacza pusty zbiór powiązań. Sam adres celu wpisany przez użytkownika pozostaje porównywalnym polem z opisanym pochodzeniem. Wspólny host, katalog archiwum albo podobny tytuł mogą podpowiedzieć, które obserwacje sprawdzić. Przyjęcie `AdPageLink` wymaga wskazania dowodu pozwalającego prześledzić związek konkretnej emisji z konkretnym zapisem. Importer zgłasza niedostępny odnośnik, sprzeczność lub niejednoznaczny cel i zachowuje dostępne rekordy do oddzielnej analizy.

W pakiecie z pobrania celu CTA relacja w `extracted.json` wskazuje element i atrybut w oryginalnym zapisie karty oraz przez `navigation_evidence` indeks odpowiedzi dokumentu w lokalnym HAR. `final_url` podaje adres po przekierowaniach z pominięciem parametrów zapytania. Wypowiedzi ze strony wskazują element HTML w `landing/`. Nieudana próba pobrania strony zachowuje powód w `landing_visit` i dostępne artefakty.

**Klucze importu.** Powtórne wczytanie tego samego ID emisji jest idempotentne. Adapter uzgadnia `(source.provider, source.ad_ref)` z `(dataset_id, ad_id)`, gdy istnieją obie tożsamości. Odcisk stabilnych pól pomaga wykryć ponowny import obcego zapisu bez ID. Konflikt dwóch identyfikatorów trafia do raportu z wierszami źródłowymi. SHA-256 identyfikuje bajty i pozwala współdzielić ekstrakcję. Dwie znane emisje o różnych ID zachowują odrębne rekordy nawet przy tym samym obrazie. Dwa pobrania tego samego URL mogą mieć różny czas, status i treść.

**Pochodzenie.** `image_origin`, `text_origin`, `url_origin` i `audio_origin` w rekordzie v0 oraz `observation_group` ze zrzutu wskazują źródło cechy. Obraz, jego kadr, pHash, OCR i ręczna transkrypcja mają wspólny `origin_id`. Tak samo nagranie, jego odcisk akustyczny, odcisk głosu i transkrypcja mowy (ASR); domyślnie `<ad_id>#audio_path` lub `<ad_id>#video_path`. Domyślnie tekst do zdjęcia dziedziczy pochodzenie zdjęcia. Cel o nieudokumentowanym pochodzeniu można pokazać jako wskazówkę. Do niezależnych dowodów kwalifikują się tylko udokumentowane, rozłączne źródła po obu stronach porównania. Dwa wpisy HAR opisujące tę samą integrację dają jeden sygnał. Etykiety kampanii i uzasadnienia anotatorów należą do osobnego zbioru ewaluacyjnego.

**Błędy i czas.** Importer ogranicza ścieżki mediów do zadeklarowanego katalogu, sprawdza format i rozmiar obrazu, zwraca numer wiersza, ID oraz przyczynę błędu. Gdy obraz jest uszkodzony, nadal analizuje poprawny tekst. Odrębnie zapisuje datę publikacji, pozyskania i obserwacji strony wraz z precyzją źródła. Przy braku daty publikacji pole pozostaje puste.

### Przykład syntetyczny

Manifest i emisja poniżej używają formatu v0. Lokalny wyciąg z fikcyjnej biblioteki dokumentuje pole, z którego importer odczytał cel reklamy. Wszystkie adresy są danymi testowymi.

`manifest.json`

```json
{"schema_version":"v0","dataset_id":"demo","source_description":"Własny syntetyczny eksport jednej emisji i zapisu jej celu.","collected_at":"2026-11-21T10:05:00Z"}
```

`ads.jsonl`

```json
{"ad_id":"ad-1","source":{"kind":"synthetic","provider":"demo-library","ad_ref":"lib-7","collected_at":"2026-11-21T10:00:00Z"},"text":"Oferta próbna","landing_url":"https://sklep.example/oferta","url_origin":"export-7"}
```

`sources/library-export.jsonl` — przykład zachowanego dowodu w formacie dostawcy.

```json
{"id":"lib-7","destination_url":"https://sklep.example/oferta","observed_at":"2026-11-21T10:00:00Z"}
```

Adapter `PageCapture` czyta istniejący format `observations/pages.jsonl`. Czas żądania dokumentu jest zapisany w `har.document_started_at`.

```json
{"capture_id":"page-1","document":{"url_without_query":"https://sklep.example/oferta"},"har":{"document_started_at":"2026-11-21T10:01:00Z","document_status":200},"html":{"title":"Oferta próbna"}}
```

Rozszerzeniem jest osobny, opcjonalny plik `observations/ad_page_links.jsonl`. W tym przykładzie źródłowy wpis wskazuje jedną emisję i dokładny adres celu, który zapisano minutę później.

```json
{"ad_id":"ad-1","capture_id":"page-1","origin_id":"export-7","observed_at":"2026-11-21T10:01:00Z","source_ref":{"file":"sources/library-export.jsonl","record_id":"lib-7","field":"destination_url","value":"https://sklep.example/oferta"}}
```

## Od obserwacji do grupy

| Wynik | Co musi wyjaśniać |
| --- | --- |
| `Feature` i `Evidence` | Cecha wskazuje typ obiektu i jego ID, rodzinę (`text`, `visual`, `infrastructure`, `audio`), pole, wartość, `origin_id`, lokalizację źródła oraz wersję ekstraktora. Rodzina `audio` (decyzja zespołu 2026-11-21) obejmuje `audio.fingerprint` (Chromaprint) i `audio.speaker_embedding` (odcisk głosu); transkrypcja `asr.text` należy do rodziny `text`. Klasyfikację śladów audio jako twardych lub miękkich ustala para C. Dowód wskazuje oba końce porównania, relację, metrykę, zmierzoną wartość, próg i siłę sygnału. Zachowujemy oryginalne wartości obok normalizacji. |
| Podobieństwo kreacji i wzorzec stron | Identyczne bajty, powtórzona kreacja i podobieństwo dwóch zapisów stron mają osobne znaczenia w wyniku. Przy parze stron pokaż np. tekst nagłówków i ślad HAR wraz z ich źródłami. Można zwrócić te wyniki nawet wtedy, gdy brakuje danych do oceny kampanii. |
| `Edge` — ocena pary emisji | Zwraca `score` w przedziale 0–1, `has_hard_evidence` oraz listę `reasons`. Każdy powód ma `group`, `kind`, `hard`, `strength` i czytelny `detail`, malejąco według siły. Do grafu i eksportu trafiają pary z `score >= min_edge`. Do klastrowania liczą się wszystkie pary. |
| `Campaign` | Klaster HDBSCAN o identyfikatorze `CMP-<n>`, numerowany malejąco według liczby członków w danym przebiegu. Zawiera członków z `strength` (0–1, jak bardzo reklama należy do rdzenia klastra), średni `score` par wewnątrz klastra, okres aktywności, liczbę reklam aktywnych i martwych, źródła, domeny docelowe, osoby oraz wspólne ślady o niezerowej rzadkości z liczbą reklam, w których występują. Reklamy poza klastrami (`unassigned`, szum) pozostają widoczne. |
| `MatchResult` | Zawiera ID zapytania, odcisk korpusu referencji, konfigurację (`Config`, `min_cluster_size`, `min_samples`, `min_edge`), backend klastrowania, status, kampanię zapytania z `strength`, najsilniejsze krawędzie zapytania z powodami oraz listę braków karty zapytania. |

### Reguła silnika `ftf_graph` (decyzja zespołu 2026-11-21)

Zespół przyjmuje regułę zaimplementowaną w `graph/ftf_graph` (`scoring.py`, `cluster.py`) zamiast oceny `strong`/`similar`/`none` z grupowaniem complete-link. Kryteria NASK „jakość metody korelacji i grupowania” oraz „czytelność i interpretowalność prezentowanych powiązań” (pkt 9 zadania) obsługują `reasons` każdej krawędzi i profil kampanii. Wagi i progi poniżej są punktami startowymi zespołu, nie wynikiem pomiaru. Aktualne wartości są w `Config` w `scoring.py` i opisie w [README silnika](../graph/README.md).

**Ślady twarde.** Artefakt to dyskretna, znormalizowana wartość, która może powtórzyć się w innej reklamie: domena z łańcucha przekierowań lub docelowa, o ile nie jest hostem wspólnym, identyfikator śledzący, endpoint formularza, kontakt, certyfikat, favicona, szablon DOM, skrypt, IP, serwer nazw, o ile nie jest hostem wspólnym, rejestrator, słowo kluczowe, odcisk audio, transkrypcja. Wspólna wartość daje siłę `waga_rodzaju × rzadkość`, gdzie `rzadkość = log(N/df) / log(N/2)`. Artefakt obecny w jednej reklamie albo w ponad `max_df_frac` (30%) korpusu ma rzadkość 0.

**Ślady miękkie.** Podobieństwo w stopniu: embedding tekstu, embedding obrazu, odległość pHash, twarz ważona gorszą z dwóch jakości, hurtowa rejestracja domen, narracja lektora, głos lektora i przybliżony odcisk audio. Siła to `waga × ramp(miara, próg_dolny, próg_górny)`. Twarz sama daje najwyżej 0.5, a głos najwyżej 0.45, bo wizerunek i sklonowany głos celebryty występują w niezależnych kampaniach.

**Wynik pary.** Z każdej grupy śladów liczy się tylko najsilniejszy. Domeny z jednego łańcucha tworzą grupę `domain`, kontakty grupę `contact`, a tekst reklamy, narracja i transkrypcja lektora grupę `text`. Każdy inny rodzaj śladu stanowi osobną grupę. Najsilniejsze ślady z różnych grup łączymy jak niezależne dowody: `score = 1 − Π(1 − sᵢ)`.

**Kampanie.** HDBSCAN dostaje pełną macierz odległości `d = 1 − score`. Pary bez wspólnych śladów mają `d = 1`. Domyślnie `min_cluster_size = 3` i `min_samples = 2`. Silnik używa pakietu `hdbscan`, a przy jego braku `sklearn.cluster.HDBSCAN`. Wynik przebiegu zapisuje backend i parametry. Numeracja `CMP-<n>` obowiązuje tylko w danym przebiegu.

**Znane ograniczenia reguły.** Obraz i jego OCR z tego samego zrzutu mogą trafić do różnych grup i liczą się wtedy jako dwa ślady, choć mają wspólny `origin_id`. Jeden rzadki ślad twardy, np. piksel śledzący, sam daje wysoki `score`. Brak pola po jednej stronie daje siłę 0, więc „nie dało się porównać” wygląda tak samo jak „różne wartości”; tę różnicę pokazuje dopiero lista braków karty. Rzadkość zależy od składu korpusu, więc dodanie reklam może zmienić `score` istniejących par. Kampanie są hipotezą do oceny analityka. Trafność wymaga pomiaru na oznaczonym zbiorze (purity, pairwise F1).

### Odcisk struktury strony `dom-shingle-minhash-v1` (decyzja zespołu 2026-11-22)

**Gdzie powstaje.** `scamgraph/landing.py` liczy go dla każdego zapisu HTML (rola `html`) i zapisuje w `pages[].dom_template_minhash`. Cecha dotyczy jednej strony i nie zależy od składu korpusu. Te same bajty HTML dają ten sam wynik.

**Tokeny.** Drzewo parsera `Document` przechodzimy w kolejności dokumentu: `<tag` przy otwarciu, `</tag` przy zamknięciu. Elementy puste (`img`, `br`, `input` i in.) mają tylko token otwarcia. Pomijamy atrybuty, tekst i komentarze. Tagi elementów ukrytych (`script`, `template`, `noscript`, `svg` i in.) też są tokenami, bo należą do szablonu. Parser domyka `p` i `li` tak samo jak w pozostałej ekstrakcji.

**Odcisk.** Zbiór fragmentów po `k = 8` kolejnych tokenów, hash każdego fragmentu z SHA-256 i 128 minimów dla stałych permutacji wyprowadzonych z nazwy metody. Zapis: `{"method": "dom-shingle-minhash-v1", "k": 8, "num_perm": 128, "tokens": N, "shingles": M, "signature": [128 liczb 0…2³²−1]}`. Strona z mniej niż 8 albo ponad 50 000 tokenami ma `dom_template_minhash: null`, a przyczynę zapisujemy przy tej stronie w `dom_template_unavailable`. Górny limit ogranicza czas liczenia jednej strony do około sekundy. Brak odcisku nie trafia do `issues`, więc nie zmienia statusu `partial` obserwacji. Zapisy przeanalizowane przed tą zmianą nie mają klucza `dom_template_minhash`. `ANALYSIS_VERSION` (`landing/3`) nie zostało podbite, więc `reanalyze` ich nie uzupełni, dopóki właściciel analizy stron nie podbije wersji. Podbicie nadaje wszystkim zapisanym pakietom nowe `capture_id`.

**Porównanie.** `scamgraph.landing.template_similarity` zwraca odsetek pozycji, na których dwie sygnatury są równe. To estymator Jaccarda zbiorów fragmentów z błędem standardowym ok. 0,04 przy 128 permutacjach. Porównujemy tylko odciski o tej samej `method`, `k` i `num_perm`; w innym przypadku wynik to `null`.

**Karta grafu.** `discovery/graph_feed.py` przepisuje odcisk do `card.page.dom_template_minhash` tylko przy warunkach, które obowiązują dla `final_domain`, pikseli i skryptów: zweryfikowany `AdPageLink` i odpowiedź dokumentu 2xx. Pole trafia do karty, gdy pakiet ma dokładnie jeden odcisk. Kilka różnych odcisków pozostawia pole puste. Wersja eksportu to `graph-feed/4`.

**Znaczenie.** Odcisk mierzy podobieństwo w stopniu, nie równość. Pochodzi z tego samego zapisu strony co skrypty i piksele, więc nie jest od nich niezależnym dowodem. Obecny `ftf_graph` nie czyta tego pola, więc krawędzie i kampanie pozostają bez zmian. Włączenie odcisku do scorera (waga, próg, grupa śladu) jest osobną decyzją pary C po pomiarze na oznaczonych parach. Kontrola na 15 prywatnych zapisach stron z 2026-11-22 to sprawdzenie poprawności, nie pomiar trafności: odcisk różnił się od dokładnego Jaccarda najwyżej o 0,03.

## Decyzja dla nowej emisji

Zapytanie wczytujemy razem z kartami referencji i przeliczamy krawędzie oraz klastry na zbiorze referencja + zapytanie, tak jak `graph/app.py`. Wynik nie zmienia zapisanej referencji. Do referencji emisję dodaje osobna, jawna akcja. Pierwszy pasujący wiersz określa status (decyzja zespołu 2026-11-21).

| Kolejność | Warunek | Status | Komunikat dla analityka |
| --- | --- | --- | --- |
| 1 | Pusta referencja albo karta zapytania bez artefaktu i bez wektora, które silnik potrafi porównać | `insufficient_evidence` | Wskaż brakujące pola karty i przyczyny z `extraction.warnings`. |
| 2 | HDBSCAN przypisał zapytanie do kampanii | `probable_match` | Pokaż kampanię, `strength` zapytania, najsilniejsze krawędzie do jej członków z powodami i wspólne ślady profilu. |
| 3 | Zapytanie jest poza klastrami, ale ma co najmniej jedną krawędź `score >= min_edge` | `review_needed` | Pokaż najsilniejsze krawędzie z powodami i kampanie, do których należą ich drugie końce. |
| 4 | Brak krawędzi `score >= min_edge` | `no_match` | Możliwy nowy wzorzec względem tej referencji. Jedna emisja może rozpocząć dochodzenie. |

Ten sam zestaw kart referencji, to samo zapytanie i ta sama konfiguracja dają ten sam status, kampanię i krawędzie zapytania. Test odbiorowy sprawdza powtarzalność dwóch kolejnych zapytań A oraz to, że zapytanie B nie zmienia zapisanej referencji. Osobny test sprawdza wiersz 1 dla karty bez porównywalnych pól i wiersz 4 dla karty z polami, ale bez krawędzi powyżej progu. Przy pełnym przeliczeniu numer kampanii może się zmienić, dlatego eksport identyfikuje kampanię także listą członków.

## Lokalny korpus NASK

Adapter v0 może użyć obecnego katalogu od razu po implementacji. Inwentarz, przypadki do pokazu i źródła obserwacji zebrano w [przewodniku po danych](NASK_DATA.md). Sumy SHA-256 obrazów sprawdzisz zgodnie z [instrukcją repozytorium](../README.md).

## JSON przekazywany Emilce (adapter `feature-join-v2`)

Decyzja integracyjna zespołu 2026-11-21: wyjście Witka w `models/` pozostaje
bez zmian (`ads.jsonl`, `corpus.json`, `features/`, `runs/`, `vectors/`, `arrays/`).
Adapter `ftf_graph merge-features` materializuje cechy wybranej emisji i łączy je
z obserwacją URL/HTML/HAR. Nie uruchamia modeli ani pobierania sieciowego.

| Pole JSON-a | Źródło |
| --- | --- |
| `infra`, `page`, `provenance` | Obserwacje URL/HTML/HAR z `extract-snapshot`; brakujące RDAP/ASN/TLS pozostają puste. Włączenie do karty reklamy wymaga jawnego `--ad-page-link`. |
| `text`, `visual`, `faces` | Dotychczasowy adapter modeli obrazu i tekstu. DINOv2 pozostaje w `extensions.image_embedding`, nie w polu CLIP. |
| `audio.transcript`, `audio.segments`, `audio.asr_duration_s` | `asr.text`, `asr.segments`, `asr.duration_s` (Whisper). |
| `audio.duration_s` | `audio.duration_s` (Chromaprint, potencjalnie inny zakres nagrania). |
| `audio.fingerprint` | `audio.fingerprint`: obiekt z `array` jako listą int32, `key`, `shape`, `dtype`, `n_frames`. |
| `audio.speaker_embedding` | `audio.speaker_embedding` (ECAPA); lista liczb, bez rozpoznania nazwiska mówcy. |
| `audio.text_embedding` | `text.embedding` tylko dla `source_field=asr.text@<metoda>`; nie zastępuje embeddingu tekstu/OCR. |
| `extensions.model_features[]` | Wszystkie poprawne cechy modeli, również QR, ORB, dHash i pozostałe pola. Referencje `vector`/`array` zawierają listy zamiast odnośników wymagających plików bocznych. Oryginalne metadane i ścieżki są w evidence. `grouping:false` pozostaje informacją, bez promocji do pól korelacyjnych. |
| `extensions.model_unavailable[]`, `extraction.warnings` | Przyczyny braków oraz odrzuconych, nieaktualnych lub niejednoznacznych wyników. |
| `extraction.evidence` | Źródło, wiersz cechy, metoda, parametry, rodzina, pochodzenie, ID emisji i fingerprint korpusu. |

Audio i jego transkrypcja/embedding tekstowy dzielą `audio_origin` (domyślnie
`<ad_id>#audio_path` lub `#video_path`). Brak audio daje puste pola, nigdy odcisk
ciszy. Obraz nadal wymaga potwierdzenia SHA-256 jawnie wybranego zrzutu; wejście
bez obrazu może zostać połączone po jawnym ID korpusu. Zachowujemy różne emisje
nawet dla identycznych mediów. Konflikt ID, fingerprintu, pochodzenia lub metody
nie jest rozstrzygany na podstawie kolejności plików.

Bez `AdPageLink` strona trafia do `extensions.page_observation`, a `infra/page`
reklamy pozostają puste. Podobieństwo tytułu, nazwa katalogu i wspólny screenshot
nie potwierdzają przejścia z reklamy do strony. Link przekazany przez wywołującego
musi mieć `ad_id`, `capture_id`, `origin_id`, `observed_at` i `source_ref` z plikiem,
polem oraz URL odpowiadającym URL snapshotu. Wywołujący odpowiada za rzeczywistą
weryfikację wskazanego dowodu; adapter sprawdza zgodność deklaracji.

To kompletny **format przekazania cech**, nie zmiana reguły punktowania. Obecny
`Scorer` nie porównuje jeszcze audio ani DINOv2; Emilka otrzymuje audio przez
`Card.audio`, pozostałe cechy przez `Card.raw`. Progi podobieństwa audio i włączenie
ich do decyzji kampanii wymagają odrębnej implementacji i pomiaru.

Komendy i własny przykład syntetyczny: [instrukcja integracji](../graf/ftf-graph-py/HANDOFF.md).

## Zapis jednej wizyty HTTP

Każde sprawdzenie adresu dostaje osobny katalog `pages/<id_pobrania>/` w prywatnym katalogu stanu. Transport pobiera główną odpowiedź przed uruchomieniem Chrome. `original/response.*` przechowuje jej bajty, `page.html` przechowuje DOM po wykonaniu JavaScriptu, a `screenshot.png` pierwszy zapis viewportu. Zasoby mają własny katalog `page_files/`. `metadata.json` przechowuje pełne adresy, czas UTC, viewport i wynik. `network.har` zachowuje także ślad przekierowań, odrzuconych żądań oraz obu prób po przejściowym timeoucie lub 5xx. `document_entry` wskazuje odpowiedź końcowej próby, gdy udało się ją odebrać w całości.

Techniczny `status` zachowuje wartości `success`, `partial` i `failed`. Nowe pola `target_kind`, `content_status` i `reason_code` opisują typ oraz dostępność treści. Na przykład wynik WWW z HTML-em oferty i niedostępnym zasobem ma `content_status: usable` oraz techniczny `status: partial`. Wizyta z HTTP 200 zwracająca ekran logowania ma `content_status: blocked`. Plik PDF, obraz albo obsługiwane audio/wideo otrzymuje ocenę na podstawie zweryfikowanego pliku. `content_evidence` w pakiecie wskazuje plik i jego SHA-256 oraz lokalizator dokumentu, jeśli dotyczy. Zapisany obraz lub film może uzupełnić dowód publicznego obiektu Facebooka z potwierdzonym ID.

Paczka jest prywatnym źródłem. Samodzielna wizyta nie tworzy relacji z emisją. Scheduler wiąże kartę z paczką na podstawie elementu i atrybutu odnośnika oraz wpisu HAR. `target_basis` podaje pochodzenie wyboru celu (`label`, `preview` albo `analyst`). Użyteczne WWW trafia do `ad_page_links` i może zasilić graf. Dla potwierdzonych plików i publicznych obiektów Facebooka `ad_target_link` zachowuje ten sam ślad dowodowy. Wcześniejsze pakiety pozostają czytelne i mogą nie mieć nowych pól oceny.

### Ręczne zapytanie URL w ekranie grafu (decyzja zespołu 2026-11-22)

`scamgraph.url_capture.page_graph_card` automatycznie przekształca JSON ekstrakcji
w zapytanie dla `ftf_graph`. Pole zgodności `ad_id` ma wartość `page:<capture_id>`,
a `provenance.record_kind = page_capture` oznacza samodzielną obserwację strony.
Nie powstaje emisja ani `AdPageLink`. Dla użytecznej strony WWW z HTTP 2xx
zapytanie zawiera własną domenę końcową, jednoznaczny piksel Meta i sumy zapisanych
skryptów. Pełne dane z pochodzeniem pozostają w `extensions.page_observation`.
Tekst strony nie dostaje embeddingu innej metody niż korpus, a czas wizyty nie
zastępuje publikacji. Ekran automatycznie porównuje zapytanie z wybranym korpusem;
trwałe dopisanie wymaga osobnego kliknięcia. Błędy i blokady nie tworzą zapytania.

Decyzja zespołu: formularz przed pobraniem sprawdza URL w wybranym korpusie grafu.
Istniejące rekordy są wyróżniane bez nowej wizyty, zapytania lub zapisu. Nowa karta
zachowuje `provenance.url_key` (SHA-256 z URL po normalizacji hosta/IDNA, portu
domyślnego i pustej ścieżki, bez fragmentu). Schemat, ścieżka i parametry query
pozostają rozróżniane; klucz nie ujawnia parametrów w karcie. Starsze karty z pełnym
`provenance.url` są porównywane tą samą metodą. Dawne obserwacje zawierające tylko
host/ścieżkę dopasowujemy przy braku query i redakcji ścieżki, bez rozróżnienia
HTTP/HTTPS. Sama zgodność domeny nie wystarcza. Po zapisie znika aktywne zapytanie,
a wyróżniony zostaje zapisany rekord. Nie zmienia to deduplikacji emisji silnika.

Korekta decyzji zespołu 2026-11-22: ręczne żądanie analityka zawsze uruchamia
pobranie, niezależnie od rankingu domen. Nie zwracamy klasyfikacji bezpieczeństwa
na podstawie popularności. Polityka automatycznego schedulera pozostaje osobna.
Pobranie i ślad w grafie to osobne decyzje. Host wspólny nie jest śladem, co nie
oznacza, że jest bezpieczny. Kolejność: blokada CERT zawsze daje ślad. Dalej
rozstrzyga najdłuższy sufiks: platforma nie jest śladem, a jej subdomena jest,
host wspólny i domena z top 10 000 lub listy ręcznej nie są śladem razem
z subdomenami. Platformy wyznaczają `TENANT_PARENTS` i prywatna sekcja PSL
w przypiętej wersji. Reguła dotyczy przekierowań, celu i serwerów nazw,
nie certyfikatu, IP ani skryptów.

Korekta zapisu: przycisk **Dopisz** nigdy nie zmienia wybranego źródłowego JSONL.
Dodaje materiał do `.private-discovery/analyst/corpora/<klucz-ścieżki-korpusu>.jsonl`,
ignorowanego przez Git. Ten prywatny dodatek jest odczytywany z wybraną referencją
również po restarcie. Klucz rozdziela dodatki dla różnych ścieżek korpusów.
Pełny tekst, OCR i lokalne ścieżki pozostają prywatne, tak samo jak zapis pobrania.

### Zapytanie zdjęcia w ekranie grafu (decyzja zespołu 2026-11-22)

`scamgraph.image_query` przyjmuje PNG/JPEG/WebP (20 MiB, 32 MP, pojedynczy kadr).
Oryginalne bajty zapisuje prywatnie po SHA-256. Karta `image:<sha256[:24]>`
ma `provenance.source=upload`, `record_kind=image_query` i wskazanie obrazu.
To zgłoszenie materiału, bez wymyślonego ID dostawcy, daty emisji i `AdPageLink`.
`visual.sha256`, `visual.phash`, `visual.origin_id`, `text.ocr_text` oraz
`text.ocr_origin_id` są wejściem tej ścieżki dla silnika grafu. Tekst może być
odczytem lokalnego OCR albo tekstem źródłowym referencji, z oznaczoną metodą.
`extraction.evidence[]` zapisuje pole, `origin_id`, `source_ref` i `method_version`;
odczyt OCR zachowuje lokalizatory linii. `extraction.warnings` wyjaśnia brak OCR.

GUI automatycznie dołącza dostępny lokalny korpus NASK, bez pola ścieżki w formularzu.
Przy jego braku pozostają karty z wybranego korpusu grafu. Adapter programowy
nadal przyjmuje jawny katalog korpusu v0 lub luźnych plików. ID w grafie to
`reference:<dataset_id>:<ad_id>`; oryginalne ID pozostaje w `provenance.original_ad_id`.
Duplikat ID jest idempotentny; różne emisje tego samego pliku są zachowane.
Niepoprawny obraz nie usuwa poprawnego tekstu. Ścieżki wychodzące poza katalog
referencji nie są dopuszczane. Referencje są dołączane na czas aktywnego zapytania.

SHA jest osobnym sygnałem ponownego użycia pliku o sile 0,95, bez filtra rzadkości.
pHash64 i TF-IDF `char_wb` 3–5 korzystają z dotychczasowych progów opisanych
w instrukcji grafu. Słownik i IDF powstają tylko z referencji; zapytanie jest
transformowane. SHA/pHash i tekst o wspólnym pochodzeniu po obu stronach pary
wchodzą do jednej grupy dowodowej (maksimum). Linki z OCR nie stają się
potwierdzoną stroną docelową. DINOv2 pozostaje poza tą ścieżką; nie trafia do CLIP.
Zapis zgłoszenia przyciskiem **Dopisz** zmienia jego `record_kind` na
`image_reference`, zachowując ID, źródło i dowody. Ponowny import tego zgłoszenia
nie mnoży rekordów. Klastrowanie pozostaje dotychczasowym HDBSCAN demonstratora;
pełna reguła niezależnego przypisania kampanii wymaga dalszej integracji.
