"""Read-only phrase search in organizer material. The corpus has no delivery-country field."""
import hashlib
from io import BytesIO
import logging
import unicodedata
from pathlib import Path

from models.common.import_rows import deduplicate_rows, parse_jsonl

from .types import Finding, Query, SourceError
from ..sources import clean

LOGGER = logging.getLogger(__name__)


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def searchable_rows(data, path):
    errors, rows = [], []
    for line, row in parse_jsonl(BytesIO(data), str(path), errors):
        if not isinstance(row.get("source"), dict) or not isinstance(row.get("text") or "", str):
            errors.append({"line": line, "error": "invalid_source_or_text"})
        else:
            rows.append((line, row))
    accepted, _ = deduplicate_rows(rows, path.parent.name, str(path), errors)
    for issue in errors:
        first_line = f", pierwszy zapis w wierszu {issue['first_line']}" if "first_line" in issue else ""
        code = issue["error"].split(":", 1)[0]
        LOGGER.warning("Pominięto ads.jsonl, wiersz %s (%s%s).", issue["line"], code, first_line)
    return accepted


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
    for number, row in searchable_rows(data, path):
        ident = row["ad_id"]
        body = row.get("text") or ""
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
