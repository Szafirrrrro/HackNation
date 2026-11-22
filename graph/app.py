"""ScamGraph — lokalny demonstrator dla analityka (Streamlit)."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace
import hashlib
from html import escape
from itertools import accumulate
from pathlib import Path
import re
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from pyvis.network import Network

# Make repository adapters available in both launch modes.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scamgraph.analyst_store import private_corpus_path, append_private_card, read_private_cards
from scamgraph.analyst_corpus import AnalystCorpus, identify_corpus, load_analyst_corpus, source_stamp
from scamgraph.analyst_timeline import card_events, event
from scamgraph import image_query
from models.common.import_rows import deduplicate_rows

from graph.ftf_graph.card import parse_card
from graph.ftf_graph.matching import build_reference
from graph.ftf_graph.presentation import card_tooltip
from graph.ftf_graph.scoring import Config
from graph.ftf_graph.trusted import load_trusted

PALETTE = ["#5CF2CA", "#85A7FF", "#FBC46B", "#D69BFF", "#F98ABB", "#F7A389",
           "#40CEDF", "#BDD773", "#E8888D", "#84D284", "#9F9CFF", "#EBA6CC"]
NOISE_COLOR = "#9DA9B8"
NEW_COLOR = "#FF92B5"
PAGE_COLOR = "#52D9F5"
NOISE_LABEL = "bez kampanii"
PAGE_LABEL = "Zapis strony"
TIMELINE_STEPS = (
    ("triangle-up", "▲", "Publikacja", ("Publikacja",)),
    ("square", "■", "Pozyskanie lub zapis strony", ("Pozyskanie", "Obserwacja strony",
     "Obserwacja powiązanej strony", "Obserwacja w schedulerze")),
    ("circle", "●", "Pierwsza obserwacja lub wykrycie", ("Pierwsza obserwacja", "Pierwsze wykrycie")),
    ("circle-open", "○", "Ostatnia obserwacja lub wykrycie", ("Ostatnia obserwacja", "Ostatnie wykrycie")),
    ("cross", "✚", "Ekstrakcja", ("Ekstrakcja",)),
    ("diamond", "◆", "Różne rodzaje zdarzeń tego samego dnia", ()),
)
EVENT_SYMBOL = {kind: symbol for symbol, _, _, kinds in TIMELINE_STEPS for kind in kinds}
GRAPH_INSPECTOR = Path(__file__).with_name("node-inspector.html").read_text(encoding="utf-8")
BOOTSTRAP_TAGS = re.compile(
    r'<link\b[^>]*\bhref="https://cdn\.jsdelivr\.net/npm/bootstrap@[^\"]*"[^>]*>'
    r'|<script\b[^>]*\bsrc="https://cdn\.jsdelivr\.net/npm/bootstrap@[^\"]*"[^>]*>\s*</script>'
)

st.set_page_config(page_title="ScamGraph · Mapa kampanii", layout="wide")
st.html(Path(__file__).with_name("analyst.css"))


def with_unique_ids(new: list[dict], taken: set[str]) -> list[dict]:
    out = []
    for k, card in enumerate(new):
        card = dict(card)
        base = card.get("ad_id") or f"NEW-{k + 1}"
        cid, n = base, 1
        while cid in taken:
            n += 1
            cid = f"{base}-{n}"
        card["ad_id"] = cid
        taken.add(cid)
        out.append(card)
    return out


def standalone_page(raw):
    return raw.get("provenance", {}).get("record_kind") == "page_capture"


def save_material(corpus_path, raw):
    saved = dict(raw)
    provenance = saved.get("provenance", {})
    if provenance.get("record_kind") == "image_query":
        saved["provenance"] = {**provenance, "record_kind": "image_reference"}
    try:
        append_private_card(corpus_path, saved)
    except (OSError, ValueError) as exc:
        st.session_state["analyst_save_error"] = (
            provenance.get("record_kind"), f"Nie zapisano materiału: {exc}"
        )
        return
    st.toast(f"Dopisano {saved['ad_id']} do prywatnego korpusu.")
    if provenance.get("source") == "upload":
        st.session_state.pop("image_analysis", None)
    if provenance.get("record_kind") == "page_capture":
        st.session_state.pop("url_capture", None)


# ---------------------------------------------------------------- graf
def build_graph_html(cards, edges, camps, camp_of, colors, new_ids, show_similar, show_noise, height,
                     hidden: set[str] = frozenset()) -> str:
    net = Network(height=f"{height}px", width="100%", bgcolor="#161616", cdn_resources="in_line")
    net.barnes_hut(gravity=-2200, central_gravity=0.55, spring_length=110, spring_strength=0.04,
                   overlap=0.65)
    net.set_edge_smooth("continuous")
    present: set[str] = set()

    for c in camps:
        nid = f"camp:{c.id}"
        color = colors[c.id]
        net.add_node(nid, label=f"{c.id}\n{len(c.members)} reklam", shape="diamond", size=29,
                     color=color, detailColor=color, detailKind="Kampania",
                     shadow={"enabled": True, "color": color + "66", "size": 17, "x": 0, "y": 0},
                     font={"color": "#ECECEA", "face": "Segoe UI, sans-serif", "size": 18},
                     title=(f"{c.id}\n{len(c.members)} reklam\n"
                            f"Aktywne: {c.alive} · martwe: {c.dead}\nWizerunek: {', '.join(c.persons) or '—'}"))
        present.add(nid)

    for i, card in enumerate(cards):
        cid, is_new = camp_of[i], card.id in new_ids
        is_page = standalone_page(card.raw)
        if card.id in hidden or (cid is None and not show_noise and not (is_new or is_page)):
            continue
        color = PAGE_COLOR if is_page else colors.get(cid, NOISE_COLOR)
        kind = PAGE_LABEL if is_page else "Reklama"
        accent = NEW_COLOR if is_new else color
        net.add_node(card.id, label=("★ " if is_new else "") + card.id,
                     shape="star" if is_new else ("square" if is_page else "dot"), size=26 if is_new else 12,
                     color={"background": accent, "border": accent,
                            "highlight": {"background": accent, "border": "#F4F9FF"}},
                     detailColor=accent, detailKind=f"Zgłoszenie · {kind.lower()}" if is_new else kind,
                     shadow={"enabled": bool(is_new or cid or is_page), "color": accent + "77",
                             "size": 11, "x": 0, "y": 0},
                     borderWidth=2 if is_new else 1,
                     font={"color": NEW_COLOR if is_new else "#D3DEE9",
                           "face": "Segoe UI, sans-serif", "size": 16 if is_new else 13},
                     title=card_tooltip(card, PAGE_LABEL if is_page else cid or NOISE_LABEL))
        present.add(card.id)
        if cid:
            net.add_edge(card.id, f"camp:{cid}", color=color, width=1.5, dashes=is_new,
                         title="Sugerowane przypisanie" if is_new else "Członek referencji")

    for e in edges:
        a, b = cards[e.a].id, cards[e.b].id
        if a not in present or b not in present:
            continue
        touches_new = a in new_ids or b in new_ids
        if not (show_similar or touches_new):
            continue
        reasons = "\n".join(f"{'[TWARDY]' if r.hard else '[MIĘKKI]'} +{r.strength:.2f} {r.detail}" for r in e.reasons)
        net.add_edge(a, b, width=1 + 2.5 * e.score, dashes=not e.has_hard,
                     color=NEW_COLOR if touches_new else "#536476",
                     physics=camp_of[e.a] == camp_of[e.b],
                     title=f"SIMILAR {a} – {b}: score {e.score:.2f}\n{reasons}")
    html = BOOTSTRAP_TAGS.sub("", net.generate_html())
    html = html.replace("</body>", GRAPH_INSPECTOR + "\n</body>", 1)
    # pyvis switches to a custom HTML popup when any title contains "href".
    # Captured titles remain text in that template too, including literal markup.
    return html.replace("popup.innerHTML = nodeData[0].title;", "popup.innerText = nodeData[0].title;").replace(
        "<head>", "<head>\n<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; "
        "script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:\">", 1)


# ---------------------------------------------------------------- oś czasu
def render_timeline(cards, pages, camps, camp_of, colors, new_ids, show_noise, hidden):
    scope = st.selectbox("Kampania na osi czasu", ["Wszystkie kampanie", *(c.id for c in camps)])
    with st.expander("Jak czytać oś czasu"):
        st.markdown(
            "1. Wybierz kampanię z listy. Każda linia pokazuje, ile zdarzeń odnotowano do danego dnia UTC.\n"
            "2. Najedź na oznaczony krok, aby zobaczyć liczbę zdarzeń i ich rodzaje.\n"
            "3. Otwórz tabelę **Zdarzenia i źródła dat**, aby odczytać dokładne wartości i ich pochodzenie."
        )
        steps = "".join(f'<li><span aria-hidden="true">{glyph}</span>{label}</li>'
                        for _, glyph, label, _ in TIMELINE_STEPS)
        st.html(f'<ul class="analyst-step-guide" aria-label="Ikony zdarzeń">{steps}</ul>')
    camp_by_id, seen = {}, []
    missing, missing_publication = [], []
    for i, card in enumerate(cards):
        cid = PAGE_LABEL if standalone_page(card.raw) else camp_of[i] or NOISE_LABEL
        if card.id in hidden or (cid == NOISE_LABEL and not show_noise and card.id not in new_ids):
            continue
        if scope != "Wszystkie kampanie" and scope != cid:
            continue
        camp_by_id[card.id] = cid
        events = card_events(card)
        seen.extend(events)
        if not events:
            missing.append(card.id)
        if (card.raw.get("provenance", {}).get("record_kind") not in {"page_capture", "image_query"}
                and not any(row.kind == "Publikacja" and row.precision != "nieczytelna data" for row in events)):
            missing_publication.append(card.id)
    if scope == "Wszystkie kampanie":
        for page in pages:
            label = f"Strona · {page.id}"
            value, source = page.captured_at
            camp_by_id[label] = PAGE_LABEL
            if item := event(label, "Obserwacja strony", value, source):
                seen.append(item)
            else:
                missing.append(label)
    daily = defaultdict(lambda: defaultdict(Counter))
    for row in seen:
        if row.instant is not None:
            daily[camp_by_id[row.record_id]][row.instant.date()][row.kind] += 1
    if daily:
        st.caption("Łączna liczba zdarzeń narastająco. Dokładne daty i pola źródłowe znajdziesz pod wykresem.")
        fig = go.Figure()
        days = sorted({day for counts in daily.values() for day in counts})
        for name, color in {**colors, PAGE_LABEL: PAGE_COLOR, NOISE_LABEL: NOISE_COLOR}.items():
            if name not in daily:
                continue
            events = [daily[name].get(day, {}) for day in days]
            counts = [sum(kinds.values()) for kinds in events]
            symbols = [EVENT_SYMBOL.get(next(iter(kinds)), "diamond") if len(kinds) == 1 else "diamond"
                       for kinds in events]
            breakdowns = ["<br>".join(f"{count} × {kind}" for kind, count in sorted(kinds.items()))
                          for kinds in events]
            rgb = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
            fig.add_scatter(
                name=name, x=[day.isoformat() for day in days], y=list(accumulate(counts)),
                mode="lines+markers",
                line={"color": color, "width": 2.6, "shape": "hv"},
                marker={"color": color, "symbol": symbols, "size": [8 if count else 0 for count in counts]},
                fill="tozeroy", fillcolor=f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, 0.08)",
                customdata=list(zip(counts, breakdowns)),
                hovertemplate=("%{y} łącznie · %{customdata[0]} w tym dniu<br>"
                               "%{customdata[1]}<extra>%{fullData.name}</extra>"),
            )
        fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          font={"color": "#BDBDB9", "family": "Segoe UI, sans-serif"},
                          legend={"orientation": "h", "y": -0.24, "title_text": ""},
                          hovermode="x unified", height=320, margin={"l": 10, "r": 12, "t": 12, "b": 24})
        fig.update_xaxes(type="date", gridcolor="#303030", tickformat="%d.%m.%Y", nticks=5,
                         title_text="Dzień (UTC)", automargin=True)
        fig.update_yaxes(gridcolor="#303030", rangemode="tozero", dtick=1 if len(seen) < 8 else None,
                         title_text="Zdarzenia łącznie", automargin=True)
        st.plotly_chart(fig, width="stretch", theme=None, config={"displayModeBar": False})
    else:
        st.info("Brak zdarzeń z czasem i strefą do naniesienia na oś.")
    if seen:
        with st.expander("Zdarzenia i źródła dat", expanded=any(row.instant is None for row in seen)):
            labels = ("Materiał", "Zdarzenie", "Data źródłowa", "Precyzja", "Źródło")
            headings = "".join(f'<th scope="col">{label}</th>' for label in labels)
            rows = []
            for row in seen:
                values = (row.record_id, row.kind, row.value, row.precision, row.source)
                cells = "".join(f"<td>{escape(str(value))}</td>" for value in values)
                rows.append(f"<tr>{cells}</tr>")
            table = f"<table><thead><tr>{headings}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
            st.html(f'<div class="analyst-evidence-table" tabindex="0" role="region" '
                    f'aria-label="Daty i źródła zdarzeń">{table}</div>')
    if missing:
        st.caption("Brak dat obserwacji: " + ", ".join(missing))
    if missing_publication:
        st.caption("Data publikacji nieustalona: " + ", ".join(missing_publication))


def source_image(card) -> bytes | None:
    provenance = card.raw.get("provenance", {})
    image_path = provenance.get("image_path")
    try:
        if not image_path:
            visual_ref = card.raw.get("visual", {}).get("source_ref")
            folder = provenance.get("snapshot")
            if not (isinstance(folder, str) and isinstance(visual_ref, dict)
                    and isinstance(visual_ref.get("file"), str)):
                return None
            root = Path(folder).resolve()
            path = (root / visual_ref["file"]).resolve()
            if not path.is_relative_to(root):
                return None
        else:
            path = Path(image_path)
        if not card.image_sha256 or not path.is_file() or path.stat().st_size > image_query.MAX_BYTES:
            return None
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != card.image_sha256:
            return None
        image_query.validate_image(data)
        return data
    except (OSError, TypeError, ValueError, RuntimeError):
        return None


def render_pair(edge, cards):
    left, right = cards[edge.a], cards[edge.b]
    st.text(f"{left.id} ↔ {right.id} · podobieństwo {edge.score:.2f} · ocena kampanii {edge.campaign_score:.2f}")
    for reason in edge.reasons:
        st.text(f"{'Twardy' if reason.hard else 'Miękki'} +{reason.strength:.2f} · {reason.detail}")
    if edge.observations:
        st.dataframe(pd.DataFrame([{"ślad": r.kind, "metoda": r.method, "miara": r.metric,
                                   "wartość": str(r.value) if r.value is not None else "",
                                   "próg": str(r.threshold) if r.threshold is not None else "",
                                   "siła": r.strength, "wkład w ocenę kampanii": r in edge.campaign_reasons}
                                  for r in edge.observations]), width="stretch", hide_index=True)
    for column, card, side in zip(st.columns(2), (left, right), ("a", "b")):
        with column:
            st.text(f"Źródło · {card.id}")
            if data := source_image(card):
                st.image(data, caption=card.id, width=320)
            if card.ad_text:
                st.text(card.ad_text[:1200])
            rows = [{"pole": getattr(r, f"field_{side}"), "pochodzenie": getattr(r, f"origin_{side}"),
                     "źródło": getattr(r, f"source_ref_{side}"), "metoda": getattr(r, f"method_{side}")}
                    for r in edge.observations]
            st.json({"provenance": card.raw.get("provenance", {}), "porównane_pola": rows,
                     "ekstrakcja": card.raw.get("extraction", {})}, expanded=False)


def render_pages(pages, report):
    if not pages:
        return
    st.subheader("Samodzielne zapisy stron")
    st.caption(f"Zapisy stron: {len(pages)} · zweryfikowane powiązania z emisjami: {report.get('verified_links', 0)}. "
               "Wspólny tytuł, nagłówek lub piksel opisuje wybrane strony.")
    options = [page.id for page in pages]
    by_id = {page.id: page for page in pages}
    with st.expander("Porównaj dwa zapisy stron"):
        first, second = st.columns(2)
        left = by_id[first.selectbox("Pierwsze źródło strony", options, key="capture-left")]
        right = by_id[second.selectbox("Drugie źródło strony", options, min(1, len(options) - 1), key="capture-right")]
        if left.id != right.id:
            headings = [p.html.get("headings") for p in (left, right)]
            common = set(h for h in headings[0] if isinstance(h, str)).intersection(
                h for h in headings[1] if isinstance(h, str)) if all(isinstance(h, list) for h in headings) else set()
            st.write("Wspólne nagłówki: " + (" · ".join(sorted(common)) or "brak"))
            st.write("Wspólne identyfikatory Meta Pixel (HAR): " + (", ".join(sorted(left.pixels & right.pixels)) or "brak"))
        for column, page in ((first, left), (second, right)):
            value, source = page.captured_at
            column.caption(source)
            column.write(page.url or "Adres nieustalony")
            column.write(f"Czas obserwacji: {value or 'nieustalony'} · HTTP {page.har.get('document_status') or 'nieustalony'}")
            column.json(page.record, expanded=False)


def render_url_capture(corpus):
    with st.form("capture-url"):
        st.subheader("Przechwyć stronę z linku", anchor=False)
        st.caption("Wklej adres strony. Po pobraniu dane automatycznie trafią do analizy i na graf.")
        page_url = st.text_input("Adres strony (HTTP lub HTTPS)", placeholder="https://…")
        fetch_page = st.form_submit_button("Przechwyć stronę", type="primary")
    if fetch_page:
        st.session_state.pop("url_capture", None)
        st.session_state.pop("url_lookup", None)
        try:
            from scamgraph.url_capture import capture_url, existing_url_ids, url_key
            known = existing_url_ids(page_url, corpus)
            st.session_state["url_lookup"] = page_url
            if not known:
                with st.spinner("Pobieranie strony i przygotowywanie danych…"):
                    captured = capture_url(page_url)
                    if captured.get("card"):
                        captured["card"].setdefault("provenance", {})["url_key"] = url_key(page_url)
                    st.session_state["url_capture"] = captured
        except ImportError:
            st.error("Brakuje zależności scrapera. Zainstaluj requirements-capture.txt z katalogu projektu.")
        except (ValueError, OSError, RuntimeError) as exc:
            st.error(f"Nie udało się przechwycić strony ({type(exc).__name__}): {exc}")

    if result := st.session_state.get("url_capture"):
        report = result["report"]
        if report.get("status") == "trusted_domain":
            st.warning("Pobranie zostało pominięte przez wcześniejszą wersję aplikacji. "
                       "Wyślij URL ponownie. Ranking domen nie potwierdza bezpieczeństwa strony.")
        else:
            if report.get("status") == "success" and report.get("content_status") == "usable":
                st.success("Strona została przechwycona.")
            else:
                st.warning("Zapis niepełny lub treść niedostępna. Sprawdź raport pobrania.")
            st.caption(f"Zapis lokalny: {result['archive']}")
            with st.expander("Raport pobrania", expanded=report.get("status") != "success"):
                st.json(report)
            if result.get("extraction_error"):
                st.warning(result["extraction_error"])
            archive = Path(result["archive"])
            screenshot = archive / "screenshot.png"
            if screenshot.is_file():
                st.image(str(screenshot), caption="Zrzut przechwyconej strony", width=700)
            if result.get("card"):
                st.success("Dane strony zostały automatycznie wczytane do analizy.")
                st.caption("Porównujesz obserwację strony. Wynik nie potwierdza jej związku z konkretną reklamą.")
            else:
                st.warning("Brak użytecznej strony do analizy. Spróbuj innego adresu.")


def render_image_query():
    with st.container(key="analyst-ad-form"):
        with st.form("analyze-image", border=False):
            upload, metadata = st.columns(2, gap="medium")
            with upload.container(key="ad-upload"):
                st.subheader("Kreacja reklamy", anchor=False)
                st.caption("Wybierz lub upuść jedno zdjęcie reklamy. PNG, JPEG lub WebP do 20 MiB.")
                uploaded_image = st.file_uploader("Zdjęcie reklamy (wymagane)", type=["png", "jpg", "jpeg", "webp"])
            with metadata.container(key="ad-optional"):
                st.subheader("Dane opcjonalne", anchor=False)
                description = st.text_area("Tekst reklamy (opcjonalnie)", height=112, max_chars=10000,
                                           placeholder="Wklej treść reklamy…")
                text_origin = st.toggle("Tekst z oryginalnego opisu (opcjonalnie)")
                st.caption("Zaznacz, jeśli wpisany tekst pochodzi spoza zrzutu.")
                known_target = st.text_input("Znany adres celu reklamy (opcjonalnie)", placeholder="https://…")
            submit_image = st.form_submit_button("Porównaj reklamę", type="primary")
        if submit_image:
            st.session_state.pop("image_analysis", None)
            if uploaded_image is None:
                st.error("Dodaj zdjęcie reklamy, aby rozpocząć porównanie.")
            else:
                try:
                    with st.spinner("Odczyt zdjęcia i przygotowywanie porównania…"):
                        card = image_query.analyze_image(uploaded_image.getvalue())["card"]
                        card = image_query.supplement_query(card, description, known_target, text_origin)
                    st.session_state["image_analysis"] = {"card": card}
                except (ImportError, ValueError, OSError, RuntimeError) as exc:
                    st.error(f"Nie udało się przeanalizować reklamy: {exc}")


def set_intake_page(open_page: bool):
    if open_page:
        st.query_params["view"] = "nowa-reklama"
    else:
        st.query_params.pop("view", None)


# ---------------------------------------------------------------- UI
intake_page = st.query_params.get("view") == "nowa-reklama"
if intake_page:
    st.title("Dodaj materiał", anchor=False)
else:
    st.html('<div class="analyst-breadcrumb"><span aria-hidden="true">▦</span> Przegląd</div>')
    st.title("Mapa kampanii", anchor="przeglad")

with st.sidebar:
    st.html('<div class="analyst-brand"><span class="analyst-mark" aria-hidden="true"></span>ScamGraph</div>')
    with st.container(key="analyst-navigation"):
        st.html('<span class="analyst-nav-label">Nawigacja</span>')
        if intake_page:
            st.button("Wróć do przeglądu", icon=":material/dashboard:", width="stretch",
                      key="nav-overview", on_click=set_intake_page, args=(False,))
            st.html('<span class="analyst-current-page" aria-current="page">Dodaj materiał</span>')
        else:
            st.html("""
                <nav class="analyst-nav" aria-label="Sekcje przeglądu">
                    <a href="#przeglad"><span aria-hidden="true">▦</span>Przegląd</a>
                    <a href="#graf-kampanii"><span aria-hidden="true">◇</span>Graf kampanii</a>
                    <a href="#os-czasu"><span aria-hidden="true">◷</span>Oś czasu</a>
                </nav>
            """)
            st.button("Dodaj materiał", icon=":material/add_circle:", width="stretch",
                      key="nav-ad", on_click=set_intake_page, args=(True,))
    st.subheader("Korpus", anchor=False)
    source_mode = st.radio("Źródło referencji", ["Demo syntetyczne", "Korpus organizatora NASK", "Korpus lokalny"])
    if source_mode == "Korpus lokalny":
        selected = st.text_input("Ścieżka korpusu", placeholder="Katalog, manifest.json, ads.jsonl, pages.jsonl lub karty JSONL")
    elif source_mode == "Korpus organizatora NASK":
        selected = str(image_query.DEFAULT_REFERENCES)
    else:
        selected = str(Path(__file__).resolve().parent / "data/sample_cards.jsonl")
    if selected:
        st.caption(str(Path(selected).expanduser()))

selection_key = (source_mode, selected)
if st.session_state.get("reference_selection", selection_key) != selection_key:
    for key in ("image_analysis", "url_capture", "url_lookup", "corpus_import", "engine_reference"):
        st.session_state.pop(key, None)
st.session_state["reference_selection"] = selection_key

imported = AnalystCorpus("bez referencji")
corpus_path = None
if selected.strip():
    try:
        source = identify_corpus(Path(selected).expanduser())
        stamp = source_stamp(source)
        import_key = (source, stamp)
        previous = st.session_state.get("corpus_import")
        if previous is None or previous[0] != import_key:
            previous = (import_key, load_analyst_corpus(source))
            st.session_state["corpus_import"] = previous
        imported = previous[1]
        corpus_path = source.storage_path
    except (ImportError, ValueError, OSError, RuntimeError) as exc:
        st.error(f"Nie udało się wczytać korpusu: {exc}")
else:
    st.info("Wskaż lokalny katalog, manifest lub plik JSONL.")
corpus = list(imported.cards)
with st.sidebar:
    imported_pages = sum(standalone_page(row) for row in corpus)
    st.caption(f"Zbiór: {imported.dataset_id} · emisje: {len(corpus) - imported_pages} · "
               f"zapisy stron: {len(imported.pages) + imported_pages} · "
               f"powtórzone pliki obrazu: {imported.report.get('repeated_images', 0)}")
    if imported.report:
        problems = imported.report.get("errors", [])
        duplicates = imported.report.get("duplicates", [])
        if problems:
            st.warning(f"Problemy importu: {len(problems)}")
        with st.expander(f"Raport importu · powtórzenia: {len(duplicates)}"):
            st.json(imported.report)

try:
    private_path = private_corpus_path(corpus_path) if corpus_path else None
except ValueError as exc:
    st.error(str(exc))
    st.stop()
if private_path and private_path.is_file():
    try:
        private_cards, skipped = read_private_cards(private_path)
    except OSError as exc:
        st.warning(f"Nie można odczytać prywatnego korpusu ({type(exc).__name__}).")
    else:
        for private_card in private_cards:
            try:
                parsed = parse_card(private_card)
                if parsed.phash is not None and not 0 <= parsed.phash < 2 ** 64:
                    raise ValueError("phash spoza 64 bitów")
                card_tooltip(parsed, NOISE_LABEL)  # the graph reads nested page fields
            except (ValueError, TypeError, AttributeError, RecursionError):
                skipped += 1
            else:
                corpus.append(private_card)
        if skipped:
            st.warning(f"Pominięto uszkodzone wiersze prywatnego korpusu: {skipped}. Plik: {private_path.name}")
        rows = list(enumerate(corpus, 1))
        overlay_errors = []
        merged, duplicates = deduplicate_rows(rows, imported.dataset_id, str(private_path), overlay_errors)
        corpus = [card for _, card in merged]
        if overlay_errors or duplicates:
            with st.expander("Powtórzenia i konflikty w prywatnym korpusie"):
                st.json({"errors": overlay_errors, "duplicates": duplicates})

dashboard = None if intake_page else st.container()
if intake_page:
    with st.container(key="analyst-intake"):
        st.caption(f"Zbiór odniesienia · {source_mode}")
        ad_tab, capture_tab = st.tabs(["Nowa reklama", "Przechwyć stronę"])
        with ad_tab:
            render_image_query()
            ad_results = st.container()
        with capture_tab:
            with st.container(key="analyst-capture-form"):
                render_url_capture(corpus)
            capture_results = st.container()

with st.sidebar:
    with st.expander("Ustawienia analizy"):
        min_cluster = st.slider("min. reklam w kampanii", 2, 10, 3)
        min_edge = st.slider("min. score krawędzi w grafie", 0.05, 0.9, 0.25, 0.05)
    with st.expander("Ustawienia grafu"):
        show_similar = st.checkbox("pokaż krawędzie SIMILAR", True)
        show_noise = st.checkbox("pokaż reklamy bez kampanii", True)
        hide_trusted = st.checkbox("ukryj reklamy prowadzące na wspólne lub popularne hosty", False,
                                   help="Domyślnie wyłączone: popularność nie świadczy o bezpieczeństwie. Po włączeniu "
                                        "nie rysujemy reklam bez kampanii, których cel to wspólny lub popularny host "
                                        "(np. youtube.com). Reklama powiązana z kampanią (np. tą samą twarzą lub głosem) zostaje.")
        graph_height = st.slider("wysokość grafu", 400, 1000, 500, 50)

image_result = st.session_state.get("image_analysis") or {}
by_id = {card["ad_id"]: card for card in corpus}

# --- dane pobranej strony trafiają bezpośrednio do silnika ---
result = st.session_state.get("url_capture") or {}
existing_page_ids = set()
if lookup := st.session_state.get("url_lookup"):
    from scamgraph.url_capture import existing_url_ids
    existing_page_ids = existing_url_ids(lookup, corpus)
if existing_page_ids:
    notice = capture_results if intake_page else st
    notice.info("Ten URL już jest w bazie danych. Podświetlono istniejący materiał na grafie.")
new_raw = [result["card"]] if result.get("card") and not existing_page_ids else []
existing_ad_id = None
if image_result.get("card"):
    candidate = image_result["card"]
    existing = by_id.get(candidate["ad_id"], {})
    if existing.get("provenance", {}).get("source") == "upload":
        existing_ad_id = candidate["ad_id"]
    else:
        new_raw.append(candidate)

new_raw = with_unique_ids(new_raw, {c.get("ad_id", "") for c in corpus})
new_ids = {c["ad_id"] for c in new_raw}
new_ids.update(existing_page_ids)
if existing_ad_id:
    new_ids.add(existing_ad_id)

try:
    config = Config(min_edge=min_edge)
    trusted = load_trusted()
    reference_key = (corpus, min_cluster, min_edge, trusted)
    snapshot = st.session_state.get("engine_reference")
    if snapshot is None or snapshot[0] != reference_key:
        reference = build_reference([parse_card(row, trusted) for row in corpus], config, min_cluster_size=min_cluster)
        snapshot = (reference_key, reference)
        st.session_state["engine_reference"] = snapshot
    reference = snapshot[1]
    cards, edges, camps = list(reference.cards), list(reference.edges), reference.campaigns
    camp_of = [reference.label_to_id.get(int(label)) for label in reference.clusters.labels]
    colors = {c.id: PALETTE[k % len(PALETTE)] for k, c in enumerate(camps)}
    decisions = {}
    for raw in new_raw:
        query_card = parse_card(raw, trusted)
        decision = reference.match(query_card)
        edges.extend(replace(edge, a=len(cards)) for edge in decision.edges)
        cards.append(query_card)
        camp_of.append(decision.campaign_id)
        decisions[query_card.id] = decision
except (ValueError, OSError, RuntimeError) as exc:
    st.error(f"Błąd analizy: {exc}")
    st.stop()

lands_trusted = {c.id for c in cards if c.final_domain and c.final_domain in c.trusted_hits}
hidden = ({c.id for i, c in enumerate(cards) if c.id in lands_trusted and camp_of[i] is None
           and c.id not in new_ids and not standalone_page(c.raw)}
          if hide_trusted else set())

if dashboard is not None:
    with dashboard:
        with st.container(key="analyst-metrics"):
            m1, m2, m3, m4, m5 = st.columns(5, gap="small")
            m1.metric("Materiały", len(cards))
            m2.metric("Kampanie", len(camps))
            m3.metric("Podobne pary", len(edges))
            m4.metric("Bez kampanii", sum(cid is None and not standalone_page(card.raw)
                                         for cid, card in zip(camp_of, reference.cards)))
            m5.metric("Ukryte reklamy", len(hidden))
        page_count = sum(standalone_page(card.raw) for card in reference.cards)
        st.caption(f"Referencja {reference.fingerprint[:16]} · emisje: {len(reference.cards) - page_count} · "
                   f"zapisy stron: {page_count + len(imported.pages)} · zgłoszenia: {len(decisions)} · "
                   f"próg kampanii {config.min_campaign:.2f}")
        card_warnings = {card.id: card.warnings for card in reference.cards if card.warnings}
        unavailable = {card.id: card.raw["unavailable"] for card in reference.cards if "unavailable" in card.raw}
        if reference.scorer.warnings or card_warnings or unavailable:
            with st.expander("Braki i ostrzeżenia referencji"):
                st.json({"porównanie": reference.scorer.warnings, "materiały": card_warnings,
                         "niedostępne_pakiety": unavailable})

ad_ids = {raw["ad_id"] for raw in new_raw if raw.get("provenance", {}).get("source") == "upload"}
if existing_ad_id:
    ad_ids.add(existing_ad_id)
if intake_page:
    for panel, result_ids in ((ad_results, ad_ids), (capture_results, new_ids - ad_ids)):
        if result_ids:
            panel.subheader("Wyniki analizy", anchor=False)
    if save_error := st.session_state.pop("analyst_save_error", None):
        kind, message = save_error
        panel = capture_results if kind == "page_capture" else ad_results
        panel.error(message)

    STATUS_LABELS = {"probable_match": "Prawdopodobne dopasowanie", "review_needed": "Do przeglądu",
                     "insufficient_evidence": "Niewystarczające dane", "no_match": "Możliwy nowy wzorzec"}
    idx = {c.id: i for i, c in enumerate(cards)}
    for nid in sorted(new_ids):
        with (ad_results if nid in ad_ids else capture_results):
            i = idx[nid]
            mine = sorted((e for e in edges if i in (e.a, e.b)), key=lambda e: -e.score)
            if decision := decisions.get(nid):
                headline = f"**{nid} · {STATUS_LABELS[decision.status]}**"
                if decision.status == "probable_match":
                    st.success(f"{headline} · **{decision.campaign_id}** · najsłabsze powiązanie do członka {decision.strength:.2f}")
                else:
                    st.warning(headline)
                if decision.exact_copies:
                    copies = ", ".join(cards[index].id for index in decision.exact_copies)
                    st.info(f"Identyczny plik obrazu (SHA-256) w referencji: {copies}.")
                if decision.similar_materials:
                    st.caption("Podobne materiały: " + ", ".join(cards[index].id for index in decision.similar_materials[:3]))
                if decision.candidate_campaigns:
                    st.caption("Kampanie do sprawdzenia: " + ", ".join(decision.candidate_campaigns[:3]))
                hidden_support = [replace(edge, a=i) for edge in decision.supporting_edges if edge.score < min_edge]
                if hidden_support:
                    with st.expander(f"Dowody przypisania poniżej progu widoku · {nid}"):
                        for edge in hidden_support:
                            render_pair(edge, cards)
                comparable = ", ".join(decision.comparable) or "brak porównywalnych rodzin"
                st.caption(f"Zakres porównania z referencją: {comparable}.")
                with st.expander(f"Braki i ograniczenia · {nid}", expanded=decision.status == "insufficient_evidence"):
                    for message in (*decision.missing, *decision.warnings):
                        st.write(message)
                    if not decision.missing and not decision.warnings:
                        st.write("Silnik nie zgłosił braków porównania.")
            if cards[i].raw.get("provenance", {}).get("record_kind") == "page_capture":
                with st.expander(f"Pełny tekst strony — {cards[i].final_domain or nid}"):
                    st.text_area("Tekst z pobranej strony", value=cards[i].ad_text,
                                 height=320, disabled=True, key=f"page-text-{nid}")
            if cards[i].trusted_hits:
                st.caption(f"Wspólne lub popularne hosty pominięte w ocenie domen: {', '.join(cards[i].trusted_hits)}")
            if mine:
                with st.expander(f"Najsilniejsze powiązania · {nid}"):
                    for edge in mine[:3]:
                        render_pair(edge, cards)
            if nid in existing_page_ids:
                st.caption("Ten URL już jest w bazie danych.")
            elif nid == existing_ad_id:
                if cards[i].image_sha256:
                    st.info("Identyczny plik obrazu (SHA-256) jest już zapisany w prywatnym korpusie.")
                else:
                    st.info("To zgłoszenie jest już zapisane w prywatnym korpusie.")
            elif corpus_path:
                raw = next(c for c in new_raw if c["ad_id"] == nid)
                st.button(f"Dopisz {nid} do prywatnego korpusu", key=f"save-{nid}",
                          on_click=save_material, args=(corpus_path, raw))

if intake_page and image_result:
    with ad_results:
        image_card = image_result["card"]
        for warning in image_card.get("extraction", {}).get("warnings", []):
            st.warning(warning)
        with st.expander("Zdjęcie i raport ekstrakcji"):
            if image_path := image_card["provenance"].get("image_path"):
                st.image(image_path, caption="Przesłane zdjęcie", width=400)
                st.caption("OCR i obraz stanowią wspólne źródło dowodu. Adresy z OCR pozostają tekstem.")
            st.text(image_card.get("text", {}).get("ad_text") or "Brak tekstu.")
            st.json(image_card.get("extraction", {}))
        overview, clear = st.columns(2, gap="small")
        overview.button("Wróć do przeglądu", icon=":material/arrow_back:", key="return-from-ad",
                        on_click=set_intake_page, args=(False,))
        clear.button("Wyczyść zgłoszenie", key="clear-image",
                     on_click=st.session_state.pop, args=("image_analysis", None))

if intake_page and new_ids - ad_ids:
    capture_results.button("Wróć do przeglądu", icon=":material/arrow_back:", key="return-from-capture",
                           on_click=set_intake_page, args=(False,))

if dashboard is not None:
    with dashboard:
        with st.container(key="analyst-graph"):
            st.header("Graf kampanii", anchor="graf-kampanii")
            st.html("""
                <ul class="analyst-legend" aria-label="Legenda grafu">
                    <li><span class="legend-campaign" aria-hidden="true">◆</span>Kampania</li>
                    <li><span aria-hidden="true">●</span>Reklama</li>
                    <li><span class="legend-page" aria-hidden="true">■</span>Zapis strony</li>
                    <li><span class="legend-query" aria-hidden="true">★</span>Zgłoszenie</li>
                </ul>
            """)
            st.caption("Kliknij węzeł lub wybierz go z listy, aby otworzyć szczegóły. Kolor wskazuje kampanię, "
                       "szary oznacza brak grupy. Linie ciągłe oznaczają twarde ślady, a przerywane tylko miękkie.")
            components.html(build_graph_html(cards, edges, camps, camp_of, colors, new_ids,
                                             show_similar, show_noise, graph_height, hidden),
                            height=graph_height, scrolling=False, tab_index=0)
            if edges:
                with st.expander("Dowody par · otwórz oba źródła"):
                    by_pair = {f"{cards[edge.a].id} ↔ {cards[edge.b].id}": edge for edge in edges}
                    pair = st.selectbox("Wybierz parę z grafu", list(by_pair), index=None, placeholder="Wybierz parę")
                    if pair is not None:
                        render_pair(by_pair[pair], cards)

        with st.container(key="analyst-timeline"):
            st.header("Oś czasu kampanii", anchor="os-czasu")
            render_timeline(cards, imported.pages, camps, camp_of, colors, new_ids, show_noise, hidden)

        render_pages(imported.pages, imported.report)
        with st.expander("Kampanie — podsumowanie"):
            st.dataframe(pd.DataFrame([{
                "kampania": c.id, "reklamy": len(c.members),
                "aktywne": c.alive, "martwe": c.dead, "domeny docelowe": len(c.final_domains),
                "wizerunek": ", ".join(c.persons), "śr. score": round(c.mean_edge, 2),
                "wspólne ślady": ", ".join(f"{k} ×{v}" for k, v in c.shared[:4]),
            } for c in camps]), width="stretch", hide_index=True)
