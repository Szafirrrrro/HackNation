# Pomiar przypisania do kampanii

Uruchom `python scripts/evaluate_campaigns.py` z katalogu projektu. Argument `--out raport.json` zapisuje pełne decyzje, top-3, odcisk plików, parametry i czas pomiaru. Polecenie korzysta z tej samej funkcji `build_reference().match()` co ekran analityka. Porównanie tekstowe uczy znakowy TF-IDF (3–5) wyłącznie na referencji. Obie metody stosują complete-link, co najmniej trzy materiały w grupie, próg kampanii 0,65 i próg przeglądu 0,25.

## Materiał i definicje

- **Rozwój.** Dane demo w `graph/data` i przykłady nowych reklam służą testowaniu i prezentacji. Poniższy pomiar korzysta z osobnych fikcyjnych materiałów napisanych na potrzeby próby.
- **Referencja.** 12 emisji w `reference.jsonl`, w tym trzy różne kampanie po trzy emisje i trzy pojedyncze emisje. Etykiety wyznaczają dziewięć dodatnich par spośród 66. Model buduje referencję raz.
- **Zapytania.** Dziesięć odrębnych emisji w `queries.jsonl`. Pięć pochodzi ze znanych kampanii, w tym jedna ze słabym dowodem. Trzy pochodzą z dwóch kampanii nieobecnych w referencji. Dwie kontrolne obejmują sprzeczne przesłanki oraz brak danych.
- **Etykiety.** Plik `labels.json` opisuje zamierzone scenariusze autorów. Ewaluator odczytuje go do oceny. Grupa musi składać się wyłącznie z emisji oczekiwanej kampanii. Top-3 oznacza co najmniej jednego właściwego sąsiada w pierwszych trzech wynikach ponad progiem przeglądu.

## Wynik na syntetycznym zbiorze

| Miara | Ekran analityka | Sam tekst |
| --- | ---: | ---: |
| Grupy w referencji | 3 | 0 |
| Pary po grupowaniu TP / FP / FN | 9 / 0 / 0 | 0 / 0 / 9 |
| Precyzja / czułość par | 100% / 100% | brak dodatnich predykcji / 0% |
| Znane kampanie, prawidłowo przypisane / do przeglądu / bez dopasowania | 4 / 1 / 0 | 0 / 4 / 1 |
| Obce kampanie, prawidłowo odrzucone / do przeglądu / błędnie przypisane | 2 / 1 / 0 | 1 / 2 / 0 |
| Kontrole, prawidłowy status | 2/2 | 2/2 |
| Pokrycie decyzją o przypisaniu lub odrzuceniu | 6/10 | 2/10 |
| Trafienie w top-3 dla znanego wariantu | 5/5 | 3/5 |
| Oczekiwany status i prawidłowa grupa przy przypisaniu | 9/10 | 4/10 |

Dla jednego obcego materiału podobieństwo tekstu wystarczyło do skierowania go do przeglądu. Sam tekst nie połączył żadnej trójki w referencji przy wspólnym progu kampanii. W obu metodach operator może obejrzeć słabszych sąsiadów. Pomiar czasu obejmuje budowę referencji oraz p95 dziesięciu zapytań z gotowych kart. Przykładowy przebieg Windows x64, Python 3.13.5, dał odpowiednio 50 ms i 3 ms dla silnika oraz 16 ms i 0,7 ms dla samego tekstu. Osobny przebieg przez `analyze_image`, `parse_card` i tę samą referencję obejmował 10 różnych syntetycznych PNG 720 × 116 px. Każdy zawierał czarny napis „TEST REKLAMY” i inny czterocyfrowy numer na białym tle, Arial 42 px. Windows.Media.Ocr odczytał pełne 10/10 napisów. Od przekazania bajtów do decyzji mediana wyniosła 482 ms, a p95 593 ms. Pomiar nie obejmuje przesłania pliku przez przeglądarkę ani pobrania URL.

Mała próba sprawdza zachowanie reguł. Etykiety wynikają ze scenariuszy syntetycznych. Nie ustalono trafności na rzeczywistych kampaniach NASK, szkodliwości treści ani jakości na ukrytym zbiorze jury. Wagi modeli laboratoryjnych nie uczestniczyły w tym pomiarze.
