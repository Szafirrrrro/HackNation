"""Read-only phrase search in organizer material. The corpus has no delivery-country field."""
import hashlib
import json
import unicodedata
from pathlib import Path

from .types import Finding, Query, SourceError
from ..sources import clean


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def fetch(options: dict, query: Query):
    root = Path(options["path"]).resolve()
    path = root / "ads.jsonl"
    if not path.is_file():
        raise SourceError("Brak ads.jsonl w skonfigurowanym korpusie NASK.")
    if path.stat().st_size > 64 * 1024**2:
        raise SourceError("ads.jsonl przekracza 64 MiB.")
    data = path.read_bytes()
    receipt = hashlib.sha256(data).hexdigest()
    needle = normalized(query.phrase)
    count = 0
    for number, line in enumerate(data.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            ident = row["ad_id"]
            if not isinstance(ident, str) or not ident or not isinstance(row.get("source"), dict):
                raise ValueError()
            body = row.get("text") or ""
            if not isinstance(body, str):
                raise ValueError()
        except (TypeError, KeyError, ValueError) as exc:
            raise SourceError(f"Niepoprawna emisja w ads.jsonl, wiersz {number}.") from exc
        if needle not in normalized(body):
            continue
        source = row["source"]
        card = {"id": ident, "text": clean(body)}
        if source.get("ad_ref"):
            card["library_ref"] = str(source["ad_ref"])
        image = None
        if row.get("image_path"):
            candidate = (root / row["image_path"]).resolve()
            if not candidate.is_relative_to(root):
                raise SourceError(f"Ścieżka obrazu poza korpusem, wiersz {number}.")
            if candidate.is_file():
                image = candidate
        yield Finding(ident, card, f"Fraza „{query.phrase}” w transkrypcji z korpusu NASK",
                      not image or not source.get("ad_ref"), path, f"line:{number}", image=image,
                      observed_at=source.get("collected_at"),
                      source_kind="synthetic" if source.get("kind") == "synthetic" else "organizer", source_sha256=receipt)
        count += 1
        if count >= query.limit:
            break
