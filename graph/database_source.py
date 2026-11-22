"""Źródło „Baza PostgreSQL (scraper)” dla graph/app.py: karty z card_current, auto-odświeżanie i zegar scrapera.

Scraper (`python -m scamgraph.discovery timer` z ustawionym DATABASE_URL) zapisuje karty i przebiegi silnika
do PostgreSQL. Ten moduł czyta je dla analityka i pozwala sterować zegarem przez <state_dir>/timer-control.json.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime
import os
from pathlib import Path

import streamlit as st

from scamgraph import db as pgdb
from scamgraph.analyst_corpus import AnalystCorpus, database_stamp, load_database_corpus

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_ENV = "SCAMGRAPH_DISCOVERY_CONFIG"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", "")


def datasets() -> list[tuple[str, int]]:
    with closing(pgdb.connect()) as conn:
        return conn.execute("SELECT dataset_id, count(*) FROM card_current GROUP BY 1 ORDER BY 1").fetchall()


def load_corpus(dataset: str) -> AnalystCorpus:
    """Ponownie czyta karty tylko wtedy, gdy zmienił się eksport lub przebieg silnika w bazie."""
    with closing(pgdb.connect()) as conn:
        stamp = database_stamp(conn, dataset)
        key = (database_url(), dataset, stamp)
        previous = st.session_state.get("corpus_import")
        if previous is None or previous[0] != key:
            previous = (key, load_database_corpus(conn, dataset))
            st.session_state["corpus_import"] = previous
    st.session_state["database_seen"] = stamp
    return previous[1]


def last_run_caption(dataset: str) -> str | None:
    with closing(pgdb.connect()) as conn:
        run = conn.execute(
            """SELECT computed_at, card_count, code_version,
                      (SELECT count(*) FROM run_result r WHERE r.run_id = e.run_id AND r.kind = 'campaign')
               FROM engine_run e WHERE dataset_id = %s ORDER BY computed_at DESC, seq DESC LIMIT 1""",
            (dataset,)).fetchone()
        feed = conn.execute("SELECT stored_at FROM feed_export WHERE dataset_id = %s", (dataset,)).fetchone()
    parts = []
    if feed:
        parts.append(f"ostatni eksport scrapera {feed[0]:%Y-%m-%d %H:%M:%S}")
    if run:
        parts.append(f"przebieg silnika {run[0]:%Y-%m-%d %H:%M:%S}: {run[3]} kampanii z {run[1]} kart, kod {run[2]}")
    return " · ".join(parts) or None


def watch(dataset: str, seconds: int) -> None:
    """Fragment sprawdza co `seconds` s rewizję zbioru i przeładowuje stronę, gdy scraper dopisał dane."""

    def check():
        try:
            with closing(pgdb.connect()) as conn:
                stamp = database_stamp(conn, dataset)
        except Exception as exc:  # chwilowy brak bazy nie zatrzymuje widoku
            st.caption(f"Nie sprawdzono bazy: {type(exc).__name__}")
            return
        if stamp != st.session_state.get("database_seen"):
            st.rerun()
        st.caption(f"Sprawdzono bazę {datetime.now():%H:%M:%S} · bez zmian")

    st.fragment(run_every=f"{seconds}s")(check)()


def _when(value) -> str:
    if value is None:
        return "—"
    return f"{datetime.fromtimestamp(value):%Y-%m-%d %H:%M:%S}"


def scraper_controls() -> None:
    """Start/stop zegara scrapera i interwały. Zegar odczytuje zmianę w ciągu sekundy."""
    from scamgraph.discovery.control import status, update_control
    from scamgraph.discovery.service import load_config

    default = os.environ.get(CONFIG_ENV) or str(REPO_ROOT / "discovery.json")
    file = st.text_input("Konfiguracja scrapera", default, key="scraper-config",
                         help=f"Plik przekazany do --config zegara. Domyślny z {CONFIG_ENV}.")
    try:
        config = load_config(Path(file).expanduser())
    except (OSError, ValueError, KeyError) as exc:
        st.error(f"Nie wczytano konfiguracji: {exc}")
        return
    state = config["state_dir"]

    def panel():
        try:
            clock = status(load_config(Path(file).expanduser()))
        except (OSError, ValueError, KeyError) as exc:
            st.error(f"Nie wczytano konfiguracji: {exc}")
            return
        paused = clock["control"]["paused"]
        if not clock["alive"]:
            st.warning("Zegar scrapera nie działa. Uruchom go w terminalu z tym samym DATABASE_URL:")
            st.code(f'python -m scamgraph.discovery --config "{file}" timer', language="bash")
        elif paused:
            st.info("Zegar działa · scrapowanie wstrzymane")
        else:
            st.success("Zegar działa · scrapowanie włączone")
        start, stop = st.columns(2)
        # Callback zapisuje stan przed ponownym narysowaniem fragmentu.
        start.button("Start", disabled=not paused, key="scraper-start", on_click=update_control, args=(state,),
                     kwargs={"paused": False})
        stop.button("Stop", disabled=paused, key="scraper-stop", on_click=update_control, args=(state,),
                    kwargs={"paused": True})
        st.caption(f"Scrapowanie co {clock['scrape_interval'] / 60:g} min · graf co {clock['graph_interval'] / 60:g} min")
        st.caption(f"Ostatnia przebudowa grafu {_when(clock['last_graph'])} · następna {_when(clock['next_graph'])}")
        if clock["graph_error"]:
            st.warning(f"Błąd aktualizacji grafu: {clock['graph_error']}")
        for source in clock["sources"]:
            st.caption(f"{source['source_id']}: {source['status'] or 'oczekuje'} · nowe {source['new_count'] or 0} · "
                       f"następny przebieg {_when(source['next_run'])}"
                       + (f" · błąd: {source['error']}" if source["error"] else ""))

    st.fragment(run_every="5s")(panel)()
    with st.form("scraper-intervals"):
        current = status(config)
        # Minimum 0,05 min = 3 s; wartości z konfiguracji mieszczą się w zakresie po przycięciu.
        scrape = st.number_input("Scrapuj co (min)", 0.05, 10080.0,
                                 min(max(current["scrape_interval"] / 60, 0.05), 10080.0), 1.0)
        graph = st.number_input("Przebuduj graf co (min)", 0.05, 1440.0,
                                min(max(current["graph_interval"] / 60, 0.05), 1440.0), 1.0)
        if st.form_submit_button("Zapisz interwały"):
            try:
                update_control(state, interval_seconds=scrape * 60, graph_interval_seconds=graph * 60)
                st.toast("Zapisano. Zegar zastosuje interwały przy najbliższym takcie.")
            except ValueError as exc:
                st.error(str(exc))
    if st.button("Przebuduj graf teraz", key="scraper-graph-now"):
        update_control(state, request_graph=True)
        st.toast("Zegar przebuduje graf i zapisze go do bazy.")
