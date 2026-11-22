"""Local corpus loading for the analyst. Page captures retain their own identity."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from models.common.corpus import load_corpus
from models.common.import_rows import deduplicate_rows, read_jsonl


def _mapping(value) -> dict:
    return value if isinstance(value, dict) else {}


def _strings(value) -> list[str]:
    return [item for item in value if isinstance(item, str) and item.strip()] if isinstance(value, list) else []


@dataclass
class PageCapture:
    id: str
    record: dict
    locator: str

    @property
    def document(self) -> dict:
        return _mapping(self.record.get("document"))

    @property
    def html(self) -> dict:
        return _mapping(self.record.get("html"))

    @property
    def har(self) -> dict:
        return _mapping(self.record.get("har"))

    @property
    def url(self) -> str:
        return self.document.get("url_without_query") or ""

    @property
    def captured_at(self) -> tuple[str, str]:
        for value, key in ((self.har.get("document_started_at"), "har.document_started_at"),
                           (_mapping(self.record.get("archive_info")).get("captured_at"), "archive_info.captured_at"),
                           (self.record.get("captured_at"), "captured_at")):
            if isinstance(value, str) and value.strip():
                return value, f"{self.locator}#{key}"
        return "", self.locator

    @property
    def pixels(self) -> set[str]:
        return set(_strings(self.har.get("meta_pixel_ids")))


@dataclass
class AnalystCorpus:
    dataset_id: str
    cards: list[dict] = field(default_factory=list)
    pages: list[PageCapture] = field(default_factory=list)
    report: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CorpusSource:
    path: Path
    kind: str
    root: Path | None = None
    ads_path: Path | None = None

    @property
    def storage_path(self) -> Path:
        if self.root is not None and self.ads_path in (None, self.root / "ads.jsonl"):
            return self.root
        return self.path


def _file_stamp(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _row_kind(row: dict) -> str | None:
    ad_id = row.get("ad_id")
    if isinstance(ad_id, str) and ad_id.strip():
        if (any(key in row for key in ("provenance", "infra", "page", "visual", "first_seen", "extraction"))
                or isinstance(row.get("text"), dict)):
            return "cards"
        if (any(key in row for key in ("image_path", "audio_path", "video_path", "landing_url"))
                or isinstance(row.get("text"), str) or isinstance(row.get("source"), dict)):
            return "v0"
        if "audio" in row or "faces" in row:
            return "cards"
    elif isinstance(row.get("capture_id"), str) and row["capture_id"].strip():
        return "pages"
    return None


@lru_cache(maxsize=32)
def _file_kind(path: Path, stamp: tuple, manifest_stamp: tuple | None) -> str:
    kinds = Counter(kind for _, row in read_jsonl(path, []) if (kind := _row_kind(row)))
    v0_manifest = False
    if manifest_stamp is not None and path.name == "ads.jsonl":
        try:
            manifest = json.loads(path.with_name("manifest.json").read_text(encoding="utf-8-sig"))
            v0_manifest = _mapping(manifest).get("schema_version") == "v0"
        except (OSError, ValueError, RecursionError):
            pass
    # Ignore broken and untyped rows for format selection. A compatible manifest
    # breaks a tie for its own ads file, while consistently typed files win.
    return max(("cards", "v0", "pages"), key=lambda kind: (kinds[kind], kind == "v0" and v0_manifest))


def identify_corpus(path: Path) -> CorpusSource:
    path = path.resolve()
    if path.is_dir():
        return CorpusSource(path, "directory", path)
    stamp = _file_stamp(path)
    if path.name == "manifest.json":
        return CorpusSource(path, "directory", path.parent)
    try:
        manifest_stamp = _file_stamp(path.with_name("manifest.json")) if path.name == "ads.jsonl" else None
    except FileNotFoundError:
        manifest_stamp = None
    kind = _file_kind(path, stamp, manifest_stamp)
    return CorpusSource(path, kind, path.parent, path) if kind == "v0" else CorpusSource(path, kind)


def source_stamp(source: CorpusSource) -> tuple:
    """Invalidate the session import when local source records or media change."""
    root = source.root
    if root is None:
        return _file_stamp(source.path)
    return tuple((str(item.relative_to(root)), *_file_stamp(item))
                 for item in sorted(root.rglob("*"))
                 if item.is_file() and item.resolve().is_relative_to(root))


def read_engine_rows(path: Path, errors: list[dict]) -> list[tuple[int, dict]]:
    """Check graph-card shapes before applying identity rules or scoring."""
    return validate_engine_rows(read_jsonl(path, errors), str(path), errors)


def validate_engine_rows(numbered, source: str, errors: list[dict]) -> list[tuple[int, dict]]:
    from graph.ftf_graph.card import parse_card
    from graph.ftf_graph.presentation import card_tooltip

    rows = []
    for line, row in numbered:
        if not isinstance(row, dict):
            errors.append({"file": source, "line": line, "ad_id": None, "error": "expected JSON object"})
            continue
        try:
            for key in ("provenance", "extensions", "visual", "text", "extraction", "infra", "page", "audio"):
                if key in row and row[key] is None:
                    del row[key]
                elif key in row and not isinstance(row[key], dict):
                    raise ValueError(f"{key}: expected JSON object")
            card = parse_card(row, trusted=frozenset())
            if card.phash is not None and not 0 <= card.phash < 2 ** 64:
                raise ValueError("phash spoza 64 bitów")
            card_tooltip(card, "bez kampanii")
        except (AttributeError, TypeError, ValueError, RecursionError) as exc:
            errors.append({"file": source, "line": line, "ad_id": row.get("ad_id"), "error": str(exc)})
        else:
            rows.append((line, row))
    return rows


def _pages(path: Path, errors: list[dict]) -> list[PageCapture]:
    pages = {}
    for line, record in read_jsonl(path, errors):
        capture_id = record.get("capture_id")
        if not isinstance(capture_id, str) or not capture_id.strip():
            errors.append({"file": str(path), "line": line, "error": "missing_capture_id"})
            continue
        locator = f"{path}:{line}"
        if capture_id in pages:
            earlier = pages[capture_id]
            if earlier.record != record:
                errors.append({"file": str(path), "line": line, "capture_id": capture_id,
                               "first_source_ref": earlier.locator, "error": "conflicting_page_capture"})
            continue
        pages[capture_id] = PageCapture(capture_id, record, locator)
    return list(pages.values())


def _url_key(url) -> tuple | None:
    if not isinstance(url, str):
        return None
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None:
            return None
        default = 443 if parsed.scheme == "https" else 80
        return parsed.scheme, parsed.hostname.lower(), parsed.port or default, parsed.path or "/", parsed.query, parsed.fragment
    except ValueError:
        return None


def _verified_links(root: Path, records, pages: list[PageCapture], errors: list[dict]) -> dict:
    path = root / "observations/ad_page_links.jsonl"
    if not path.is_file():
        return {}
    ads = {ad.ad_id: ad for ad in records}
    pages_by_id = {page.id: page for page in pages}
    matches, ambiguous, sources = {}, set(), {}
    for line, link in read_jsonl(path, errors):
        ref = _mapping(link.get("source_ref"))
        ad_id, capture_id = link.get("ad_id"), link.get("capture_id")
        origin, observed = link.get("origin_id"), link.get("observed_at")
        field, record_id, filename = ref.get("field"), ref.get("record_id"), ref.get("file")
        if not all(isinstance(value, str) and value.strip() for value in
                   (ad_id, capture_id, origin, observed, field, record_id, filename)):
            errors.append({"file": str(path), "line": line, "error": "invalid_ad_page_link"})
            continue
        ad, page = ads.get(ad_id), pages_by_id.get(capture_id)
        source = (root / filename).resolve()
        source_rows = []
        if source.is_relative_to(root) and not Path(filename).is_absolute() and source.is_file():
            if source not in sources:
                sources[source] = read_jsonl(source, errors)
            source_rows = [(row_line, row) for row_line, row in sources[source]
                           if record_id in (row.get("id"), row.get("record_id"), row.get("ad_id"))]
        destination = _url_key(ref.get("value"))
        value = source_rows[0][1] if len(source_rows) == 1 else None
        for key in field.split("."):
            value = _mapping(value).get(key)
        own_ref = ad.record.get("source", {}).get("ad_ref") if ad else None
        document_url = page.document.get("url") if page else None
        recorded_target = _url_key(document_url or page.url) if page else None
        if (ad is None or page is None or record_id not in (ad_id, own_ref)
                or destination is None or destination != recorded_target
                or (page.document.get("query_keys") and not (document_url or recorded_target[4]))
                or value != ref.get("value")):
            errors.append({"file": str(path), "line": line, "ad_id": ad_id, "capture_id": capture_id,
                           "error": "unverified_ad_page_link"})
            continue
        declared = ad.record.get("landing_url")
        if (declared and _url_key(declared) != destination) or (
                ad_id in matches and matches[ad_id][0].id != capture_id):
            ambiguous.add(ad_id)
            errors.append({"file": str(path), "line": line, "ad_id": ad_id,
                           "error": "ambiguous_ad_page_link"})
            continue
        matches.setdefault(ad_id, (page, link, f"{source}:{source_rows[0][0]}#{field}"))
    return {ad_id: item for ad_id, item in matches.items() if ad_id not in ambiguous}


def _add_link(card: dict, page: PageCapture, link: dict, link_source: str) -> None:
    from .graph_features import text_features

    origin = f"{card['provenance']['dataset_id']}:{page.id}"
    headings = _strings(page.html.get("headings"))
    parts = [page.html.get("title"), *headings, page.html.get("body_excerpt")]
    body = "\n".join(dict.fromkeys(part for part in parts if isinstance(part, str) and part.strip()))
    card["page"] = {"origin_id": origin, "text": text_features(body, origin, source_refs=[f"{page.locator}#html"]),
                    "tracking_ids": {"meta_pixel": next(iter(page.pixels))} if len(page.pixels) == 1 else {}}
    card["infra"] = {"final_domain": page.url, "origin_id": origin, "source_ref": link_source}
    card["extensions"] = {"linked_page": {"capture_id": page.id, "source_ref": page.locator,
                                         "link_source_ref": link_source, "record": page.record}}
    card["extraction"]["evidence"].append({"field": "page.tracking_ids.meta_pixel", "origin_id": origin,
        "source_ref": f"{page.locator}#har.meta_pixel_ids", "method_version": "v0/HAR", "value": sorted(page.pixels)})
    value, source = page.captured_at
    if value:
        card["provenance"]["page_observations"] = [{"at": value, "source_ref": source, "capture_id": page.id}]


def load_analyst_corpus(source: Path | CorpusSource) -> AnalystCorpus:
    if isinstance(source, Path):
        source = identify_corpus(source)
    path = source.path
    if root := source.root:
        from .image_query import reference_cards

        corpus = load_corpus(root, ads_path=source.ads_path)
        cards, report = reference_cards(corpus)
        pages_path = root / "observations/pages.jsonl"
        pages = _pages(pages_path, report["errors"]) if pages_path.is_file() else []
        links = _verified_links(root, corpus.ads, pages, report["errors"])
        for card in cards:
            if item := links.get(card["provenance"]["original_ad_id"]):
                _add_link(card, *item)
        report["page_captures"] = len(pages)
        report["verified_links"] = len(links)
        return AnalystCorpus(corpus.dataset_id, cards, pages, report)
    if source.kind == "pages":
        errors: list[dict] = []
        pages = _pages(path, errors)
        root = path.parent.parent if path.parent.name == "observations" else path.parent
        return AnalystCorpus(root.name, pages=pages,
                             report={"accepted": 0, "page_captures": len(pages), "errors": errors})
    errors = []
    rows, duplicates = deduplicate_rows(read_engine_rows(path, errors), path.stem, str(path), errors)
    cards = [card for _, card in rows]
    hashes = [value for card in cards if isinstance(value := card.get("visual", {}).get("sha256"), str) and value]
    return AnalystCorpus(path.stem, cards, report={"accepted": len(cards), "duplicates": duplicates,
        "errors": errors, "repeated_images": len(hashes) - len(set(hashes)),
        "fingerprint": hashlib.sha256(path.read_bytes()).hexdigest()[:16]})


def database_stamp(conn, dataset_id: str) -> tuple:
    """Cheap revision of a PostgreSQL dataset: the last graph_feed export and the last engine run."""
    feed = conn.execute("SELECT revision, written_ns FROM feed_export WHERE dataset_id = %s",
                        (dataset_id,)).fetchone()
    run = conn.execute("SELECT run_id FROM engine_run WHERE dataset_id = %s ORDER BY computed_at DESC, seq DESC LIMIT 1",
                       (dataset_id,)).fetchone()
    return (tuple(feed) if feed else None, str(run[0]) if run else None)


def load_database_corpus(conn, dataset_id: str) -> AnalystCorpus:
    """Current scraper cards (view card_current) with the same checks as an engine JSONL file."""
    from . import db

    source = f"postgresql:card_current/{dataset_id}"
    errors: list[dict] = []
    rows = validate_engine_rows(enumerate(db.load_cards(conn, dataset_id), 1), source, errors)
    rows, duplicates = deduplicate_rows(rows, dataset_id, source, errors)
    cards = [card for _, card in rows]
    hashes = [value for card in cards if isinstance(value := card.get("visual", {}).get("sha256"), str) and value]
    unavailable = conn.execute("SELECT count(*) FROM ad WHERE dataset_id = %s AND unavailable IS NOT NULL",
                               (dataset_id,)).fetchone()[0]
    return AnalystCorpus(f"postgres:{dataset_id}", cards, report={
        "accepted": len(cards), "duplicates": duplicates, "errors": errors,
        "repeated_images": len(hashes) - len(set(hashes)), "unavailable_in_database": unavailable,
        "revision": database_stamp(conn, dataset_id)})
