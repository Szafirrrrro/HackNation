# ScamGraph

**Od jednej podejrzanej reklamy do grupy materiałów, które warto sprawdzić razem.**

ScamGraph to planowany demonstrator na zadanie NASK „Kolekcjoner Fejków” podczas HackNation 2026. Analityk dodaje obraz lub zrzut reklamy. Aplikacja porównuje go z wcześniej zebranymi materiałami i pokazuje proponowane powiązania wraz z konkretnymi śladami. Zbieżność ogólnego tematu lub wizerunku może uzasadnić porównanie. Przypisanie do kampanii wymaga silniejszych przesłanek.

## Zakres pierwszej wersji

- Korpus startowy zawiera 13 reklam z publicznej zagadki NASK. Każdy rekord ma lokalny obraz, fragment tekstu widocznego na zrzucie i udokumentowane pochodzenie.
- Jeden lokalny ekran Streamlit z wejściem PNG/JPEG, opcjonalnym tekstem i znanym adresem docelowym. Analiza korzysta z zapisanego korpusu.
- Deterministyczne porównanie obrazów, tekstu i dostępnych metadanych. OCR odczytuje tekst z kreacji. Silnik pokazuje grupę, hipotezę do sprawdzenia albo brak podstaw do przypisania.
- Pokaz jednego uzasadnionego dopasowania i jednego trudnego kontrprzykładu, z pomiarem względem prostego wariantu tekstowego.

Zgodnie z nowym opisem NASK po 30% oceny przypada na metodę korelacji i grupowania oraz na jakość cech i źródeł. Pozostałe kryteria to pełny demonstrator (15%), interpretowalność (15%) oraz potencjał wdrożeniowy, skalowalność i przenośność (10%). Podczas oceny NASK wykorzysta także wcześniej nieudostępniony zbiór. [Pełny opis zadania](docs/NASK_ZADANIE.md)

## Dane do pierwszego uruchomienia

Wskaż jako katalog korpusu [data/nask-hacknation-2026](data/nask-hacknation-2026/). Rekordy wejściowe są w [ads.jsonl](data/nask-hacknation-2026/ads.jsonl). Ich ścieżki `image_path` liczą się od katalogu z [manifestem](data/nask-hacknation-2026/manifest.json). Całość można odczytać offline.

Materiały przekazane przez NASK służą wyłącznie realizacji wyzwania. Punkt 8 zadania zabrania ich publicznego rozpowszechniania. Korpus pracuje lokalnie, a publiczna strona zespołu ilustruje reguły na danych syntetycznych. Dostęp do repozytorium zawierającego korpus lub jego historię powinien być ograniczony.

Pierwsze porównanie można wykonać na zrzutach [p3](data/nask-hacknation-2026/media/p3-123146.png) i [p4](data/nask-hacknation-2026/media/p4-123420.png). Na obu widać ten sam krajobraz i tekst „Temat, o którym mówi cała Polska”. Karty mają różne ID Biblioteki reklam Meta. To para do sprawdzenia podobieństwa kreacji. Etykieta kampanii pozostaje nieustalona.

W podkatalogu `observations/` są też [zapisy 15 obserwacji stron](data/nask-hacknation-2026/observations/pages.jsonl) z nagłówkami i dostępnymi śladami sieciowymi oraz [trzy adresy z katalogu NASK](data/nask-hacknation-2026/observations/scam-links.txt) do testowania parsera. Adresy przetwarzamy lokalnie jako tekst. [Opis pól i przykład odczytu](docs/DATA_CONTRACT.md#lokalny-korpus-nask)

## Start prac

1. Zacznij od [pełnej treści zadania NASK](docs/NASK_ZADANIE.md) i [regulaminu zadania](docs/NASK_REGULAMIN.md).
2. Przeczytaj [plan MVP](docs/MVP.md), [kontrakt danych](docs/DATA_CONTRACT.md) i [przewodnik po danych NASK](docs/NASK_DATA.md). Zasady pracy i przeglądu zmian są w [AGENTS.md](AGENTS.md).
3. Wczytaj lokalny korpus NASK i wybierz przypadki do porównań i ewaluacji przed strojeniem.
4. Para A odpowiada za obraz i OCR, para B za import, tekst i metadane, para C za korelację, interfejs i ewaluację. Pierwszy wspólny wynik to obliczony dowód widoczny z formularza. [Plan, podział ról i testy odbiorowe](docs/MVP.md)

## Podręcznik dewelopera

[Pierwszy dzień w projekcie](https://scamgraph-hacknation.valid-mouse-6580.chatgpt.site/start.html) prowadzi od uruchomienia przykładu do pierwszego zadania w parze. [Interaktywna mapa systemu](https://scamgraph-hacknation.valid-mouse-6580.chatgpt.site/#architektura), [kontrakty warstw](https://scamgraph-hacknation.valid-mouse-6580.chatgpt.site/architektura.html) i [przykład jednej analizy](https://scamgraph-hacknation.valid-mouse-6580.chatgpt.site/przyklad.html) opisują ten sam przepływ z trzech perspektyw.

Strona dla programistów przedstawia architekturę, technologie, odpowiedzialność trzech par i testy integracji. Statyczny przykład pokazuje reguły dopasowania na danych syntetycznych. Jej pliki źródłowe znajdują się w [sites/scamgraph/dist/](sites/scamgraph/dist/), a scenariusze mają [testy w Node.js](sites/scamgraph/tests/cases.test.mjs). Poniższe polecenia uruchamiają statyczną stronę z katalogu głównego. W Windows możesz użyć `py -3` zamiast `python`.

```sh
node --test sites/scamgraph/tests/cases.test.mjs
python -m http.server 8000 --bind 127.0.0.1 --directory sites/scamgraph/dist
```

Podgląd działa pod adresem `http://127.0.0.1:8000/`.

## Materiały organizatorów

- [Pełna treść zadania NASK](docs/NASK_ZADANIE.md) i [regulamin zadania](docs/NASK_REGULAMIN.md). W regulaminie §2 dotyczy oceny, a §4 praw autorskich. Mapa wymagań jest w planie MVP.
- [FakeCollector PRO™ — przykład NASK](https://science.nask.pl/hacknation). Parodia reklamy z inspiracjami technicznymi i wskazówką do katalogu materiałów.
- [Przewodnik uczestnika HackNation](https://hacknation.pl/przewodnik-uczestnika) i [komunikat NASK o zadaniu oraz kierunku integracji z DROZD](https://www.nask.pl/aktualnosci/polska-rzuca-wyzwanie-hakerom-nask-na-hacknation).
