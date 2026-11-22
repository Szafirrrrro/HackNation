"""Compact graph labels; source text and scoring inputs stay intact."""
from textwrap import fill

from .card import SIGNAL_KINDS


def compact(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    prefix = text[:limit - 1]
    boundary = prefix.rfind(" ")
    return (prefix[:boundary] if boundary >= limit * 0.7 else prefix).rstrip() + "…"


def page_preview(raw: dict) -> tuple[str, str]:
    pages = raw.get("extensions", {}).get("page_observation", {}).get("pages", [])
    titles = [row["value"] for page in pages for row in page.get("titles", []) if row.get("value")]
    content = [row["value"] for page in pages for row in page.get("reading_text", [])
               if row.get("section") == "content" and row.get("value")]
    headings = [row["value"] for page in pages for row in page.get("headings", []) if row.get("value")]
    # Older captures without reading_text use headings; never promote the menu dump.
    return (titles[0] if titles else "", " ".join(dict.fromkeys(content or headings)))


def short_ref(record_id: str) -> str:
    ref = record_id.rsplit("/", 1)[-1] or record_id
    return f"…{ref[-8:]}" if len(ref) > 12 else ref


def graph_title(card) -> str:
    """Prefer text already available to the analyst, without opening an archive."""
    provenance = card.raw.get("provenance", {})
    kind = provenance.get("record_kind")
    if kind == "page_capture":
        title, content = page_preview(card.raw)
        options = (title, card.final_domain, content)
        fallback = "Zapis strony"
    else:
        options = (card.ad_text, card.raw.get("page_name"), provenance.get("page_name"),
                   card.final_domain, card.audio_transcript)
        fallback = "Zgłoszenie" if kind == "image_query" else "Reklama"
    for value in options:
        if isinstance(value, str) and value.strip():
            return compact(value, 80)
    return f"{fallback} · {short_ref(card.id)}"


def pair_labels(cards, pairs) -> dict[str, str]:
    choices = [f"{compact(graph_title(card), 32)} [{short_ref(card.id)}]" for card in cards]
    labels = {pair: f"{choices[edge.a]} ↔ {choices[edge.b]}" for pair, edge in pairs.items()}
    # Streamlit uses the formatted labels to resolve a selection.
    if len(set(labels.values())) != len(labels):
        labels = {pair: f"{index} · {label}" for index, (pair, label) in enumerate(labels.items(), 1)}
    return labels


def card_tooltip(card, campaign: str) -> str:
    title, content = page_preview(card.raw)
    is_page = card.raw.get("provenance", {}).get("record_kind") == "page_capture"
    lines = [compact(f"{card.id} — {campaign}", 100)]
    if is_page:
        lines.extend([compact(title or card.final_domain or "Obserwacja strony", 100),
                      f"domena: {compact(card.final_domain or '—', 100)}"])
        if content:
            lines.append(compact(content, 180))
        lines.append(f"pozyskano: {compact(card.fetched_at or 'nieustalone', 40)}")
    else:
        lines.extend([compact(card.ad_text, 180), f"domena: {compact(card.final_domain or '—', 100)}",
                      f"status: {compact(card.status or '?', 24)}   od {card.first_seen[:10] or '?'}"])
    if card.audio_transcript:
        lines.append("lektor: " + compact(card.audio_transcript, 100))
    signals = card.signals()
    lines.append(f"sygnały: {len(signals)}/{SIGNAL_KINDS} ({', '.join(signals) or 'brak'})")
    if card.trusted_hits:
        lines.append("wspólne hosty, nie są śladem: " + compact(", ".join(card.trusted_hits), 100))
    # Bundled vis-network displays string titles via innerText, so keep plain text.
    return "\n".join(fill(line, width=64, break_long_words=True, break_on_hyphens=False)
                     for line in lines if line)
