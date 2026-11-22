"""Point-in-time observations with original date values and source fields."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone


@dataclass(frozen=True)
class Event:
    record_id: str
    kind: str
    value: str
    source: str
    precision: str
    instant: datetime | None


def event(record_id: str, kind: str, value, source: str) -> Event | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        if len(value) == 10:
            date.fromisoformat(value)
            return Event(record_id, kind, value, source, "dzień", None)
        instant = datetime.fromisoformat(value)
        if instant.utcoffset() is None:
            return Event(record_id, kind, value, source, "czas bez strefy", None)
        return Event(record_id, kind, value, source, "czas ze strefą", instant.astimezone(timezone.utc))
    except OverflowError:
        return Event(record_id, kind, value, source, "poza zakresem UTC", None)
    except ValueError:
        return Event(record_id, kind, value, source, "nieczytelna data", None)


def card_events(card) -> list[Event]:
    raw = card.raw
    provenance = raw.get("provenance", {})
    source = provenance.get("source_ref") or provenance.get("snapshot") or card.id

    def item(kind, value, field):
        return event(card.id, kind, value, f"{source}#{field}")

    published = raw.get("published_at") or provenance.get("published_at")
    publication_field = "published_at" if raw.get("published_at") else "provenance.published_at"
    collection_field = "provenance.collected_at"
    if provenance.get("original_ad_id"):
        publication_field = provenance.get("published_at_field") or "source.published_at"
        collection_field = "source.collected_at"
    collected = provenance.get("collected_at")
    acquired_kind = "Obserwacja strony" if provenance.get("record_kind") == "page_capture" else "Pozyskanie"
    fetched_kind = acquired_kind
    if "observation_seq" in provenance:
        fetched_kind = "Obserwacja w schedulerze"
        first_kind, last_kind = "Pierwsze wykrycie", "Ostatnie wykrycie"
    else:
        first_kind, last_kind = "Pierwsza obserwacja", "Ostatnia obserwacja"
    if provenance.get("record_kind") in {"image_query", "image_reference"} and not collected:
        # Older analyst cards used fetched_at for extraction and lacked collection time.
        fetched_kind = "Ekstrakcja"
    events = [item("Publikacja", published, publication_field),
              item(acquired_kind, collected, collection_field),
              item(fetched_kind, card.fetched_at, "provenance.fetched_at"),
              item("Ekstrakcja", provenance.get("extracted_at"), "provenance.extracted_at"),
              item(first_kind, card.first_seen, "first_seen")]
    if card.last_seen and card.last_seen != card.first_seen:
        events.append(item(last_kind, card.last_seen, "last_seen"))
    observations = provenance.get("page_observations")
    for observation in observations if isinstance(observations, list) else []:
        if isinstance(observation, dict):
            events.append(event(card.id, "Obserwacja powiązanej strony", observation.get("at"),
                                observation.get("source_ref") or card.id))
    return [value for value in events if value]
