"""Follow the Fake — demonstrator (Streamlit).

    streamlit run app.py

1. Graf wszystkich kampanii: węzły to reklamy i kampanie, każda kampania w innym kolorze.
2. Wgranie nowej reklamy (.json z kartą): silnik przelicza krawędzie i klastry, pokazuje,
   gdzie trafiła nowa reklama i dlaczego, i rysuje graf od nowa.
3. Pod grafem oś czasu: kiedy każda kampania publikowała reklamy.

Korzysta wyłącznie z paczki ftf_graph (card, scoring, cluster, report) — bez jej modyfikacji.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components
from pyvis.network import Network

from ftf_graph.card import SIGNAL_KINDS, parse_card
from ftf_graph.cluster import cluster
from ftf_graph.report import summarize
from ftf_graph.scoring import Config, Scorer

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


def parse_json_text(text: str) -> list[dict]:
    """Przyjmuje pojedynczą kartę, listę kart albo JSONL."""
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        obj = [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(obj, dict):
        obj = [obj]
    if not isinstance(obj, list) or not all(isinstance(x, dict) for x in obj):
        raise ValueError("plik musi zawierać kartę reklamy (obiekt JSON) albo listę kart")
    return obj


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
    res = cluster(scores, min_cluster, min_samples, min_link=min_edge)
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
                     title=(f"{card.id} — {cid or NOISE_LABEL}\n{card.ad_text}\ndomena: {card.final_domain}\n"
                            f"status: {card.status or '?'}   od {card.first_seen[:10] or '?'}"
                            + (f"\nlektor: {card.audio_transcript[:120]}" if card.audio_transcript else "")
                            + f"\nsygnały: {len(card.signals())}/{SIGNAL_KINDS} ({', '.join(card.signals()) or 'brak'})"
                            + (f"\npominięte zaufane domeny: {', '.join(card.trusted_hits)}" if card.trusted_hits else "")))
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
    return net.generate_html()


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
    corpus_path = st.text_input("Plik z kartami (JSONL)", "data/sample_cards.jsonl")
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
corpus = read_jsonl(corpus_path, Path(corpus_path).stat().st_mtime)

# --- nowa reklama ---
st.subheader("Nowa reklama")
col_up, col_ex = st.columns([3, 2])
uploaded = col_up.file_uploader("Wgraj kartę reklamy (.json albo .jsonl)", type=["json", "jsonl"])
examples = sorted(str(p) for p in Path("data").glob("new_ad_*.json"))
example = col_ex.selectbox("…albo wybierz przykład", ["—"] + examples)

new_raw: list[dict] = []
try:
    if uploaded is not None:
        new_raw = parse_json_text(uploaded.getvalue().decode("utf-8"))
    elif example != "—":
        new_raw = parse_json_text(Path(example).read_text(encoding="utf-8"))
except (ValueError, UnicodeDecodeError) as exc:
    st.error(f"Nie mogę wczytać karty: {exc}")
    st.stop()

new_raw = with_unique_ids(new_raw, {c.get("ad_id", "") for c in corpus})
new_ids = {c["ad_id"] for c in new_raw}

try:
    cards, scores, edges, res, camps, camp_of, colors = analyze(corpus + new_raw, min_cluster, min_samples, min_edge)
except ValueError as exc:  # np. embeddingi o innym wymiarze niż w korpusie
    st.error(f"Błąd analizy: {exc}")
    st.stop()

lands_trusted = {c.id for c in cards if c.final_domain and c.final_domain in c.trusted_hits}
hidden = ({c.id for i, c in enumerate(cards) if c.id in lands_trusted and camp_of[i] is None and c.id not in new_ids}
          if hide_trusted else set())

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("reklamy", len(cards))
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
        st.success(f"**{nid}** → **{cid}** ({size} reklam w kampanii, "
                   f"rdzeniowość w kampanii wg HDBSCAN {res.strength[i]:.2f})")
    else:
        near = max(((c.id, float(scores[i, c.members].mean())) for c in camps), key=lambda t: t[1], default=None)
        hint = f" Najbliżej jej do {near[0]} (śr. podobieństwo {near[1]:.2f})." if near and near[1] > 0.05 else ""
        st.warning(f"**{nid}** nie pasuje do żadnej kampanii.{hint}")
    n_sig = len(cards[i].signals())
    if n_sig <= 3:
        st.info(f"Karta {nid} ma tylko {n_sig} z {SIGNAL_KINDS} rodzajów sygnałów "
                f"({', '.join(cards[i].signals()) or 'żadnego'}). Brak powiązań może wynikać z braku danych, "
                f"a nie z tego, że reklama jest unikalna.")
    if nid in lands_trusted:
        st.info(f"Strona docelowa {nid} ({cards[i].final_domain}) jest na liście zaufanych. "
                + ("Reklama jest jednak powiązana z kampanią, więc zostaje na grafie." if cid else
                   "Nowa reklama i tak jest pokazana, żebyś widziała wynik analizy."))
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
    if st.button(f"Dopisz {nid} do korpusu ({corpus_path})", key=f"save-{nid}"):
        with open(corpus_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(next(c for c in new_raw if c["ad_id"] == nid), ensure_ascii=False) + "\n")
        st.toast(f"Dopisano {nid}. Martwych reklam nie usuwamy — korpus tylko rośnie.")
        st.rerun()

# --- graf ---
st.subheader("Graf kampanii")
st.caption("◆ kampania · ● reklama (kolor = kampania, szary = bez kampanii) · ★ nowa reklama · "
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
