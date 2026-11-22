"""Follow the Fake — demonstrator (Streamlit).

    streamlit run app.py

1. Graf wszystkich kampanii: węzły to reklamy i kampanie, każda kampania w innym kolorze.
2. Pobranie strony przez URL: dane automatycznie trafiają do silnika i na graf.
   Zdjęcie: lokalne SHA-256/pHash i OCR porównywane z obrazami referencyjnymi.
3. Pod grafem oś czasu: kiedy każda kampania publikowała reklamy.

Korzysta wyłącznie z paczki ftf_graph (card, scoring, cluster, report) — bez jej modyfikacji.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components
from pyvis.network import Network

# Share the same trusted-domain cache with the URL adapter in both launch modes.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from graph.ftf_graph.card import SIGNAL_KINDS, parse_card
from graph.ftf_graph.cluster import cluster
from graph.ftf_graph.report import summarize
from graph.ftf_graph.presentation import card_tooltip
from graph.ftf_graph.scoring import Config, Scorer

PALETTE = ["#1F77B4", "#2CA02C", "#9467BD", "#FF7F0E", "#17BECF", "#8C564B",
           "#E377C2", "#BCBD22", "#393B79", "#637939", "#8C6D31", "#7B4173"]
NOISE_COLOR = "#B8B8B8"
NEW_COLOR = "#E8112D"
NOISE_LABEL = "bez kampanii"

st.set_page_config(page_title="Follow the Fake — kampanie", layout="wide")


# ---------------------------------------------------------------- dane
@st.cache_data
def read_jsonl(path: str, mtime: float) -> list[dict]:  # mtime: odśwież cache, gdy plik się zmieni
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


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


def analyze(raw: list[dict], min_cluster: int, min_samples: int, min_edge: float):
    cards = [parse_card(r) for r in raw]
    sc = Scorer(cards, Config(min_edge=min_edge))
    scores, edges = sc.score_all()
    res = cluster(scores, min_cluster, min_samples)
    camps, label_to_id = summarize(cards, scores, res, sc)
    camp_of = [label_to_id.get(int(lab)) if lab >= 0 else None for lab in res.labels]
    colors = {c.id: PALETTE[k % len(PALETTE)] for k, c in enumerate(camps)}
    return cards, scores, edges, res, camps, camp_of, colors


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
                     title=(f"{c.id}: {len(c.members)} reklam\n{c.first_seen[:10]} → {c.last_seen[:10]}\n"
                            f"aktywne {c.alive} / martwe {c.dead}\nwizerunek: {', '.join(c.persons) or '—'}"))
        present.add(nid)

    for i, card in enumerate(cards):
        cid, is_new = camp_of[i], card.id in new_ids
        if card.id in hidden or (cid is None and not show_noise and not is_new):
            continue
        color = colors.get(cid, NOISE_COLOR)
        net.add_node(card.id, label=("★ " if is_new else "") + card.id,
                     shape="star" if is_new else "dot", size=30 if is_new else 14,
                     color={"background": color, "border": NEW_COLOR if is_new else color},
                     borderWidth=4 if is_new else 1,
                     font={"color": NEW_COLOR if is_new else "#333333", "size": 16 if is_new else 12},
                     title=card_tooltip(card, cid or NOISE_LABEL))
        present.add(card.id)
        if cid:
            net.add_edge(card.id, f"camp:{cid}", color=color, width=1.5, title="IN_CAMPAIGN")

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
    html = net.generate_html()
    # pyvis switches to a custom HTML popup when any title contains "href".
    # Captured titles remain text in that template too, including literal markup.
    return html.replace("popup.innerHTML = nodeData[0].title;",
                        "popup.innerText = nodeData[0].title;")


# ---------------------------------------------------------------- oś czasu
def timeline_figure(cards, camps, camp_of, colors, new_ids, show_noise, hidden: set[str] = frozenset()):
    rows = []
    for i, card in enumerate(cards):
        cid = camp_of[i] or NOISE_LABEL
        if card.id in hidden or (cid == NOISE_LABEL and not show_noise and card.id not in new_ids):
            continue
        start = pd.to_datetime(card.first_seen, utc=True, errors="coerce")
        if pd.isna(start):
            continue
        end = pd.to_datetime(card.last_seen, utc=True, errors="coerce")
        if pd.isna(end) or end <= start:
            end = start + pd.Timedelta(hours=12)
        rows.append({"kampania": cid,
                     "reklama": f"{cid} · {card.id}" + (" ★" if card.id in new_ids else ""),
                     "start": start, "koniec": end, "status": card.status or "?",
                     "domena": card.final_domain, "tekst": card.ad_text})
    if not rows:
        return None
    df = pd.DataFrame(rows)
    camp_order = [c.id for c in camps] + [NOISE_LABEL]
    df["_k"] = df["kampania"].map({c: k for k, c in enumerate(camp_order)})
    df = df.sort_values(["_k", "start"])
    fig = px.timeline(df, x_start="start", x_end="koniec", y="reklama", color="kampania",
                      color_discrete_map={**colors, NOISE_LABEL: NOISE_COLOR},
                      category_orders={"reklama": df["reklama"].tolist(), "kampania": camp_order},
                      hover_data={"status": True, "domena": True, "tekst": True, "reklama": False})
    fig.update_yaxes(autorange="reversed", title=None)
    fig.update_xaxes(title="okres aktywności reklamy (first_seen → last_seen)")
    for label in df.loc[df["reklama"].str.endswith("★"), "reklama"]:
        fig.add_annotation(x=df.loc[df["reklama"] == label, "start"].iloc[0], y=label, text="NOWA",
                           showarrow=False, xanchor="right", font={"color": NEW_COLOR, "size": 12})
    fig.update_layout(height=max(320, 24 * len(df) + 120), legend_title_text="kampania",
                      margin={"l": 10, "r": 10, "t": 30, "b": 10})
    return fig


# ---------------------------------------------------------------- UI
st.title("Follow the Fake — mapa kampanii")

with st.sidebar:
    st.header("Korpus")
    corpus_path = st.text_input("Plik z kartami (JSONL)", str(Path(__file__).resolve().parent / "data/sample_cards.jsonl"))
corpus = (read_jsonl(corpus_path, Path(corpus_path).stat().st_mtime)
          if Path(corpus_path).is_file() else [])

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
        st.success(f"Domena {report['trusted_domain']} jest uznawana za bezpieczną "
                   "na podstawie listy zaufanych. Pominięto skanowanie.")
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

st.subheader("Sprawdź zdjęcie lub zrzut reklamy")
st.caption("Wgraj zdjęcie, aby znaleźć podobne reklamy w dostępnej bazie.")
with st.form("analyze-image"):
    uploaded_image = st.file_uploader("Zdjęcie reklamy (PNG, JPEG, WebP)",
                                     type=["png", "jpg", "jpeg", "webp"])
    submit_image = st.form_submit_button("Analizuj zdjęcie")
if submit_image:
    st.session_state.pop("image_analysis", None)
    if uploaded_image is None:
        st.error("Wybierz zdjęcie reklamy.")
    else:
        try:
            from scamgraph.image_query import analyze_image
            with st.spinner("Odczyt zdjęcia i przygotowywanie porównania…"):
                st.session_state["image_analysis"] = analyze_image(uploaded_image.getvalue())
        except ImportError:
            st.error("Brakuje zależności zdjęć. Zainstaluj graph/requirements-app.txt.")
        except (ValueError, OSError, RuntimeError) as exc:
            st.error(f"Nie udało się przeanalizować zdjęcia: {exc}")
if image_result := st.session_state.get("image_analysis"):
    image_card = image_result["card"]
    st.image(image_card["provenance"]["image_path"], caption="Przesłane zdjęcie", width=600)
    st.success("Zdjęcie zostało wczytane do analizy i na graf.")
    st.caption("Podobieństwo kreacji i identyczność pliku są wskazówkami do przeglądu. "
               "Nie potwierdzają oszustwa ani wspólnej kampanii. "
               "OCR i obraz stanowią wspólne źródło dowodu; adresy z OCR nie są odwiedzane.")
    for warning in image_card.get("extraction", {}).get("warnings", []):
        st.warning(warning)
    with st.expander("Tekst OCR i raport analizy zdjęć"):
        st.text(image_card.get("text", {}).get("ad_text") or "Brak odczytanego tekstu.")
        st.json(image_result.get("report", {}))
        st.json(image_card.get("extraction", {}))
        reference_warnings = {c["ad_id"]: c.get("extraction", {}).get("warnings", [])
                              for c in image_result.get("references", [])
                              if c.get("extraction", {}).get("warnings")}
        if reference_warnings:
            st.json(reference_warnings)
    if st.button("Usuń zapytanie ze zdjęcia", key="clear-image"):
        st.session_state.pop("image_analysis", None)
        st.rerun()

with st.sidebar:
    st.header("Parametry")
    min_cluster = st.slider("min. reklam w kampanii", 2, 10, 3)
    min_samples = st.slider("HDBSCAN min_samples", 1, 10, 2)
    min_edge = st.slider("min. score krawędzi w grafie", 0.05, 0.9, 0.25, 0.05)
    st.header("Widok")
    show_similar = st.checkbox("pokaż krawędzie SIMILAR", True)
    show_noise = st.checkbox("pokaż reklamy bez kampanii (szum HDBSCAN)", True,
                             help="Reklamy, których nie dało się przypisać do żadnej kampanii. To NIE znaczy, "
                                  "że są bezpieczne — mogą być pojedynczym oszustwem albo mieć za mało danych.")
    hide_trusted = st.checkbox("ukryj reklamy prowadzące na zaufane strony", True,
                               help="Reklama, której strona docelowa jest na liście zaufanych (np. youtube.com) "
                                    "i która NIE należy do żadnej kampanii, nie jest rysowana. Reklama na zaufanej "
                                    "stronie, ale powiązana z kampanią (np. tą samą twarzą lub głosem), zostaje.")
    graph_height = st.slider("wysokość grafu", 400, 1000, 650, 50)

if not Path(corpus_path).exists():
    st.error(f"Nie ma pliku {corpus_path}. Uruchom najpierw: python tools/gen_sample_cards.py")
    st.stop()

# Reference IDs include the dataset namespace; never join unrelated records by
# an accidental ID collision with the graph corpus.
image_result = st.session_state.get("image_analysis") or {}
by_id = {c["ad_id"]: dict(c) for c in corpus}
for reference in image_result.get("references", []):
    if reference["ad_id"] not in by_id:
        by_id[reference["ad_id"]] = reference
    else:
        original = by_id[reference["ad_id"]]
        if original != reference:
            st.error(f"Konflikt ID referencji {reference['ad_id']}. Wybierz osobny korpus kart.")
            st.stop()
corpus = list(by_id.values())

# --- dane pobranej strony trafiają bezpośrednio do silnika ---
result = st.session_state.get("url_capture") or {}
existing_page_ids = set()
if lookup := st.session_state.get("url_lookup"):
    from scamgraph.url_capture import existing_url_ids
    existing_page_ids = existing_url_ids(lookup, corpus)
if existing_page_ids:
    st.info("Ten URL już jest w bazie danych. Podświetlono istniejący materiał na grafie.")
new_raw = [result["card"]] if result.get("card") and not existing_page_ids else []
existing_image_id = None
if image_result.get("card"):
    candidate = image_result["card"]
    existing = by_id.get(candidate["ad_id"], {})
    if (existing.get("visual", {}).get("sha256") == candidate["visual"]["sha256"]
            and existing.get("provenance", {}).get("source") == "upload"):
        existing_image_id = candidate["ad_id"]
    else:
        new_raw.append(candidate)

new_raw = with_unique_ids(new_raw, {c.get("ad_id", "") for c in corpus})
new_ids = {c["ad_id"] for c in new_raw}
new_ids.update(existing_page_ids)
if existing_image_id:
    new_ids.add(existing_image_id)

try:
    cards, scores, edges, res, camps, camp_of, colors = analyze(corpus + new_raw, min_cluster, min_samples, min_edge)
except (ValueError, OSError, RuntimeError) as exc:
    st.error(f"Błąd analizy: {exc}")
    st.stop()

lands_trusted = {c.id for c in cards if c.final_domain and c.final_domain in c.trusted_hits}
hidden = ({c.id for i, c in enumerate(cards) if c.id in lands_trusted and camp_of[i] is None and c.id not in new_ids}
          if hide_trusted else set())

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("materiały", len(cards))
m2.metric("kampanie", len(camps))
m3.metric("krawędzie SIMILAR", len(edges))
m4.metric("bez kampanii", int(sum(c is None for c in camp_of)))
m5.metric("ukryte (zaufane strony)", len(hidden))

# --- gdzie trafiła nowa reklama ---
idx = {c.id: i for i, c in enumerate(cards)}
for nid in sorted(new_ids):
    i = idx[nid]
    cid = camp_of[i]
    mine = sorted((e for e in edges if i in (e.a, e.b)), key=lambda e: -e.score)
    if cid:
        size = next(len(c.members) for c in camps if c.id == cid)
        st.success(f"**{nid}** → **{cid}** ({size} materiałów w kampanii, "
                   f"rdzeniowość w kampanii wg HDBSCAN {res.strength[i]:.2f})")
    else:
        near = max(((c.id, float(scores[i, c.members].mean())) for c in camps), key=lambda t: t[1], default=None)
        hint = f" Najbliżej jej do {near[0]} (śr. podobieństwo {near[1]:.2f})." if near and near[1] > 0.05 else ""
        st.warning(f"**{nid}** nie pasuje do żadnej kampanii.{hint}")
    if cards[i].raw.get("provenance", {}).get("record_kind") == "page_capture":
        with st.expander(f"Pełny tekst strony — {cards[i].final_domain or nid}"):
            st.text_area("Tekst z pobranej strony", value=cards[i].ad_text,
                         height=320, disabled=True, key=f"page-text-{nid}")
    n_sig = len(cards[i].signals())
    if n_sig <= 3:
        st.info(f"Karta {nid} ma tylko {n_sig} z {SIGNAL_KINDS} rodzajów sygnałów "
                f"({', '.join(cards[i].signals()) or 'żadnego'}). Brak powiązań może wynikać z braku danych, "
                f"a nie z unikalności materiału.")
    if nid in lands_trusted:
        st.info(f"Strona docelowa {nid} ({cards[i].final_domain}) jest na liście zaufanych. "
                + ("Reklama jest jednak powiązana z kampanią, więc zostaje na grafie." if cid else
                   "Nowy materiał jest pokazany, aby umożliwić ocenę wyniku analizy."))
    if cards[i].trusted_hits:
        st.caption(f"Pominięte zaufane domeny (nie są śladem): {', '.join(cards[i].trusted_hits)}")
    with st.expander(f"Dlaczego? Najsilniejsze powiązania {nid}", expanded=bool(cid)):
        if not mine:
            st.write("Brak krawędzi powyżej progu.")
        for e in mine[:5]:
            other = cards[e.b if e.a == i else e.a]
            st.markdown(f"**{other.id}** ({camp_of[idx[other.id]] or NOISE_LABEL}) — score **{e.score:.2f}**")
            st.markdown("\n".join(f"- {'🟥 twardy' if r.hard else '🟦 miękki'} +{r.strength:.2f} — {r.detail}"
                                  for r in e.reasons))
            # Only adapter-owned, validated private files are offered as evidence.
            paths = [c.raw.get("provenance", {}).get("image_path") for c in (cards[i], other)]
            if all(paths) and all(Path(p).is_file() for p in paths):
                left, right = st.columns(2)
                left.image(paths[0], caption=nid, width=320)
                right.image(paths[1], caption=other.id, width=320)
    if image_result.get("card") and nid in new_ids and cards[i].image_sha256:
        comparable = sum(bool(c.image_sha256 or c.phash is not None or c.image_text)
                         for c in cards if c.id not in new_ids)
        st.caption(f"Materiały referencyjne z cechami do porównania zdjęcia: {comparable}.")
        if not comparable:
            st.warning("W bazie brakuje materiałów do porównania tego zdjęcia.")
    if nid in existing_page_ids:
        st.caption("Ten URL już jest w bazie danych.")
    elif nid == existing_image_id:
        st.caption("To zdjęcie jest już zapisane w korpusie; ponowny import nie dodaje kopii.")
    elif st.button(f"Dopisz {nid} do korpusu ({corpus_path})", key=f"save-{nid}"):
        saved = dict(next(c for c in new_raw if c["ad_id"] == nid))
        if saved.get("provenance", {}).get("record_kind") == "image_query":
            saved["provenance"] = {**saved["provenance"], "record_kind": "image_reference"}
        with open(corpus_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(saved, ensure_ascii=False) + "\n")
        st.toast(f"Dopisano {nid}. Martwych reklam nie usuwamy — korpus tylko rośnie.")
        if image_result.get("card") and cards[i].image_sha256:
            st.session_state.pop("image_analysis", None)
        if saved.get("provenance", {}).get("record_kind") == "page_capture":
            st.session_state.pop("url_capture", None)
        st.rerun()

# --- graf ---
st.subheader("Graf kampanii")
st.caption("◆ kampania · ● reklama (kolor = kampania, szary = bez kampanii) · ★ nowy materiał · "
           "linia ciągła = jest ślad twardy, przerywana = tylko miękkie · grubość = score · "
           "najedź na węzeł/krawędź, żeby zobaczyć szczegóły i uzasadnienie")
components.html(build_graph_html(cards, edges, camps, camp_of, colors, new_ids,
                                 show_similar, show_noise, graph_height, hidden),
                height=graph_height + 20, scrolling=False)

# --- oś czasu ---
st.subheader("Oś czasu kampanii")
fig = timeline_figure(cards, camps, camp_of, colors, new_ids, show_noise, hidden)
if fig is None:
    st.info("Brak dat first_seen w kartach.")
else:
    st.plotly_chart(fig, width="stretch")

with st.expander("Kampanie — podsumowanie"):
    st.dataframe(pd.DataFrame([{
        "kampania": c.id, "reklamy": len(c.members), "od": c.first_seen[:10], "do": c.last_seen[:10],
        "aktywne": c.alive, "martwe": c.dead, "domeny docelowe": len(c.final_domains),
        "wizerunek": ", ".join(c.persons), "śr. score": round(c.mean_edge, 2),
        "wspólne ślady": ", ".join(f"{k} ×{v}" for k, v in c.shared[:4]),
    } for c in camps]), width="stretch", hide_index=True)
