# Scraper live → PostgreSQL → Streamlit: uruchomienie

Scraper (`scamgraph.discovery`) co N minut pobiera reklamy z Biblioteki reklam Meta i zapisuje karty do PostgreSQL. Co M minut przelicza kampanie. Streamlit (`graph/app.py`) czyta karty z bazy, rysuje graf i sam się odświeża po nowych danych.

Wszystkie polecenia uruchamiaj z katalogu głównego repo `HackNation`, nie z `graph/`.

## 1. Jednorazowa instalacja

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r graph/requirements-app.txt
```

Scraper Meta potrzebuje **Google Chrome**. Na Ubuntu i Debianie zainstaluje go `playwright install chrome`. Na Linux Mint i innych dystrybucjach zainstaluj ręcznie:

```bash
wget -O /tmp/google-chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install /tmp/google-chrome.deb
google-chrome --version
```

## 2. Baza PostgreSQL (Docker)

Hasło wymyślasz sama. Docker ustawia je przy **pierwszym** starcie bazy.

```bash
export POSTGRES_PASSWORD='HackNation123'
docker compose -f graph/docker-compose.yml up -d postgres
```

- Compose udostępnia PostgreSQL lokalnie na porcie 5433. Gdy ten port jest zajęty, zmień port hosta w `graph/docker-compose.yml` oraz w `DATABASE_URL`.
- `password authentication failed` oznacza, że baza powstała wcześniej z innym hasłem. Załóż ją od nowa, co usuwa jej dane: `docker compose -f graph/docker-compose.yml down -v`, a potem powtórz krok 2.

Sprawdzenie:

```bash
export DATABASE_URL="postgresql://scamgraph:HackNation123@127.0.0.1:5433/scamgraph"
psql "$DATABASE_URL" -c "select 1"
```

## 3. Konfiguracja scrapera (`discovery.live.json`)

- `"permission"` musi zawierać deklarację zespołu, że wolno wam automatycznie czytać Bibliotekę reklam Meta. Puste pole blokuje start.
- `"phrases"` to frazy wyszukiwania (do 50), a `"limit"` to maksymalna liczba reklam na frazę (do 100).
- Przy wielu frazach dodaj `"timeout_seconds": 1200`. Domyślne 180 s nie wystarcza.

## 4. Każdy nowy terminal (ważne)

`export` działa tylko w terminalu, w którym go wpiszesz. W **każdym** terminalu wpisz:

```bash
source .venv/bin/activate
export DATABASE_URL="postgresql://scamgraph:HackNation123@127.0.0.1:5433/scamgraph"
```

Bez `DATABASE_URL` scraper zapisuje **tylko pliki** i po cichu pomija bazę. Sprawdzisz to poleceniem `echo "URL=[$DATABASE_URL]"`.

Na stałe: `echo 'export DATABASE_URL="..."' >> ~/.bashrc`

## 5. Pierwszy przebieg na próbę

```bash
python -m scamgraph.discovery --config discovery.live.json run --source meta
```

Dobry wynik to `"status": "success"` i `read_count` większe od 0. Przebieg odwiedza też strony docelowe reklam i może trwać kilka minut. **Nie przerywaj go Ctrl+C**, bo eksport do bazy wykonuje się na końcu. Gdyby przebieg został przerwany, wyeksportuj karty ręcznie:

```bash
python -m scamgraph.discovery --config discovery.live.json graph --mode live
psql "$DATABASE_URL" -c "select dataset_id, count(*) from card_current group by 1"
```

## 6. Terminal 1: zegar scrapera

```bash
python -m scamgraph.discovery --config discovery.live.json control --scrape-minutes 30 --graph-minutes 10
python -m scamgraph.discovery --config discovery.live.json timer
```

Zegar zostaw włączony. Po każdym przebiegu karty od razu trafiają do bazy, a co `--graph-minutes` zegar przelicza kampanie.

Sterowanie z innego terminala, działa od razu:

```bash
python -m scamgraph.discovery --config discovery.live.json control            # stan
python -m scamgraph.discovery --config discovery.live.json control --pause    # stop
python -m scamgraph.discovery --config discovery.live.json control --resume   # start
python -m scamgraph.discovery --config discovery.live.json control --graph-now
```

## 7. Terminal 2: Streamlit

```bash
export SCAMGRAPH_DISCOVERY_CONFIG=discovery.live.json
streamlit run graph/app.py
```

W przeglądarce (http://localhost:8501), w panelu bocznym:

1. Źródło: **„Baza PostgreSQL (scraper)”**.
2. Tryb scrapera (dataset): **`live`**. Lista jest alfabetyczna i domyślnie zaznacza `import`.
3. Panel **„Zegar scrapera”** ma przyciski Start i Stop, interwały oraz „Przebuduj graf teraz”.

Strona sama się przeładowuje, gdy scraper dopisze dane (domyślnie sprawdza co 30 s).

## Najczęstsze problemy

| Objaw | Przyczyna | Rozwiązanie |
| --- | --- | --- |
| `streamlit: command not found`, `python: not found` | brak aktywnego `.venv` | `source .venv/bin/activate` |
| `No module named 'imagehash'` | brak zależności aplikacji | `pip install -r graph/requirements-app.txt` |
| `Nie udało się załadować Playwright` | uruchomione systemowym `python3` | aktywuj `.venv` |
| `role "<user>" does not exist` przy `psql` | pusty `DATABASE_URL` | `export DATABASE_URL=...` |
| W bazie brak zbioru `live`, choć scraper odczytał reklamy | scraper działał bez `DATABASE_URL` albo przebieg przerwano | ustaw zmienną i uruchom `graph --mode live` |
| Liczba kart stoi w miejscu | ta sama fraza zwraca te same reklamy | dodaj frazy i podnieś `limit` |
| `Dokument Meta HTTP 403. Odmowa dostępu.` | Meta blokuje zbyt częste zapytania | scrapuj rzadziej (np. co 30 min), odczekaj. Alternatywa: ręczny import zapisanego HTML (`"manual_import": true`) |
| Mało kampanii na grafie | kampania wymaga min. 3 podobnych reklam | więcej danych albo suwak „min. reklam w kampanii” |

Testy: `python -m unittest tests.test_timer_control`, a z osobną, pustą bazą testową `TEST_DATABASE_URL=postgresql://.../scamgraph_test python -m unittest tests.test_database_source_app`.
