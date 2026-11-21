"""Run with streamlit run scheduler_panel.py -- --store data/captures."""
import argparse
import json
import re
from pathlib import Path

import streamlit as st

from scamgraph.capture import DEFAULT_STORE
from scamgraph.catalog import artifact_path, catalog, matches, preview

LABELS = {"card": "Karta reklamy", "image": "Obraz reklamy", "recording": "Nagranie", "landing": "HTML strony",
          "assets": "Zasoby strony", "har": "Zapis HAR", "screenshot": "Zrzut reklamy",
          "landing_screenshot": "Zrzut strony docelowej", "full_page_screenshot": "Zrzut całej strony"}
SOURCES = {"landing_review": "Opinia na stronie docelowej", "platform_comment": "Komentarz z platformy",
           "creative_quote": "Cytat w kreacji"}


def label(value):
    # Widget labels accept Markdown; source text must never load a remote image.
    return re.sub(r"([\\\[\]()!*_\x60<>])", r"\\\1", str(value))


def proof(capture_id, ref, excerpt):
    st.session_state["proof"] = (capture_id, ref, excerpt)


def button(label, cid, row, excerpt, key):
    st.button(label, key=key, on_click=proof, args=(cid, row["evidence"], str(excerpt)))


def describe(records, cid):
    _, meta, result = records[cid]
    name = next((f["value"] for f in result["ad_fields"] if f["field"] == "page_name"), meta["provider"])
    return f"{name} · {meta.get('ad_ref') or cid}"


def selection(cid):
    st.query_params["znalezisko"] = cid
    st.session_state.pop("proof", None)


def field_value(row):
    value = row["value"]
    if isinstance(value, dict) and "amount" in value:
        value = f"{value['amount']} {value.get('currency') or ''}".strip()
    return " · ".join(str(v) for v in (row.get("product"), value) if v)


def readable_page(folder, meta, saved, index, cid):
    rows = saved.get("reading_text")
    if rows is None:
        rows = [{**r, "section": "content"} for r in saved.get("content", [])]
    st.subheader("Tekst strony")
    source = saved.get("reading_source", saved["evidence"])
    st.caption("Źródło tekstu · " + source["file"])
    if saved.get("reading_source"):
        st.caption("Tekst odzyskany z początkowej odpowiedzi HTML. W zapisie widoku dostępne były tylko elementy interfejsu lub pusty dokument.")
    text = "\n\n".join(row["value"] for row in rows if row["section"] == "content")
    if text:
        st.text_area("Treść dokumentu", text, height=280, disabled=True, key=f"text-{cid}-{index}")
    else:
        st.info("W zapisanym HTML nie znaleziono tekstu poza elementami interfejsu.")
    interface = "\n".join(r["value"] for r in rows if r["section"] == "interface")
    if interface:
        with st.expander("Nawigacja i komunikaty strony"):
            st.text(interface)
    item = next((f for f in meta.get("derived_files", []) if f["source"] == source), None)
    if item:
        st.download_button("Pobierz tekst strony (.txt)", artifact_path(folder, item).read_bytes(),
                           file_name=f"{cid}-{index+1}.txt", mime="text/plain; charset=utf-8", key=f"txt-{cid}-{index}")
    if rows:
        with st.expander("Źródła fragmentów tekstu"):
            i = st.selectbox("Fragment tekstu", range(len(rows)), format_func=lambda n: rows[n]["value"][:120],
                             key=f"txt-loc-{cid}-{index}")
            button("Otwórz źródło fragmentu", cid, rows[i], rows[i]["value"], f"txt-proof-{index}")


def detail(records, cid):
    folder, meta, result = records[cid]
    st.header(label(describe(records, cid)))
    st.caption(f"{meta['acquisition_method']} · {meta['collected_at']} · {cid}")
    st.write("Analiza częściowa" if result["partial"] else "Analiza pełna dla dostarczonych materiałów")
    if result.get("ad_page_links"):
        st.caption("Strona docelowa z odnośnika CTA na zapisanej karcie.")
    else:
        st.caption("Powiązanie emisji ze stroną pozostaje nieustalone.")
    if "proof" in st.session_state:
        other, ref, excerpt = st.session_state["proof"]
        with st.container(border=True):
            st.subheader("Lokalny dowód")
            st.text(f"{ref['file']} · {json.dumps(ref['locator'], ensure_ascii=False)}")
            try:
                kind, value = preview(*records[other][:2], ref, excerpt)
                if kind in {"video", "audio"}:
                    getattr(st, kind)(value.read_bytes(), start_time=ref["locator"]["start"])
                elif kind == "text":
                    st.text(str(value))
                else:
                    getattr(st, kind)(value)
            except (ValueError, OSError, KeyError, IndexError) as exc:
                st.error(f"Błąd odczytu dowodu ({type(exc).__name__})")
            st.button("Zamknij dowód", on_click=lambda: st.session_state.pop("proof", None))
    ad, page, opinions, net, signals, inventory = st.tabs(
        ["Kreacja", "Strona", "Opinie i odpowiedzi", "Ślady sieciowe", "Sygnały", "Materiały"])
    with ad:
        if result.get("source_record"):
            st.button("Otwórz oryginalny zapis źródła", key="upstream", on_click=proof,
                      args=(cid, result["source_record"], ""))
        for item in meta["artifacts"]:
            role = item["role"]
            if role in {"image", "video", "audio"}:
                try:
                    path = artifact_path(folder, item)
                    if item.get("media_kind") == "card_attachment":
                        st.text("Medium osadzone w karcie · " + item["path"])
                    if role == "image":
                        from PIL import Image
                        with Image.open(path) as image:
                            if image.width * image.height > 32_000_000:
                                raise ValueError("Obraz przekracza limit pikseli")
                            st.image(image.convert("RGB"))
                    else:
                        getattr(st, role)(path.read_bytes())
                except (OSError, ValueError):
                    st.warning("Nie udało się odczytać medium.")
        for group, rows in (("Pola karty i zrzutu", result["ad_fields"]), ("Tekst OCR", result["ocr"])):
            if rows:
                with st.expander(group, expanded=group.startswith("Pola")):
                    for index, row in enumerate(rows):
                        st.text(f"{row.get('field', 'OCR')} · {row['value']}")
                        button("Otwórz fragment", cid, row, row["value"], (group + str(index)))
        for i, recording in enumerate(result["asr"]):
            for j, row in enumerate(recording["segments"]):
                st.text(f"{row['start']:.1f}–{row['end']:.1f} s · {row['text']}")
                button("Otwórz nagranie", cid, row, row["text"], f"audio{i}-{j}")
    with page:
        visit = result.get("landing_visit", {})
        if visit.get("trusted_domain"):
            st.text("Pominięto pobranie · zaufana domena " + visit["trusted_domain"])
        elif visit.get("status"):
            st.text("Stan pobrania · " + visit["status"])
        if visit.get("page_id"):
            st.text("Paczka URL · pages/" + visit["page_id"])
        for index, saved in enumerate(result["pages"]):
            readable_page(folder, meta, saved, index, cid)
        if visit.get("cookie_action"):
            action = visit["cookie_action"]
            st.text(" · ".join(v for v in ("Okno cookies", action.get("settings"), action["status"], action.get("label")) if v))
        quality = result.get("landing_summary")
        if quality:
            st.write("Odczytano HTML strony" if quality["document"] else "Brak odczytanego dokumentu")
            if quality["document"]:
                st.text("Renderowanie · " + ("częściowe" if quality["issues"] else
                        "zapisany widok" if quality["screen"] else "brak potwierdzonego zrzutu"))
                offer = quality.get("offer")
                st.write("Wykryto treść oferty" if offer else "Brak rozpoznanej treści oferty")
                if offer:
                    button("Pokaż fragment oferty", cid, offer, offer["value"], "offer-evidence")
                if quality.get("dialog"):
                    st.write("Wykryto okno cookies w zapisanym HTML")
                    button("Pokaż treść okna", cid, quality["dialog"], quality["dialog"]["value"], "dialog-evidence")
                if (quality.get("screen") or {}).get("mostly_uniform"):
                    st.write("Jednolity środek zapisanego zrzutu")
                    button("Pokaż oceniony obszar", cid, quality["screen"], "", "screen-evidence")
        if visit.get("reason"):
            st.text(visit["reason"])
        for issue in visit.get("issues", []):
            st.text(issue)
        for i, link in enumerate(result.get("ad_page_links", [])):
            st.text(f"{visit.get('label', 'CTA')} → {link['final_url']}")
            button("Pokaż odnośnik na karcie", cid, link, "", f"cta-{i}")
            st.button("Pokaż odpowiedź serwera strony", key=f"cta-http-{i}", on_click=proof,
                      args=(cid, link["navigation_evidence"], ""))
        images = [a for a in meta["artifacts"] if a["path"].startswith("landing/") and
                  a["type"] in {"image/png", "image/jpeg", "image/webp", "image/gif", "image/avif"}]
        names = {"landing/screenshot_full.png": "Zrzut całej strony", "landing/full-page.png": "Zrzut całej strony", "landing/page-partial.png": "Zrzut części długiej strony",
                 "landing/screenshot.png": "Widoczny obszar strony"}
        if visit and not any(a["path"] in {"landing/screenshot_full.png", "landing/full-page.png"} for a in images):
            st.caption("Pełny zrzut strony jest niedostępny w tym pakiecie.")
        if images:
            images.sort(key=lambda a: list(names).index(a["path"]) if a["path"] in names else len(names))
            img = st.selectbox("Zrzut i obrazy strony", images, format_func=lambda a:
                               names.get(a["path"], a["path"]))
            try:
                from PIL import Image
                with Image.open(artifact_path(folder, img)) as view:
                    if view.width * view.height <= 32_000_000:
                        st.image(view.convert("RGB"))
                if img["path"] in names:
                    st.download_button("Pobierz zrzut PNG", artifact_path(folder, img).read_bytes(),
                                       file_name=Path(img["path"]).name, mime="image/png")
            except (OSError, ValueError):
                st.warning("Nie udało się wyświetlić lokalnego obrazu strony.")
        if not result["pages"]:
            st.write("Brak zapisanego HTML strony.")
        for i, saved in enumerate(result["pages"]):
            for field, heading in (("titles", "Tytuł"), ("headings", "Nagłówki"), ("products", "Rozpoznane produkty"),
                                 ("prices", "Ceny"), ("cart_balances", "Saldo koszyka"), ("amounts", "Kwoty w treści"), ("names", "Kandydaci na nazwy własne"),
                                 ("content", "Treść strony i oferty")):
                rows = saved.get(field, [])
                if rows:
                    with st.expander(f"{heading} ({len(rows)})"):
                        index = st.selectbox("Fragment", range(len(rows)), format_func=lambda n, data=rows: field_value(data[n])[:160],
                                             key=f"page{i}-{field}")
                        row = rows[index]
                        st.text(field_value(row))
                        button("Otwórz element HTML", cid, row, row["value"], f"open{i}-{field}")
                        if row.get("product_evidence"):
                            st.button("Pokaż nazwę produktu", key=f"product-{i}-{field}", on_click=proof,
                                      args=(cid, row["product_evidence"], row["product"]))
    with opinions:
        rows = result["opinions"]
        if result["opinion_source"] == "missing":
            st.info("Brak źródła opinii.")
        else:
            st.write(f"Wpisy główne · {sum(not r['is_reply'] for r in rows)}   |   Odpowiedzi · {sum(r['is_reply'] for r in rows)}")
            st.caption("Podpis, ocena i reakcje są wartościami widocznymi w źródle. Autentyczność autora i zakup pozostają nieustalone.")
        for i, row in enumerate(rows):
            entry_label = "Odpowiedź" if row["is_reply"] else "Wpis"
            with st.expander(f"{row['order']}. {entry_label} · {label(row['signature'] or 'brak podpisu')}"):
                st.caption(SOURCES[row["source_kind"]] + " · " + label(row["visible_time"] or "brak czasu"))
                st.text(row["text"])
                if row.get("product"):
                    st.text("Produkt · " + row["product"])
                st.text(f"Ocena · {row['rating'] if row['rating'] is not None else 'brak danych'}")
                if row.get("rating_evidence"):
                    st.button("Pokaż ikony oceny", key=f"rating-{i}", on_click=proof,
                              args=(cid, row["rating_evidence"], row["rating"]))
                st.text("Reakcje · " + (", ".join(f"{r['kind']} {r['display']}" for r in row["reactions"]) or "brak danych"))
                if row["is_reply"]:
                    parent = next((p for p in rows if p["id"] == row["parent_id"] and p["evidence"]["file"] == row["evidence"]["file"]), None)
                    st.text(f"Wpis nadrzędny · {parent['order'] if parent else 'nieustalony'}")
                button("Otwórz źródło wpisu", cid, row, row["text"], f"op{i}")
        badges = [b for p in result["pages"] for b in p.get("rating_badges", [])]
        if badges:
            with st.expander(f"Oceny zbiorcze podane przez stronę ({len(badges)})"):
                i = st.selectbox("Odznaka oceny", range(len(badges)),
                                 format_func=lambda i: field_value(badges[i]))
                st.text(field_value(badges[i]))
                button("Pokaż źródło oceny zbiorczej", cid, badges[i], badges[i]["value"], "badge-proof")
        st.subheader("Powtórzone opinie w innych obserwacjach")
        copies = list(matches(records, cid))
        if not copies:
            st.write("Brak dopasowań w zaimportowanych obserwacjach.")
        for i, (left, other, right, score) in enumerate(copies):
            with st.expander(f"{'Identyczny tekst po normalizacji' if score == 1 else 'Bliska kopia'} · {score:.0%} · {other}"):
                for j, (key, row) in enumerate(((cid, left), (other, right))):
                    st.text(describe(records, key) + " · " + row["evidence"]["file"])
                    st.text(row["text"])
                    button("Otwórz źródło", key, row, row["text"], f"copy{i}-{j}")
    with net:
        if not result["networks"]:
            st.write("Brak dostarczonego HAR.")
        pixel_groups = [result["pixels"]] + [p["pixels"] for p in result["pages"]]
        for i, har in enumerate(result["networks"]):
            pixel_groups.append(har["pixels"])
            rows = har["entries"]
            st.write(f"Wpisy HAR · {len(rows)}")
            if rows:
                index = st.selectbox("Żądanie", range(len(rows)), format_func=lambda n, data=rows: f"{n} · {data[n]['status']} · {data[n]['address']}", key=f"har{i}")
                st.json({k: v for k,v in rows[index].items() if k != "evidence"})
                button("Otwórz wpis HAR", cid, rows[index], "", f"net{i}")
            with st.expander("Powtarzające się zasoby"):
                st.json(har["repeated_resources"])
        for i, pixels in enumerate(pixel_groups):
            for j, row in enumerate(pixels):
                st.text(f"Piksel · {row['value']}")
                button("Otwórz dowód piksela", cid, row, row["value"], f"pixel{i}-{j}")
    with signals:
        if not result["signals"]:
            st.write("Brak rozpoznanych sygnałów.")
        groups = {}
        for row in result["signals"]:
            key = (row["kind"], row.get("context", "treść strony"), " ".join(row["excerpt"].casefold().split()))
            groups.setdefault(key, []).append(row)
        for i, ((kind, context, _), group) in enumerate(groups.items()):
            with st.expander(kind.replace("_", " ") + " · " + label(group[0]["excerpt"][:65])):
                st.caption(f"{context} · liczba wystąpień {len(group)}")
                occurrence = st.selectbox("Wystąpienie", range(1, len(group)+1), key=f"signal-choice-{i}") if len(group)>1 else 1
                row = group[occurrence-1]
                st.text(row["excerpt"])
                button("Otwórz lokalny dowód", cid, row, row["excerpt"], f"signal{i}")
    with inventory:
        for key, value in meta["availability"].items():
            st.write(f"{LABELS[key]} · " + ("dostępne" if value["available"] else value["reason"]))
        for issue in result["issues"]:
            st.warning(f"{issue['evidence']['file']} · {issue['reason']}")
        st.dataframe([*meta["artifacts"], *meta.get("derived_files", [])], hide_index=True)
        st.download_button("Eksportuj analizę JSON", json.dumps(result, ensure_ascii=False, indent=2),
                           file_name=f"{cid}-extracted.json", mime="application/json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--discovery", type=Path)
    args = parser.parse_args()
    st.set_page_config(page_title="ScamGraph · Znaleziska", layout="wide")
    if args.discovery:
        from scamgraph.discovery.dashboard import show
        show(args.discovery, detail, selection)
        return
    st.title("Znaleziska schedulera")
    try:
        errors = []
        records = catalog(args.store, errors)
    except (ValueError, OSError, KeyError) as exc:
        st.error(f"Błąd odczytu katalogu ({type(exc).__name__})")
        return
    for message in errors:
        st.warning("Pominięto nieczytelny pakiet " + label(message))
    if not records:
        st.info("Brak zaimportowanych obserwacji.")
        return
    selected = st.query_params.get("znalezisko")
    with st.sidebar:
        st.header("Obserwacje")
        for cid in records:
            st.button(label(describe(records, cid)), key=cid, on_click=selection, args=(cid,))
    if selected in records:
        detail(records, selected)
    else:
        st.write("Wybierz reklamę z listy obserwacji.")


if __name__ == "__main__":
    main()
