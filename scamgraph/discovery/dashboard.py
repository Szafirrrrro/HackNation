"""Discovery controls for the local Streamlit analyst panel."""
from pathlib import Path
import json
import queue
import threading
import time

import streamlit as st

from ..catalog import catalog
from ..capture import read_json
from .engine import connection
from .page_queue import drain
from .graph_feed import refresh_graph
from .diagnostic import enabled as diagnostic_enabled, last_live_run, run_diagnostic
from .service import engine_for, load_config, restore_config, save_import

STATUS = {"idle": "Oczekuje", "running": "W toku", "error": "Błąd", "success": "Zakończono"}
PAGE_STATUS = {"queued": "W kolejce", "running": "Pobieranie strony", "partial": "Zapis częściowy",
               "trusted_domain": "Pominięto · zaufana domena",
               "success": "Zapis kompletny", "failed": "Błąd", "skipped": "Pominięta",
               "superseded": "Dostępna inna wersja"}


@st.cache_resource(max_entries=8)
def panel_engine(config):
    return engine_for(config)


def start(config, selected):
    ready = queue.Queue(maxsize=1)

    def supervise():
        try:
            claims = engine_for(config).run(selected, trigger="gui", on_claim=ready.put_nowait)
            drain(config, claims.values())
            refresh_graph(config)
        except Exception as exc:
            if ready.empty():
                ready.put_nowait(type(exc).__name__)

    threading.Thread(target=supervise, daemon=True, name="discovery-manual").start()
    try:
        claims = ready.get(timeout=2)
    except queue.Empty:
        return "Przekazano żądanie. Trwa oczekiwanie na rezerwację źródeł."
    if isinstance(claims, str):
        return "Błąd uruchomienia · " + claims
    if not claims:
        return "Przebieg już trwa lub właśnie wystartował z timera."
    return "Uruchomiono · " + ", ".join(claims)


@st.dialog("Diagnostyka Meta")
def diagnostic_dialog(file, sid, options):
    country = options["country"]
    st.caption("Frazy przycisku „Uruchom teraz” dla tego źródła:")
    st.text(" · ".join(options["phrases"]))
    enabled = diagnostic_enabled(options)
    if not enabled:
        st.info("Pomiar wymaga trybu live i skonfigurowanego uprawnienia Meta.")
    with st.form("meta-diagnostic"):
        phrase = st.text_input("Fraza do sprawdzenia", value=options["phrases"][0], max_chars=200).strip()
        st.form_submit_button("Pokaż zapis adaptera")
        submit = st.form_submit_button("Sprawdź HTTP w Chrome", disabled=not enabled)
    if not phrase:
        st.warning("Wpisz frazę wyszukiwania.")
        return
    st.subheader("Ostatni przebieg adaptera live")
    st.text(f"{phrase} · {country}")
    run = last_live_run(options["state_dir"], sid, phrase, country)
    if run:
        st.caption(f"{run['started']} · {run['trigger']} · {run['run_id'][:10]}")
        st.text(f"Stan przebiegu · {STATUS.get(run['status'], run['status'])}")
        if run["country"] is None:
            st.caption("Brak zapisanych kart dla tej frazy. Kraj tego przebiegu nie został utrwalony.")
        else:
            st.text(f"Zapisane karty dla frazy · {run['cards']}")
        if run["http"]:
            st.text(f"Status dokumentu zapisany przy kartach · HTTP {run['http']}")
        if run["error"] and run["phrase"] == phrase:
            st.text(run["error"])
    else:
        st.caption("Brak zapisanego przebiegu live dla tego wyszukiwania.")
    st.subheader("Osobny pomiar w Chrome")
    st.caption("Chrome mierzy pierwszą odpowiedź dokumentu i kończy próbę przed odczytem kart.")
    if submit:
        with st.spinner("Chrome sprawdza dokument wyników…"):
            result = run_diagnostic(file, phrase)
        st.session_state["meta-diagnostic-result"] = {"phrase": phrase, "country": country, **result}
    result = st.session_state.get("meta-diagnostic-result")
    if result and (result["phrase"], result["country"]) == (phrase, country):
        st.text(f"{result['phrase']} · {result['country']}")
        if result.get("started_at"):
            st.caption(result["started_at"])
        status = result.get("http_status")
        if status == 403:
            st.error("HTTP 403 · Serwer odmówił dostępu do dokumentu wyników.")
        elif status is None:
            st.warning("Brak zmierzonego statusu HTTP.")
        elif 200 <= status < 300:
            st.success(f"HTTP {status} · Serwer odpowiedział na żądanie dokumentu.")
            st.caption("Pomiar kończy się przed odczytem kart. Liczba wyników pozostaje nieustalona.")
        else:
            st.text(f"HTTP {status} · Pierwsza odpowiedź serwera.")
        if result.get("error"):
            st.text(result["error"])
        if result.get("url"):
            st.code(result["url"], language=None)


def manual_import(file, config):
    sources = [sid for sid, opts in config["sources"].items() if opts.get("manual_import")]
    if not sources:
        return
    with st.expander("Import ręcznie zapisanego wyszukiwania"):
        sid = st.selectbox("Dostawca importu", sources, format_func=lambda k: config["sources"][k]["name"])
        if config["sources"][sid].get("using_manual_selection"):
            if st.button("Przywróć ustawienia źródła z konfiguracji"):
                restore_config(config, sid)
                st.rerun()
        with st.form("manual-import"):
            opts = config["sources"][sid]
            phrase = st.text_input("Fraza użyta przy zapisie", value=opts["phrases"][0])
            country = st.text_input("Kraj wyszukiwania", value=opts["country"], max_chars=2)
            upload = st.file_uploader("Zapis wyników (HTML lub JSON)", type=["html", "htm", "json"])
            st.caption("Po imporcie kolejne uruchomienia tego źródła będą czytać wybrany zapis.")
            submit = st.form_submit_button("Zapisz i uruchom import")
        if submit:
            if not upload:
                st.error("Wybierz plik zapisanego wyszukiwania.")
            else:
                try:
                    save_import(config, sid, upload.name, upload.getvalue(), phrase, country.strip().upper())
                    st.session_state["notice"] = start(load_config(file), [sid])
                    st.rerun()
                except (OSError, ValueError) as exc:
                    st.error(str(exc))


@st.cache_data(max_entries=2048, show_spinner=False)
def coverage(folder):
    meta = read_json(folder / "manifest.json")
    if "landing_summary" in meta:
        return meta["landing_summary"]
    saved = read_json(folder / "extracted.json")
    visit = saved.get("landing_visit", {})
    return {"cta": bool(visit.get("attribute") or saved.get("ad_page_links")), "document": bool(saved["pages"]),
            "reason": visit.get("reason"), "issues": visit.get("issues", [])}


def run_pages(root, select):
    with connection(root / "discovery.sqlite3") as db:
        groups = db.execute("""SELECT r.run_id,o.phrase,r.source_id,datetime(r.started,'unixepoch') AS started
                            FROM runs r JOIN observations o ON o.run_id=r.run_id
                            GROUP BY r.run_id,o.phrase ORDER BY r.started DESC,o.phrase""").fetchall()
        if not groups:
            return
        choices = [(r["run_id"], r["phrase"]) for r in groups]
        labels = {(r["run_id"], r["phrase"]): f"{r['phrase']} · {r['source_id']} · {r['started']} UTC" for r in groups}
        first = next((i for i,key in enumerate(choices) if key[0] == st.query_params.get("przebieg")
                      and key[1] == st.query_params.get("fraza", key[1])), 0)
        st.subheader("Odczyt stron docelowych")
        selected = st.selectbox("Przebieg i fraza", choices, index=first, format_func=labels.get, key="coverage-run")
        rows = db.execute("""SELECT o.ad_ref,o.card,o.capture_id,j.status AS page_status,j.error AS job_error
                          FROM observations o LEFT JOIN page_jobs j USING(seq)
                          WHERE o.run_id=? AND o.phrase=? ORDER BY o.seq""", selected).fetchall()
    details = []
    for row in rows:
        try:
            record = coverage(root / "captures" / row["capture_id"])
        except (KeyError, ValueError, OSError):
            record = {"reason": "Nie udało się odczytać pakietu"}
        details.append((row, record))
    st.write(f"Karty · {len(rows)}   |   Z celem CTA · {sum(bool(r.get('cta')) for _, r in details)}"
             f"   |   Odczytane strony · {sum(bool(r.get('document')) for _, r in details)}")
    table = []
    for row, r in details:
        name = json.loads(row["card"]).get("page_name") or row["ad_ref"]
        table.append({"Reklama": name, "ID emisji": row["ad_ref"],
                      "Wizyta": PAGE_STATUS.get(row["page_status"], "—"), "Powód": row["job_error"] or "",
                      "Strona": "Odczytano HTML" if r.get("document") else r.get("reason") or "Brak zapisanego HTML",
                      "Renderowanie": ("Częściowe" if r.get("issues") else "Zapisany widok" if r.get("screen") else "Brak oceny"),
                      "Widok": ("Wykryto okno cookies" if r.get("dialog") else
                                "Jednolity środek zrzutu" if (r.get("screen") or {}).get("mostly_uniform") else "—"),
                      "Treść oferty": ("Wykryto" if r.get("offer") else "Nie oceniono" if r.get("document") and "offer" not in r
                                       else "Brak rozpoznanej treści" if r.get("document") else "—")})
    st.dataframe(table, hide_index=True)
    pick = st.selectbox("Dowody reklamy z tego przebiegu", range(len(rows)),
                        format_func=lambda i: f"{table[i]['Reklama']} · {table[i]['ID emisji']}")
    if st.button("Otwórz pakiet reklamy"):
        select(rows[pick]["capture_id"])
        st.rerun()


@st.fragment(run_every=1)
def monitor(file, select):
    config = load_config(file)
    state = panel_engine(config).snapshot()
    root = Path(config["state_dir"])
    clock = root / "clock"
    try:
        ticking = time.time() - float(clock.read_text(encoding="ascii")) < 12
    except (OSError, ValueError):
        ticking = False
    st.caption(("Zegar działa" if ticking else "Zegar poza połączeniem") +
               f" · interwał domyślny {config['interval_seconds']:g} s · czasy UTC")
    for mode_name in sorted({s["mode"] for s in config["sources"].values()}):
        graph = root / "graph" / (mode_name + ".jsonl")
        if graph.with_suffix(".error").is_file():
            st.warning("Błąd aktualizacji grafu · " + mode_name)
        if graph.is_file():
            st.caption(f"Dane dla grafu · {mode_name} · {graph}")
        report = graph.with_suffix(".campaigns.json")
        if report.is_file():
            groups = read_json(report)
            with st.expander(f"Kampanie · {mode_name} · {len(groups['campaigns'])}"):
                st.caption(f"Przeliczono {groups['computed_at']} · powiązania {len(groups['edges'])}"
                           f" · emisje bez kampanii {len(groups['unassigned'])}")
                if groups.get("unavailable"):
                    st.write("Emisje z brakującym lub uszkodzonym pakietem dowodowym")
                    st.dataframe(groups["unavailable"], hide_index=True)
                for campaign in groups["campaigns"]:
                    st.text(campaign["campaign"] + " · " + ", ".join(m["ad_id"] for m in campaign["members"]))
                if groups["edges"]:
                    st.dataframe([{"Emisja A": e["a"], "Emisja B": e["b"], "Wynik": e["score"],
                                   "Uzasadnienie": ", ".join(r["detail"] for r in e["reasons"])}
                                  for e in groups["edges"]], hide_index=True)
    st.subheader("Stan źródeł")
    for source in state["sources"]:
        opts = config["sources"][source["source_id"]]
        with st.container(border=True):
            top, mode = st.columns([3, 1])
            top.subheader(opts["name"])
            mode.text(f"{source['run_mode'] or source['mode']} · {STATUS.get(source['status'], source['status'])}")
            if source["run_mode"] and source["run_mode"] != source["mode"]:
                st.caption(f"Tryb następnego uruchomienia · {source['mode']}")
            if opts.get("requires_web_permission") and not str(opts.get("permission", "")).strip():
                st.caption("Live · brak zadeklarowanego uprawnienia do automatycznego odczytu WWW Meta.")
            if source["mode"] == "replay":
                st.caption("Odtworzenie lokalne · " + ("własne dane syntetyczne" if opts.get("synthetic") else "zapis historyczny"))
            st.text(f"Fraza · {source['phrase'] or '—'}")
            st.text(f"Odczytane {source['read_count']}   ·   Nowe {source['new_count']}   ·   Znane {source['known_count']}   ·   Braki w karcie {source['missing_count']}")
            st.caption(f"Ostatni sukces {source['last_success'] or '—'}   ·   Następne uruchomienie {source['next_run']}")
            if source.get("trigger"):
                st.caption(f"Przebieg {source['run_id'][:10]} · {source['trigger']} · {source['run_mode']}")
            if source["error"]:
                st.text("Przyczyna błędu · " + source["error"])
    run_pages(root, select)
    candidates = state["candidates"]
    st.subheader(f"Kandydaci do przeglądu ({len(candidates)})")
    st.caption("Powód znalezienia opisuje dopasowanie w źródle. Ocenę podejrzenia wykonuje analityk.")
    if candidates:
        for candidate in candidates:
            opts = config["sources"].get(candidate["source_id"], {})
            with st.container(border=True):
                card = candidate["card"]
                st.text(f"{card.get('page_name') or candidate['provider']} · ID {candidate['ad_ref']}")
                st.text(f"{opts.get('name', candidate['source_id'])} · {candidate['mode']} · wykrycie {candidate['found_at']}")
                if candidate["page_status"]:
                    st.text("Strona docelowa · " + PAGE_STATUS.get(candidate["page_status"], candidate["page_status"]))
                when = candidate.get("observed_at") or card.get("observation_date")
                if when:
                    st.text(f"Data zapisu źródłowego · {when}")
                st.text("Powód · " + "\n".join(candidate["reasons"]))
                if card.get("observer_note"):
                    st.text("Notatka z zapisu · " + str(card["observer_note"]))
                if st.button("Otwórz znalezisko", key="open-" + candidate["provider"] + "/" + candidate["ad_ref"]):
                    select(candidate["capture_id"])
                    st.rerun()
    else:
        st.write("Brak zapisanych kandydatów.")


@st.fragment(run_every=1)
def follow_page(db_path, capture_id, select):
    with connection(db_path) as db:
        job = db.execute("""SELECT j.status,j.error,o.capture_id FROM page_jobs j JOIN observations o USING(seq)
                            WHERE j.base_capture=? ORDER BY j.seq DESC LIMIT 1""", (capture_id,)).fetchone()
    if job:
        st.text("Strona docelowa · " + PAGE_STATUS.get(job["status"], job["status"]))
        if job["error"]:
            st.text(job["error"])
        if job["capture_id"] != capture_id and st.button("Otwórz uzupełniony pakiet"):
            select(job["capture_id"])
            st.rerun()


def show(file, detail, select):
    config = load_config(file)
    root = Path(config["state_dir"]) / "captures"
    selected = st.query_params.get("znalezisko")
    if selected:
        if st.button("← Wróć do wyszukiwania"):
            st.query_params.pop("znalezisko", None)
            st.session_state.pop("proof", None)
            st.rerun()
        errors = []
        records = catalog(root, errors)
        if selected in records:
            panel_engine(config)
            follow_page(root.parent / "discovery.sqlite3", selected, select)
            detail(records, selected)
        else:
            st.error("Nie znaleziono czytelnego pakietu dla wybranej obserwacji.")
        return
    st.title("Wyszukiwanie reklam")
    choice, action = st.columns([3, 1], vertical_alignment="bottom")
    sources = config["sources"]
    selected_source = choice.selectbox("Zakres uruchomienia", ["*"] + list(sources),
                                       format_func=lambda k: "Wszystkie źródła" if k == "*" else sources[k]["name"])
    if action.button("Uruchom teraz", type="primary"):
        selected_ids = None if selected_source == "*" else [selected_source]
        st.session_state["notice"] = start(config, selected_ids)
    if st.session_state.get("notice"):
        st.info(st.session_state["notice"])
    meta_sid = next((sid for sid, opts in sources.items()
                     if opts.get("adapter") == "scamgraph.discovery.meta:fetch"), None)
    if meta_sid and st.button("Diagnostyka Meta"):
        diagnostic_dialog(file, meta_sid, sources[meta_sid])
    manual_import(file, config)
    monitor(file, select)
    with st.expander("Pakiety z importu offline"):
        for folder in sorted(root.glob("*/manifest.json")):
            if folder.parent.name.startswith("."):
                continue
            if st.button(folder.parent.name, key="bundle-" + folder.parent.name):
                select(folder.parent.name)
                st.rerun()
