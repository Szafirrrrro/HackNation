"""Compact graph labels; source text and scoring inputs stay intact."""
from textwrap import fill

from .card import SIGNAL_KINDS


def compact(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def page_preview(raw: dict) -> tuple[str, str]:
    pages = raw.get("extensions", {}).get("page_observation", {}).get("pages", [])
    titles = [row["value"] for page in pages for row in page.get("titles", []) if row.get("value")]
    content = [row["value"] for page in pages for row in page.get("reading_text", [])
               if row.get("section") == "content" and row.get("value")]
    headings = [row["value"] for page in pages for row in page.get("headings", []) if row.get("value")]
    # Older captures without reading_text use headings; never promote the menu dump.
    return (titles[0] if titles else "", " ".join(dict.fromkeys(content or headings)))


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
