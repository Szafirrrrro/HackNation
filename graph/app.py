"""Follow the Fake — lokalny demonstrator dla analityka (Streamlit)."""
from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import re
import sys

import pandas as pd
import plotly.express as px
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

PALETTE = ["#1F77B4", "#2CA02C", "#9467BD", "#FF7F0E", "#17BECF", "#8C564B",
           "#E377C2", "#BCBD22", "#393B79", "#637939", "#8C6D31", "#7B4173"]
NOISE_COLOR = "#B8B8B8"
NEW_COLOR = "#E8112D"
NOISE_LABEL = "bez kampanii"
BOOTSTRAP_TAGS = re.compile(
    r'<link\b[^>]*\bhref="https://cdn\.jsdelivr\.net/npm/bootstrap@[^\"]*"[^>]*>'
    r'|<script\b[^>]*\bsrc="https://cdn\.jsdelivr\.net/npm/bootstrap@[^\"]*"[^>]*>\s*</script>'
)

st.set_page_config(page_title="Follow the Fake — kampanie", layout="wide")


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


# ---------------------------------------------------------------- graf
def build_graph_html(cards, edges, camps, camp_of, colors, new_ids, show_similar, show_noise, height,
                     hidden: set[str] = frozenset()) -> str:
    net = Network(height=f"{height}px", width="100%", bgcolor="#FFFFFF", cdn_resources="in_line")
    net.barnes_hut(gravity=-6000, central_gravity=0.3, spring_length=110, spring_strength=0.03)
    present: set[str] = set()

    for c in camps:
        nid = f"camp:{c.id}"
        net.add_node(nid, label=f"{c.id}\n{len(c.members)} reklam", shape="diamond", size=34,
                     color=colors[c.id], font={"size": 18, "bold": True},
                     title=(f"{c.id}: {len(c.members)} reklam\n"
                            f"aktywne {c.alive} / martwe {c.dead}\nwizerunek: {', '.join(c.persons) or '—'}"))
        present.add(nid)

    for i, card in enumerate(cards):
        cid, is_new = camp_of[i], card.id in new_ids
        is_page = standalone_page(card.raw)
        if card.id in hidden or (cid is None and not show_noise and not (is_new or is_page)):
            continue
        color = "#008279" if is_page else colors.get(cid, NOISE_COLOR)
        net.add_node(card.id, label=("★ " if is_new else "") + card.id,
                     shape="star" if is_new else ("square" if is_page else "dot"), size=30 if is_new else 14,
                     color={"background": color, "border": NEW_COLOR if is_new else color},
                     borderWidth=4 if is_new else 1,
                     font={"color": NEW_COLOR if is_new else "#333333", "size": 16 if is_new else 12},
                     title=card_tooltip(card, "Zapis strony" if is_page else cid or NOISE_LABEL))
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
        net.add_edge(a, b, width=1 + 5 * e.score, dashes=not e.has_hard,
                     color=NEW_COLOR if touches_new else "#9A9A9A",
                     title=f"SIMILAR {a} – {b}: score {e.score:.2f}\n{reasons}")
    html = BOOTSTRAP_TAGS.sub("", net.generate_html())
    # pyvis switches to a custom HTML popup when any title contains "href".
    # Captured titles remain text in that template too, including literal markup.
    return html.replace("popup.innerHTML = nodeData[0].title;", "popup.innerText = nodeData[0].title;").replace(
        "<head>", "<head>\n<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; "
        "script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:\">", 1)


# ---------------------------------------------------------------- oś czasu
def render_timeline(cards, pages, camps, camp_of, colors, new_ids, show_noise, hidden):
    scope = st.selectbox("Kampania na osi czasu", ["Wszystkie kampanie", *(c.id for c in camps)])
    camp_by_id, seen = {}, []
    missing, missing_publication = [], []
    for i, card in enumerate(cards):
        cid = "Zapis strony" if standalone_page(card.raw) else camp_of[i] or NOISE_LABEL
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
            camp_by_id[label] = "Zapis strony"
            if item := event(label, "Obserwacja strony", value, source):
                seen.append(item)
            else:
                missing.append(label)
    dated = [{"materiał": row.record_id, "rodzaj": row.kind, "czas UTC": row.instant,
              "wartość źródłowa": row.value, "źródło": row.source, "kampania": camp_by_id[row.record_id]}
             for row in seen if row.instant is not None]
    if dated:
        frame = pd.DataFrame(dated).sort_values("czas UTC")
        fig = px.scatter(frame, x="czas UTC", y="materiał", color="kampania", symbol="rodzaj",
                         color_discrete_map={**colors, NOISE_LABEL: NOISE_COLOR, "Zapis strony": "#008279"},
                         hover_data={"czas UTC": False, "wartość źródłowa": True, "źródło": True})
        fig.update_traces(marker={"size": 10})
        fig.update_layout(height=max(320, 19 * len(camp_by_id) + 140), margin={"l": 10, "r": 10, "t": 30, "b": 10})
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("Brak zdarzeń z czasem i strefą do naniesienia na oś.")
    if seen:
        with st.expander("Zdarzenia i źródła dat", expanded=any(row.instant is None for row in seen)):
            st.dataframe(pd.DataFrame([{"materiał": row.record_id, "rodzaj": row.kind, "data": row.value,
                                       "precyzja": row.precision, "źródło": row.source}
                                      for row in seen]), width="stretch", hide_index=True)
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


# ---------------------------------------------------------------- UI
st.title("Follow the Fake — mapa kampanii")

with st.sidebar:
    st.header("Korpus")
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

st.subheader("Przechwyć stronę z linku")
st.caption("Wklej adres strony. Po pobraniu dane automatycznie trafią do analizy i na graf.")
with st.form("capture-url"):
    page_url = st.text_input("Adres strony (HTTP lub HTTPS)", placeholder="https://…")
    fetch_page = st.form_submit_button("Przechwyć stronę")
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

st.subheader("Porównaj nową reklamę")
st.caption(f"Porównanie z wybraną referencją: {source_mode}.")
with st.form("analyze-image"):
    uploaded_image = st.file_uploader("Zdjęcie reklamy (PNG, JPEG, WebP)",
                                     type=["png", "jpg", "jpeg", "webp"])
    description = st.text_area("Tekst reklamy", max_chars=10000)
    text_origin = st.toggle("Tekst pochodzi z oryginalnego opisu reklamy", help="Włącz, jeśli tekst pochodzi spoza zrzutu.")
    known_target = st.text_input("Znany adres celu reklamy", placeholder="https://…")
    submit_image = st.form_submit_button("Porównaj reklamę")
if submit_image:
    st.session_state.pop("image_analysis", None)
    card, image_error = None, None
    if uploaded_image is not None:
        try:
            with st.spinner("Odczyt zdjęcia i przygotowywanie porównania…"):
                card = image_query.analyze_image(uploaded_image.getvalue())["card"]
        except (ImportError, ValueError, OSError, RuntimeError) as exc:
            image_error = f"Nie udało się przeanalizować zdjęcia: {exc}"
    try:
        card = image_query.supplement_query(card, description, known_target, text_origin)
        if card is None:
            st.error(image_error or "Dodaj zdjęcie, tekst lub znany adres celu reklamy.")
        else:
            if image_error:
                card["extraction"]["warnings"].append(image_error)
            st.session_state["image_analysis"] = {"card": card}
    except (ImportError, ValueError, OSError, RuntimeError) as exc:
        st.error(str(exc))
if image_result := st.session_state.get("image_analysis"):
    image_card = image_result["card"]
    if image_path := image_card["provenance"].get("image_path"):
        st.image(image_path, caption="Przesłane zdjęcie", width=600)
        st.caption("OCR i obraz stanowią wspólne źródło dowodu. Adresy z OCR pozostają tekstem.")
    for warning in image_card.get("extraction", {}).get("warnings", []):
        st.warning(warning)
    with st.expander("Tekst i raport ekstrakcji"):
        st.text(image_card.get("text", {}).get("ad_text") or "Brak tekstu.")
        st.json(image_card.get("extraction", {}))
    if st.button("Wyczyść zgłoszenie", key="clear-image"):
        st.session_state.pop("image_analysis", None)
        st.rerun()

with st.sidebar:
    st.header("Parametry")
    min_cluster = st.slider("min. reklam w kampanii", 2, 10, 3)
    min_edge = st.slider("min. score krawędzi w grafie", 0.05, 0.9, 0.25, 0.05)
    st.header("Widok")
    show_similar = st.checkbox("pokaż krawędzie SIMILAR", True)
    show_noise = st.checkbox("pokaż reklamy bez kampanii", True)
    hide_trusted = st.checkbox("ukryj reklamy prowadzące na wspólne lub popularne hosty", False,
                               help="Domyślnie wyłączone: popularność nie świadczy o bezpieczeństwie. Po włączeniu "
                                    "nie rysujemy reklam bez kampanii, których cel to wspólny lub popularny host "
                                    "(np. youtube.com). Reklama powiązana z kampanią (np. tą samą twarzą lub głosem) zostaje.")
    graph_height = st.slider("wysokość grafu", 400, 1000, 650, 50)

image_result = st.session_state.get("image_analysis") or {}
by_id = {card["ad_id"]: card for card in corpus}

# --- dane pobranej strony trafiają bezpośrednio do silnika ---
result = st.session_state.get("url_capture") or {}
existing_page_ids = set()
if lookup := st.session_state.get("url_lookup"):
    from scamgraph.url_capture import existing_url_ids
    existing_page_ids = existing_url_ids(lookup, corpus)
if existing_page_ids:
    st.info("Ten URL już jest w bazie danych. Podświetlono istniejący materiał na grafie.")
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

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("materiały", len(cards))
m2.metric("kampanie", len(camps))
m3.metric("krawędzie SIMILAR", len(edges))
m4.metric("reklamy bez kampanii", sum(cid is None and not standalone_page(card.raw)
                                    for cid, card in zip(camp_of, reference.cards)))
m5.metric("ukryte (wspólne hosty)", len(hidden))
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

STATUS_LABELS = {"probable_match": "Prawdopodobne dopasowanie", "review_needed": "Do przeglądu",
                 "insufficient_evidence": "Niewystarczające dane", "no_match": "Możliwy nowy wzorzec"}
idx = {c.id: i for i, c in enumerate(cards)}
for nid in sorted(new_ids):
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
    elif corpus_path and st.button(f"Dopisz {nid} do prywatnego korpusu", key=f"save-{nid}"):
        saved = dict(next(c for c in new_raw if c["ad_id"] == nid))
        if saved.get("provenance", {}).get("record_kind") == "image_query":
            saved["provenance"] = {**saved["provenance"], "record_kind": "image_reference"}
        try:
            append_private_card(corpus_path, saved)
        except (OSError, ValueError) as exc:
            st.error(f"Nie zapisano materiału: {exc}")
            st.stop()
        st.toast(f"Dopisano {nid} do prywatnego korpusu.")
        if image_result.get("card") and saved.get("provenance", {}).get("source") == "upload":
            st.session_state.pop("image_analysis", None)
        if saved.get("provenance", {}).get("record_kind") == "page_capture":
            st.session_state.pop("url_capture", None)
        st.rerun()

# --- graf ---
st.subheader("Graf kampanii")
st.caption("◆ kampania · ● reklama (kolor = kampania, szary = bez kampanii) · ■ zapis strony · ★ zgłoszenie · "
           "linia ciągła = jest ślad twardy, przerywana = tylko miękkie · grubość = score · "
           "najedź na węzeł/krawędź, żeby zobaczyć szczegóły i uzasadnienie")
components.html(build_graph_html(cards, edges, camps, camp_of, colors, new_ids,
                                 show_similar, show_noise, graph_height, hidden),
                height=graph_height + 20, scrolling=False)
if edges:
    with st.expander("Dowody par · otwórz oba źródła"):
        by_pair = {f"{cards[edge.a].id} ↔ {cards[edge.b].id}": edge for edge in edges}
        pair = st.selectbox("Wybierz parę z grafu", list(by_pair), index=None, placeholder="Wybierz parę")
        if pair is not None:
            render_pair(by_pair[pair], cards)

render_pages(imported.pages, imported.report)

# --- oś czasu ---
st.subheader("Oś czasu kampanii")
render_timeline(cards, imported.pages, camps, camp_of, colors, new_ids, show_noise, hidden)

with st.expander("Kampanie — podsumowanie"):
    st.dataframe(pd.DataFrame([{
        "kampania": c.id, "reklamy": len(c.members),
        "aktywne": c.alive, "martwe": c.dead, "domeny docelowe": len(c.final_domains),
        "wizerunek": ", ".join(c.persons), "śr. score": round(c.mean_edge, 2),
        "wspólne ślady": ", ".join(f"{k} ×{v}" for k, v in c.shared[:4]),
    } for c in camps]), width="stretch", hide_index=True)
