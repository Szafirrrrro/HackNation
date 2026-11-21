# Kontrakt danych i decyzji ScamGraph

Moduł wyszukiwania przechowuje kandydatów i historię powodów w SQLite. Rekord znaleziska wskazuje lokalny pakiet z oryginałem, lokalizatorem i sumą SHA-256. Karta wyłącznie katalogowa jest częściowym wynikiem. [Integracja schedulera](AD_DISCOVERY.md) · [Format pakietu](PAKIET_DOWODOWY.md)

To specyfikacja planowanego demonstratora. Para A przekazuje korpus i pochodzenie obserwacji. Para B zwraca cechy i mierzy wpływ metod. Para C buduje referencję, porównuje nowe materiały i wyświetla dowody. Import, CLI i GUI mają korzystać z tego samego silnika. [Plan MVP](MVP.md)

## Wejście i zgodność z v0

### Publikacja podczas pracy zegara

Decyzja `trusted_domain` dotyczy wizyty w stronie docelowej. Scheduler sprawdza host ustalony z oryginalnego CTA oraz cele przekierowań HTTP głównego dokumentu. Porównuje dokładne nazwy DNS, zapisane w postaci ASCII IDNA w tabeli `trusted_domains(domain)` prywatnej bazy schedulera. Każdą zaufaną subdomenę wprowadza się osobno. Karta oraz źródłowy odnośnik zachowują pochodzenie. Wpis `landing_visit.trusted_domain` identyfikuje trafienie. Odebrane wcześniej przekierowania zostają w HAR. Ocena treści pominiętej strony pozostaje nieznana.

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
| `Feature` i `Evidence` | Cecha wskazuje typ obiektu i jego ID, rodzinę (`text`, `visual`, `infrastructure`, `audio`), pole, wartość, `origin_id`, lokalizację źródła oraz wersję ekstraktora. Rodzina `audio` (decyzja zespołu 2026-11-21) obejmuje `audio.fingerprint` (Chromaprint) i `audio.speaker_embedding` (odcisk głosu); transkrypcja `asr.text` należy do rodziny `text`. Klasyfikację śladów audio jako specyficznych lub pomocniczych ustala para C. Dowód wskazuje oba końce porównania, relację, metrykę, zmierzoną wartość, próg i siłę sygnału. Zachowujemy oryginalne wartości obok normalizacji. |
| Podobieństwo kreacji i wzorzec stron | Identyczne bajty, powtórzona kreacja i podobieństwo dwóch zapisów stron mają osobne znaczenia w wyniku. Przy parze stron pokaż np. tekst nagłówków i ślad HAR wraz z ich źródłami. Można zwrócić te wyniki nawet wtedy, gdy brakuje danych do oceny kampanii. |
| `PairAssessment` emisji | Zwraca oceny `strong`, `similar` lub `none`, dowody, kolejność w rankingu, powody oraz osobny stan pokrycia. `strong` wymaga zgodności co najmniej dwóch niezależnych rodzin po obu stronach i co najmniej jednego śladu specyficznego. `similar` oznacza dostępną sugestię poniżej tego warunku, `none` brak sugestii. Wystarczające pokrycie wymaga możliwości porównania co najmniej dwóch niezależnych rodzin, nawet przy rozbieżnych wartościach. |
| `Campaign` | Hipoteza obejmuje przynajmniej dwie emisje. Profil zawiera wspólne ślady, ich źródła, liczbę wspierających emisji i ich ID. Podobieństwo dwóch odrębnych grup wskazuje cechę profilu oraz konkretne pary wspierające analogię. |
| `MatchResult` | Zawiera ID zapytania, wersję korpusu, konfiguracji i metod, status, przyczyny, kandydatów, podobne pojedyncze emisje i pokrycie każdej grupy. GUI i eksport pokazują liczbę porównywalnych emisji spośród wszystkich oraz powody braków. |

**Specyficzność i ranking.** Przed oceną utrwal w konfiguracji warunki uznania śladu za specyficzny. Oceń, jak często dokładna wartość występuje w odrębnych przypadkach rozwojowych i czy źródło wiąże ją z konkretnym materiałem. Wspólny popularny SDK lub nazwa parametru daje najwyżej wskazówkę pomocniczą. Dokładny identyfikator konkretnej integracji może być specyficzny, jeśli potwierdzają to pochodzenie i sprawdzony zakres jego użycia. Sama rzadkość w małym korpusie pozostawia ślad pomocniczym.

`rank_score` to największa suma punktów z podzbioru zgodnych, udokumentowanych obserwacji. Przyznaj 2 punkty za obserwację specyficzną i 1 za pomocniczą. W wybranym podzbiorze lewy `origin_id` może wystąpić tylko raz i prawy `origin_id` również tylko raz. Gdy specyficzne podobieństwo obrazu i pomocnicze podobieństwo OCR pochodzą z tej samej pary zrzutów, ich łączny wkład wynosi 2 punkty. Zgodny ślad pomocniczy o odrębnym pochodzeniu po obu stronach zwiększa wynik do 3. Ocena `strong` nadal wymaga niezależnych rodzin i spełnienia warunku specyficzności.

**Scalanie grup.** Rozpatruj krawędzie `strong` według malejącego `rank_score`. Przy remisie użyj uporządkowanych ID emisji. Połącz dwie grupy tylko wtedy, gdy wszystkie pary między nimi są mocne (complete-link). Dla mocnych A–B i B–C przy słabym A–C powstaje grupa dwóch emisji, a trzecia zachowuje relację do przeglądu. Ranking służy do kolejności, a próg i wersja metody do odtworzenia decyzji.

## Decyzja dla nowej emisji

Zapytanie porównujemy ze wszystkimi emisjami zamrożonej referencji, również z pojedynczymi. **Pełna grupa** ma `strong` wobec każdego członka. **Sugestia częściowa** ma co najmniej jedno trafienie `strong` lub `similar`, lecz nie spełnia warunku pełnej grupy. Pojedyncza podobna emisja także stanowi sugestię. **Silny rywal** to inna, częściowo pasująca grupa z co najmniej jedną parą `strong`. Pojedyncza emisja spoza grupy pozostaje widoczna jako sugestia, również przy mocnym związku. **Wykluczenie grupy** według complete-link wymaga co najmniej jednej pary `none` z wystarczającym pokryciem w tej grupie. **Pełne wykluczenie** wymaga niepustej referencji, braku sugestii, takiego wykluczenia każdej grupy oraz pary `none` z wystarczającym pokryciem dla każdej pojedynczej emisji poza grupami.

Pierwszy pasujący wiersz określa wynik.

| Kolejność | Warunek | Status | Komunikat dla analityka |
| --- | --- | --- | --- |
| 1 | Dwie lub więcej pełnych grup albo jedna pełna grupa i silny rywal | `review_needed` | Pokaż konkurujące grupy i mocne dowody dla każdej kandydatury. |
| 2 | Dokładnie jedna pełna grupa bez silnego rywala | `probable_match` | Pokaż hipotezę przypisania, pokrycie wszystkich grup, podobne pojedyncze emisje, słabsze sugestie i nieporównywalne przypadki. |
| 3 | Brak pełnej grupy i przynajmniej jedna sugestia częściowa lub podobna pojedyncza emisja | `review_needed` | Pokaż źródła sugestii i brakujący dowód. |
| 4 | Brak sugestii oraz pusta referencja, niewykluczona grupa lub pojedyncza emisja z niedostatecznym pokryciem | `insufficient_evidence` | Wskaż, których hipotez nie udało się sprawdzić i z jakiego powodu. |
| 5 | Brak sugestii przy pełnym wykluczeniu w referencji | `no_match` | Możliwy nowy wzorzec względem tej referencji. Jedna emisja może rozpocząć dochodzenie. |

Zapytanie nie zmienia słownika tekstu, składu kampanii ani cech referencji. Test odbiorowy powtarza zgłoszenie A po odmiennym zgłoszeniu B i sprawdza identyczne dowody dla A. Osobny test porównuje nowy materiał z jedną dobrze opisaną emisją i drugą grupą bez wystarczających pól. Przy braku trafień oczekiwany jest wiersz 4.

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

Każde sprawdzenie adresu dostaje osobny katalog `pages/<id_pobrania>/` w prywatnym katalogu stanu. Źródłami dla analizy są `page.html` (DOM po wykonaniu JavaScriptu), `page_files/`, `screenshot.png` i `network.har` (HAR 1.2 z treściami odpowiedzi). `metadata.json` przechowuje pełne adresy wejścia i końca nawigacji, czas UTC, viewport, status i błędy. Status `success` wymaga DOM, zrzutu, wpisu odpowiedzi dokumentu i braku błędów. `partial` oznacza zachowaną odpowiedź lub DOM przy niepełnej wizycie, a `failed` brak obu. Żądania zablokowane przez transport i brakujące odpowiedzi mają jawny ślad. Kolektor przewija stronę bez naciskania przycisków i wysyłania formularzy.

Paczka jest prywatnym źródłem. W eksporcie analitycznym pola sieciowe nadal mają dotychczasowy ograniczony zakres. Samodzielna wizyta nie tworzy relacji z emisją. Scheduler wiąże kartę z paczką na podstawie elementu CTA i wpisu HAR dokumentu. Wcześniejsze pakiety pozostają czytelne po ścieżkach zapisanych w ich manifestach.
