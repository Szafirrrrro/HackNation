# Jeden JSON dla Emilki

Finalny format Witka w `models/` jest wejściem bez modyfikacji. Wynik adaptera
łączy cechy obrazu, tekstu i audio z obserwacjami strony. Zobacz
[kontrakt pól](../../docs/DATA_CONTRACT.md#json-przekazywany-emilce-adapter-feature-join-v2).

Z katalogu `graf/ftf-graph-py` (Python + numpy, bez wag i inferencji):

```bash
python3 -m ftf_graph extract-snapshot /folder/zapisu --screenshot reklama.png --out /tmp/snapshot.json
python3 -m ftf_graph merge-features /tmp/snapshot.json \
  --features /folder/wyniku/witka/dataset-id \
  --feature-ad-id ID_Z_ADS_JSONL \
  --ad-page-link /folder/potwierdzony-link.json \
  --out /tmp/emilka.json
```

`--screenshot` pomijamy przy samym audio. Wtedy wyjście Witka musi zawierać
`audio_path` albo `video_path`. Nie łączymy plików po podobnych nazwach i nie
zmieniamy ID emisji. Jeśli brak snapshotu, jako wejście funkcji `merge_features`
można przekazać `ftf_graph.snapshot.empty_result('no page capture')`.

Przykładowy format `potwierdzony-link.json` (wyłącznie własne dane syntetyczne):

```json
{
  "ad_id": "a",
  "capture_id": "capture-1",
  "origin_id": "export-1",
  "observed_at": "2026-11-21T10:00:00Z",
  "source_ref": {
    "file": "sources/library-export.jsonl",
    "field": "destination_url",
    "value": "https://front.example/start"
  }
}
```

Bez `--ad-page-link` wszystkie dane strony zostają w
`extensions.page_observation`, a aktywne `infra/page` pozostają puste. Link jest
jawną deklaracją zweryfikowanego związku; adapter nie zastępuje analityka ani nie
odczytuje pliku wskazanego w `source_ref`. Historyczne HTTP 200 nie oznacza obecnego
statusu alive. Brakujących RDAP, ASN i certyfikatu nie uzupełniamy domysłami.

Jeśli Witek policzył kilka metod tego samego pola, wybierz dokładną wersję:

```bash
python3 -m ftf_graph merge-features /tmp/snapshot.json \
  --features /folder/wyniku/witka/dataset-id --feature-ad-id ID_Z_ADS_JSONL \
  --method 'audio.transcript=METODA_WHISPER_Z_JSONL' \
  --method 'audio.text_embedding=METODA_E5_Z_JSONL' \
  --source 'audio.text_embedding=asr.text@METODA_WHISPER_Z_JSONL' \
  --out /tmp/emilka.json
```

Analogiczny wybór jest dostępny dla `audio.segments`, `audio.asr_duration_s`,
`audio.duration_s`, `audio.fingerprint`, `audio.speaker_embedding` i pól obrazu.
Niejednoznaczność pozostawia pole puste, ze wskazaniem w warnings; pełny zestaw
prawidłowych cech nadal znajduje się w `extensions.model_features`.

[example_handoff.json](data/example_handoff.json) to kompletny przykład formatu
na własnym HTML/HAR i **syntetycznych cechach**, nie wynik modeli na reklamie NASK.
Krótkie wektory pokazują serializację; prawdziwe wymiary wynikają z metody Witka.
JSON jest samowystarczalny: embeddingi i fingerprint są listami liczb, bez potrzeby
przekazywania NPY/NPZ. Dowody nadal wskazują źródłowe pliki do audytu.

```python
from ftf_graph.card import load_cards
card = next(load_cards('/tmp/emilka.json'))
transcript = card.audio['transcript']
fingerprint = card.audio['fingerprint']  # None albo obiekt z listą array
features = card.raw['extensions']['model_features']
```

Scorer nie ma jeszcze reguł audio ani DINOv2. Ten adapter dostarcza dane do ich
implementacji; nie nadaje nowych wag ani progów. Transkrypcja, fingerprint i głos
jednego nagrania mają wspólne pochodzenie, więc nie stanowią trzech niezależnych
dowodów. Wszystkie faktycznie dostępne pola URL/metadanych są zachowane z dotychczasowego
snapshotu: przekierowania, domena, historyczny status HTTP, tracking/AIO, skrypty,
struktura DOM, tekst ukryty, formularze, kontakty, favicon i landing text.

Sprawdzenie bez pobierania modeli:

```bash
python3 -B -m unittest discover -s tests -v
```

Prywatne wyniki NASK zapisuj poza śledzonymi przykładami (np. w `wyniki/`).
