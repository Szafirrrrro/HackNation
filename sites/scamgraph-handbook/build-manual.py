"""Build the handbook articles from the eight team documents (Python 3.10+, PowerShell 7)."""

import json
import re
import subprocess
from html import escape
from html.parser import HTMLParser
from pathlib import Path


SITE = Path(__file__).resolve().parent
ROOT = SITE.parents[1]
OUTPUT = SITE / "dist" / "manual.js"
SOURCES = {
    "readme": ("README.md", "overview"),
    "roadmap": ("docs/MVP.md", "teams"),
    "contract": ("docs/DATA_CONTRACT.md", "matching"),
    "data": ("docs/NASK_DATA.md", "data"),
    "ui": ("docs/PLAN_GRAF_I_OS_CZASU.md", "ui"),
    "build": ("docs/INSTRUKCJA_BUDOWY.md", "flow"),
    "lab": ("models/README.md", "lab"),
    "agents": ("AGENTS.md", "onboarding"),
}
ROUTES = {path: route for path, route in SOURCES.values()}


def site_link(match, source):
    label, target = match.groups()
    if target.startswith("https://"):
        return match[0]
    target_path = (ROOT / source).parent / target.split("#", 1)[0]
    relative = target_path.resolve().relative_to(ROOT).as_posix()
    if relative in ROUTES:
        return f"[{label}](#/{ROUTES[relative]})"
    return f"{label} (`{relative}`, w kopii zespołu)"


def source_markdown(source):
    md = (ROOT / source).read_text(encoding="utf-8")
    md = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: site_link(m, source), md)
    if source == "docs/NASK_DATA.md":
        # Preserve team findings without exposing private ad identifiers, archive credentials
        # or original capture hostnames. Reproduction examples use fictional targets.
        md = re.sub(r", odpowiednio `[0-9]+` oraz `[0-9]+`", "", md)
        md = re.sub(r"profil „[^”]+”", "ten sam profil", md)
        md = re.sub(r"widać `[A-Za-z0-9.-]+\.[A-Za-z]{2,}`", "widać jedną domenę", md)
        md = md.replace(
            "Dla pierwszego odczytu oczekiwany jest tytuł z `502: Bad gateway`, dla drugiego 26 wpisów HAR.",
            "W kopii zespołu pierwszy przykład dotyczy błędu HTTP 502, a drugi podsumowania 26 wpisów HAR. "
            "Poniższe komendy odczytu wnętrza archiwum pokazują składnię na fikcyjnych nazwach. "
            "W prywatnym środowisku podstaw ścieżki z manifestu i właściwe hasło.",
        )
        md = re.sub(r"tar\.exe --passphrase \S+ -xOf ___BACKUP.zip BACKUP/\S+?/archive_info\.json",
                    'tar.exe --passphrase $haslo -xOf ___BACKUP.zip demo/zapis/archive_info.json', md)
        md = re.sub(r"tar\.exe --passphrase \S+ -xOf ___BACKUP.zip BACKUP/\S+?\.har",
                    'tar.exe --passphrase $haslo -xOf ___BACKUP.zip demo/zapis/strona.har', md)
    return md


def split_sections(md):
    """Split at H2 only, keeping the source title, preamble and ordered subsections."""
    first_line, _, body = md.partition("\n")
    if not first_line.startswith("# "):
        raise ValueError(f"Missing document title in {first_line!r}")
    sections = {}
    chunks = re.split(r"(?m)^## (.+)\n", body)
    sections[""] = chunks[0].strip()
    for title, text in zip(chunks[1::2], chunks[2::2]):
        if title in sections:
            raise ValueError(f"Duplicate section {title}")
        sections[title] = f"## {title}\n\n{text.strip()}"
    return first_line[2:], sections


def render_documents(documents):
    """Convert Markdown with tables and fenced code using the bundled Markdig renderer."""
    script = """
        $ErrorActionPreference = 'Stop'
        [Console]::InputEncoding = [Text.Encoding]::UTF8
        [Console]::OutputEncoding = [Text.Encoding]::UTF8
        $parts = ConvertFrom-Json -AsHashtable -InputObject ([Console]::In.ReadToEnd())
        $html = [ordered]@{}
        foreach ($key in $parts.Keys) {
            $html[$key] = (ConvertFrom-Markdown -InputObject $parts[$key]).Html
        }
        [Console]::Write((ConvertTo-Json -Compress -Depth 5 $html))
    """
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
        input=json.dumps(documents, ensure_ascii=False), capture_output=True,
        text=True, encoding="utf-8", check=True,
    )
    # Routing uses hash paths. Markdown-generated heading IDs would collide in the archive.
    return {k: re.sub(r'(<h[2-6]) id="(?!para-[abc]")[^"]+"', r"\1", v)
            for k, v in json.loads(result.stdout).items()}


TEAM_SHIFTS = """## Praca równoległa i przekazania

Terminy w tabeli odnoszą się do czasu polskiego. Próba każdego etapu korzysta z efektu pracy poprzedniej pary.

| Etap | A · dane i źródła | B · ekstrakcja i pomiar | C · korelacja i ekran |
| --- | --- | --- | --- |
| Do 18:00, 21 XI | Przekaż dwa rekordy emisji, jeden zapis strony i raport źródeł. | Oblicz dwie cechy obrazu, odległość oraz pochodzenie. | Wczytaj rekordy i pokaż pierwszą zmierzoną relację po dodaniu nowego pliku. A sprawdza, czy prowadzi do pierwotnego pola. |
| Do 20:00 | Z B odłóż materiały do testu. Rozdziel rzeczywiste i kontrolowane dane. | Z A przygotuj niezależne etykiety oraz opis przypadków spornych. | Sprawdź brak pola i ponowny import. Lider tworzy zgłoszenie robocze w HackTribe. |
| Do północy | Przekaż zweryfikowane powiązania emisja–strona albo jawny raport braków. | Dostarcz TF-IDF, obraz, OCR i próbę z popularną cechą. Wskaż błąd bazy, który uzasadnia ewentualny eksperyment. | Zbuduj grupy na CPU i uruchom pełny przebieg od zapytania do grafu, chronologii i źródeł. |
| Do 07:00, 22 XI | Zamroź referencję i sposób mapowania obcych danych. | Porównaj bazę z najwyżej jednym modelem, zmierz koszty i zamroź wersje oraz progi. | Zamroź silnik. Sprawdź łańcuch, rywali, pokrycie i powtarzalność identycznego zapytania. |
| Do 10:30 | Sprawdź pochodzenie wzorców, warunki użycia i skład przekazywanego pakietu. | Otwórz końcową próbę raz. Przekaż liczniki, mianowniki, błędy i czasy na opisanym sprzęcie. | Odbierz aplikację na świeżym stanowisku CPU bez sieci, wykonaj niezależny przegląd i złóż materiały przed 11:00. |
"""

TEAM_GUIDES = """## Para A · dane i źródła {#para-a}

**Cel.** Każda wartość przekazana do porównania powinna prowadzić do pola źródłowego. Jedna osoba odpowiada za emisje i powtórne importy, druga za zapisy stron, dowód związku emisja–cel i znaczenie dat. Zacznijcie od [inwentarza i przykładowych wejść](#/data).

1. **Pierwsza integracja.** Wczytajcie manifest i rekordy JSONL. Przekażcie B dwa obiekty emisji, obraz lub tekst oraz identyfikator źródła każdej wartości. C powinno dostać również jeden samodzielny zapis strony i raport pól brakujących.
2. **Podział materiału.** Przed strojeniem jedna osoba z A i jedna z B opisują przypadki niezależnie, porównują uzasadnienia i odkładają próbę końcową. Kopie jednej emisji pozostają razem. Dla obcej kampanii cała grupa pozostaje poza referencją. Odłóżcie nieustalone przypadki do przeglądu jakościowego.
3. **Do północy.** Uzgodnijcie ID lokalne i dostawcy, ścieżki zasobów i sumy SHA-256. Zachowajcie dwa zapisy tego samego URL, jeśli dotyczą różnych pobrań. Przekażcie C udokumentowane relacje emisja–strona wraz z polem i czasem obserwacji. Gdy brakuje takiego źródła, strona pozostaje dostępna w porównaniach stron.
4. **Do zamrożenia i złożenia.** Utrwalcie wersję korpusu i mapowanie formatów. Oddajcie inwentarz, źródła etykiet, zestaw braków oraz wykaz praw do użytych materiałów. Sprawdźcie osobno skład prywatnej paczki dla jury i publiczne przykłady.

**Odbiór przez B i C.** Ponowny import zachowuje liczebność. Dwie emisje o innych ID mogą współdzielić jeden plik. Wadliwy obraz pozwala nadal użyć poprawnego tekstu. Każda dołączona strona daje się prześledzić do konkretnej emisji. Osoba odbierająca otwiera te pola z wyniku analizy.

## Para B · ekstrakcja i pomiar {#para-b}

**Cel.** Dostarczcie C porównywalne cechy i rozstrzygnijcie pomiarem, czy nowa metoda odzyskuje wcześniej pomijane warianty. Jedna osoba opracowuje obraz i OCR, druga tekst, procedurę porównań oraz koszt. [Laboratorium, komendy i wybór modelu](#/lab)

1. **Pierwsza integracja.** Sprawdźcie wymiary i format obrazów z A. Obliczcie SHA-256 z oryginalnych bajtów i pHash ze znormalizowanego obrazu. C dostaje odległość, wartości obu cech, wersję metody oraz odwołania do źródeł albo współrzędnych kadrów.
2. **Baza CPU.** Uruchomcie polski i angielski OCR oraz znakowy TF-IDF 3–5 dopasowany wyłącznie do referencji. Wydzielcie pomiar odczytu kluczowych fraz oraz ręcznie transkrybowane całe kadry do CER. Zaznaczcie wspólne pochodzenie kadru, pHash i odczytanego napisu. Przy brakach zwracajcie przyczynę.
3. **Próby przed 07:00.** Zestawcie sam tekst z pełną metodą klasyczną. Obejrzyjcie po jednym błędzie wyszukiwania, ekstrakcji lub scalenia, o ile wystąpił. Dla problemu z kadrem sprawdźcie punkty ORB i ewentualnie DINOv2-small, a dla pominiętej parafrazy E5-small. Jeden embedding kwalifikuje się po odzyskaniu dodatkowego właściwego wariantu w top-3 bez wzrostu błędnych przypisań i w budżecie czasu.
4. **Po zamrożeniu.** Uruchomcie raz pomiar końcowy na odłożonych przypadkach. Przekażcie C tabelę liczników, mianowników, wstrzymań, kosztów oraz opis sprzętu i wersji. Dla celu p95 do 5 s mierzycie drogę od przyjęcia obrazu do decyzji na gotowym indeksie. Czas OCR i budowę indeksu pokazujecie oddzielnie.

**Odbiór przez A i C.** A odtwarza wynik pojedynczej cechy z materiału źródłowego. C powtarza to samo zgłoszenie po innym i uzyskuje ten sam ranking. Brak GPU i nieudany OCR mają jawny stan i pozwalają użyć pozostałych pól. Raport oddziela dane kontrolowane od rzeczywistych przypadków z niezależnym potwierdzeniem.

## Para C · korelacja i demonstrator {#para-c}

**Cel.** Jeden silnik obsługuje testy, GUI i eksport. Jedna osoba buduje referencję, ocenia pary i przypisania. Druga łączy formularz, graf, chronologię, eksport oraz kontener. [Kontrakt decyzji](#/matching) · [Zachowanie ekranu](#/ui)

1. **Pierwsza integracja.** Odbierzcie od A dwa rekordy oraz źródła, od B pierwszy wynik porównania. Podłączcie je do formularza Streamlit. Po podstawieniu innego materiału użytkownik ma zobaczyć przeliczoną miarę i oba pola wykorzystane przez metodę.
2. **Do północy.** Rozdzielcie zgodność wartości od dostępności danych. Zapiszcie źródła z obu stron. Obliczcie ranking bez dwukrotnego użycia tego samego źródła, deterministycznie zbudujcie grupy complete-link i porównajcie nowe zgłoszenie ze wszystkimi członkami referencji oraz z pojedynczymi emisjami poza grupami. Decyzję wybierzcie według tabeli kontraktu.
3. **Do 07:00.** Przetestujcie słabe ogniwo w łańcuchu, konkurencyjną grupę, część referencji bez pokrycia i powtarzalność zapytania. Kliknięcie pary w Cytoscape.js otwiera źródła, a wybranie zdarzenia w vis-timeline wskazuje odpowiednią emisję. Filtr widoku zachowuje obliczoną decyzję.
4. **Oddanie do 10:30.** Uruchomcie kontener CPU na czystym stanowisku, otwórzcie nowy katalog i dodajcie plik spoza przykładów. Zbierzcie raport B, konfigurację, licencje, eksport dowodów i instrukcję. Przeprowadźcie prywatny pokaz i [próby odbiorowe](#/validation).

**Odbiór przez A i B.** A odtwarza wskazany związek na podstawie pól źródłowych. B przechodzi od wyniku do metryki i jej wartości na obu materiałach. Na ślepej próbie osoba spoza implementacji potrafi pokazać podstawę przypisania albo wskazać, jakiej informacji zabrakło.
"""

RESULT_EXAMPLE = """### Jak przeczytać pojedyncze porównanie

Poniżej przykładowy wyciąg z objaśnienia dla dwóch **syntetycznych** emisji. Nazwy kluczy pokazują możliwą serializację wyniku. Obowiązki typów definiuje tabela powyżej.

```json
{
  "left": {"ad_id": "demo-a", "field": "image.phash", "origin_id": "screenshot-a", "value": "0f0f0f0f0f0f0f0f"},
  "right": {"ad_id": "demo-b", "field": "image.phash", "origin_id": "screenshot-b", "value": "0f0f0f0f0f0f0f0e"},
  "family": "visual",
  "metric": "hamming_64",
  "metric_value": 1,
  "tier": "similar",
  "reason": "Wariant obrazu do przeglądu. Brakuje drugiej niezależnej rodziny.",
  "missing_families": ["infrastructure"]
}
```

Dwie różne emisje mogą mieć identyczny plik. Rejestr zachowuje oba ID i współdzieli obliczenia obrazu. Dodanie napisu OCR odczytanego z każdego z tych dwóch plików nadal daje po jednym źródle na stronę porównania. Dołączenie pola dostawcy o udokumentowanym, osobnym pochodzeniu umożliwia ponowną ocenę niezależności.
"""

QA = """## Próby, które mogą zmienić decyzję

| Wejście lub awaria | Oczekiwany efekt widoczny dla osoby testującej |
| --- | --- |
| Dwa ID dostawcy, te same bajty obrazu | Dwie emisje i jeden odcisk zasobu. Ponowny import zachowuje liczebność. |
| Nowy identyfikator, nowy katalog, brak obrazu | Importer mapuje dostępne pola i raportuje pominięcia. Analiza używa np. tekstu. |
| Podobny obraz + pochodzący z niego OCR | Panel pokazuje wspólne pochodzenie. Ranking nie nalicza dwóch niezależnych trafień. |
| Mocne A–B i B–C, słabe A–C | Pełne scalenie trzech materiałów zostaje wstrzymane. Krawędź do trzeciej emisji nadal można zbadać. |
| Jedna pełna grupa i silna częściowa rywalka | Wynik `review_needed`. Obie grupy można otworzyć. |
| Brak trafień i jedna niewykluczona grupa | Wynik `insufficient_evidence` wskazuje brakujące pola. Przy pełnym wykluczeniu wszystkich grup i pojedynczych emisji możliwy jest `no_match`. |
| Dwa zapytania, a następnie ponownie pierwsze | Liczba członków referencji i jej wersja pozostają stałe. Pierwsze zgłoszenie odtwarza decyzję i dowody. |
| Tylko data pozyskania albo znana data dzienna | Typ i precyzja źródła są widoczne. Widok nie przypisuje dacie pobrania znaczenia publikacji. |
| Awaria OCR lub brak GPU | Użytkownik widzi powód braku i dostępne cechy. Ścieżka CPU pozostaje dostępna. |

Na zablokowanym zbiorze raportuj precyzję par po grupowaniu `TP/(TP+FP)` i czułość `TP/(TP+FN)`. Dla wyszukiwania pokaż, dla ilu zapytań właściwy wariant znalazł się w pierwszej trójce i ile takich zapytań oceniono. Dla końcowej decyzji rozbij liczniki na znane i nowe kampanie. Zapisz przyczynę przynajmniej jednej pomyłki lub wstrzymania. Test modelu na tej samej emisji po rekompresji dowodzi odporności na tę transformację. Trafność na rzeczywistych kampaniach wymaga osobnych, udokumentowanych etykiet.
"""


def main():
    titles, sections = {}, {}
    for key, (path, _) in SOURCES.items():
        titles[key], sections[key] = split_sections(source_markdown(path))

    def pick(key, *names):
        return "\n\n".join(sections[key][name] for name in names)

    def full(key):
        return "\n\n".join(sections[key].values())

    md = {
        "overview": pick("readme", "") + "\n\n" + pick("roadmap", "Kryteria NASK i sposób odbioru"),
        "flow": pick("readme", "Od pliku do wyniku") + "\n\n" + pick("build", "Pierwszy wspólny przebieg", "Planowane uruchomienie demonstratora"),
        "data": full("data") + "\n\n" + pick("contract", "Wejście i zgodność z v0"),
        "matching": pick("contract", "Od obserwacji do grupy", "Decyzja dla nowej emisji") + "\n\n" + RESULT_EXAMPLE,
        "ui": full("ui"),
        "teams": pick("roadmap", "Trzy pary, jeden wynik") + "\n\n" + TEAM_GUIDES + "\n\n" + TEAM_SHIFTS + "\n\n" + pick("roadmap", "Punkty integracji"),
        "lab": full("lab"),
        "validation": pick("roadmap", "Jak oceniamy trafność", "Scenariusz dwuminutowego pokazu") + "\n\n" + QA + "\n\n" + pick("build", "Odbiór i pakiet konkursowy"),
        "onboarding": pick("readme", "Pierwszy kwadrans w projekcie", "Gdzie zacząć pracę") + "\n\n" + pick("build", "Co można sprawdzić przed implementacją") + "\n\n" + full("agents"),
    }
    html = render_documents({**md, **{f"doc_{k}": full(k) for k in SOURCES}})
    archive = ['<h2>Dokumenty zespołu</h2><p>Rozwiń wybrany dokument, aby przeczytać go w całości. '
               'W wydaniu na stronę przykłady z chronionymi identyfikatorami, adresami i hasłem do archiwum zastąpiono opisem lub danymi fikcyjnymi. '
               'Wskazane ścieżki lokalne odnoszą się do prywatnej kopii zespołu.</p>']
    for k, (path, _) in SOURCES.items():
        archive.append(f'<details><summary>{escape(titles[k])} · <code>{escape(path)}</code></summary>'
                       f'{html[f"doc_{k}"]}</details>')
    dest = {k: html[k] for k in md}
    dest["onboarding"] += "\n".join(archive)
    validate(dest)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as out:
        out.write("/* Artykuły podręcznika. Źródło: build-manual.py. */\nwindow.manual = ")
        json.dump(dest, out, ensure_ascii=False, indent=2)
        out.write(";\n")


class Validator(HTMLParser):
    def __init__(self, routes):
        super().__init__()
        self.routes = routes

    def handle_starttag(self, tag, attrs):
        allowed = {"h2", "h3", "h4", "p", "a", "code", "pre", "em", "strong", "ul", "ol", "li",
                   "table", "thead", "tbody", "tr", "th", "td", "details", "summary", "blockquote"}
        if tag not in allowed:
            raise ValueError(f"Unexpected article HTML tag {tag}")
        for key, value in attrs:
            if key == "href" and tag == "a" and (value.startswith("https://") or value in self.routes):
                continue
            if key == "class" and tag == "code" and value.startswith("language-"):
                continue
            if key == "id" and tag == "h2" and re.fullmatch("para-[abc]", value):
                continue
            raise ValueError(f"Unexpected attribute {tag} {key}={value}")


def validate(routes):
    allowed = {f"#/{key}" for key in routes}
    for article in routes.values():
        parser = Validator(allowed)
        parser.feed(article)
        parser.close()
        if re.search(r"--passphrase (?!\$haslo)\S|___BACKUP\.zip BACKUP/", article):
            raise ValueError("Original archive details in site export")


if __name__ == "__main__":
    main()
