"""Operator configuration and publication shared by CLI, worker and panel."""
import hashlib
import importlib
import json
import os
import re
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import urljoin

from ..capture import capture, staging, write_json
from ..media import AUDIO, IMAGES, VIDEO
from .types import SourceError

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "discovery.json"


def manual_selection(state, sid):
    db_path = state / "manual-imports.sqlite3"
    if not db_path.is_file():
        return None
    with closing(sqlite3.connect(db_path, timeout=10)) as db:
        db.execute("BEGIN")
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='active'").fetchone():
            return None
        row = db.execute("SELECT country FROM active WHERE source=?", (sid,)).fetchone()
        if row:
            paths = dict(db.execute("SELECT phrase,path FROM files WHERE source=? AND country=? ORDER BY phrase",
                                    (sid, row[0])))
            return {"mode": "import", "imports": paths, "phrases": list(paths), "country": row[0],
                    "synthetic": False, "path": None, "using_manual_selection": True}


def restore_config(config, sid):
    db_path = Path(config["state_dir"]) / "manual-imports.sqlite3"
    if db_path.is_file():
        with closing(sqlite3.connect(db_path, timeout=10)) as db, db:
            db.execute("DELETE FROM active WHERE source=?", (sid,))


def resolve(base, path):
    return str((base / path).resolve())


def load_config(file=DEFAULT_CONFIG):
    file = Path(file).resolve()
    config = json.loads(file.read_text(encoding="utf-8-sig"))
    config["_config_file"] = str(file)
    base = file.parent
    state = Path(resolve(base, config.get("state_dir", ".private-discovery")))
    config["state_dir"] = str(state)
    interval = config.setdefault("interval_seconds", 1800)
    if not isinstance(interval, (int, float)) or not 1 <= interval <= 604800:
        raise ValueError("Interwał musi wynosić od 1 do 604800 sekund.")
    if not isinstance(config["sources"], dict) or not config["sources"]:
        raise ValueError("Brak źródeł w konfiguracji.")
    for sid, opts in config["sources"].items():
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", sid):
            raise ValueError("Nieprawidłowy identyfikator źródła.")
        opts["state_dir"] = str(state)
        opts["archive_dir"] = str(state / "archives" / sid)
        if opts.get("manual_import"):
            opts.update(manual_selection(state, sid) or {})
        for key in ("path",):
            if opts.get(key):
                opts[key] = resolve(base, opts[key])
        opts["imports"] = {phrase: resolve(base, p) for phrase, p in opts.get("imports", {}).items()}
        phrases = opts["phrases"]
        if not isinstance(phrases, list) or not 1 <= len(phrases) <= 50 or not all(
                isinstance(p, str) and 1 <= len(p.strip()) <= 200 for p in phrases):
            raise ValueError(f"Nieprawidłowe frazy dla {sid}.")
        opts["phrases"] = list(dict.fromkeys(p.strip() for p in phrases))
        if not isinstance(opts["limit"], int) or not 1 <= opts["limit"] <= 100:
            raise ValueError(f"Limit {sid} musi wynosić od 1 do 100.")
        if not re.fullmatch("[A-Z]{2}", opts["country"]) or opts["mode"] not in {"live", "import", "replay"}:
            raise ValueError(f"Nieprawidłowy kraj lub tryb {sid}.")
    return config


def save_import(config, sid, name, payload, phrase, country):
    options = config["sources"][sid]
    if not options.get("manual_import"):
        raise ValueError("Źródło nie obsługuje ręcznie zapisanego wyniku.")
    suffix = Path(name).suffix.lower()
    if suffix not in {".json", ".html", ".htm"} or not 0 < len(payload) <= 12 * 1024**2:
        raise ValueError("Wybierz plik HTML lub JSON do 12 MiB.")
    if not phrase.strip() or len(phrase) > 200 or not re.fullmatch("[A-Z]{2}", country):
        raise ValueError("Podaj frazę i dwuliterowy kod kraju zapisanego wyniku.")
    root = Path(config["state_dir"]) / "imports" / sid
    root.mkdir(parents=True, exist_ok=True)
    path = root / (hashlib.sha256(payload).hexdigest() + suffix)
    with staging(root) as stage:
        tmp = stage / "upload"
        tmp.write_bytes(payload)
        os.replace(tmp, path)
    with closing(sqlite3.connect(Path(config["state_dir"]) / "manual-imports.sqlite3", timeout=10)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE IF NOT EXISTS active(source TEXT PRIMARY KEY, country TEXT NOT NULL)")
        db.execute("""CREATE TABLE IF NOT EXISTS files(source TEXT, country TEXT, phrase TEXT, path TEXT NOT NULL,
                      PRIMARY KEY(source,country,phrase))""")
        db.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?)", (sid, country, phrase.strip(), str(path)))
        if db.execute("SELECT count(*) FROM files WHERE source=? AND country=?", (sid, country)).fetchone()[0] > 50:
            raise ValueError("Limit ręcznie zapisanych fraz dla kraju wynosi 50.")
        db.execute("INSERT OR REPLACE INTO active VALUES (?,?)", (sid, country))


def configured_fetch(options, query):
    # Imports run inside the bounded source process, including optional SDKs.
    try:
        module, name = options["adapter"].split(":")
        fetch = getattr(importlib.import_module(module), name)
    except Exception as exc:
        raise SourceError(f"Nie można załadować adaptera {options.get('adapter')} ({type(exc).__name__}).") from exc
    yield from fetch(options, query)


def engine_for(config):
    from .engine import Engine
    database = str(Path(config["state_dir"]) / "discovery.sqlite3")
    sources = {sid: {**options, "queue_landing": True, "domain_db": database} for sid, options in config["sources"].items()}
    return Engine({**config, "sources": sources, "start_immediately": True},
                  dict.fromkeys(sources, configured_fetch), publish)


def collect_landing(stage, options, finding, *, defer=False):
    from ..landing import Document
    from .cta import destination, target_identity
    from .landing_visit import visit
    from .landing_fetch import public_url
    from .trusted_domains import match_url, skip_reason
    from .verified_entity import match_verified_entity

    index = finding.card.get("cta_element")
    candidates = finding.card.get("landing_candidates", [])
    if index is None:
        return {"content_status": "review" if candidates else "no_target", "reason_code": "unconfirmed_target" if candidates else "no_target",
                "candidates": candidates, "reason": finding.card.get("landing_missing_reason") or "Karta bez dostępnego odnośnika CTA."}
    raw = finding.original.read_bytes()
    if hashlib.sha256(raw).hexdigest() != finding.source_sha256:
        raise SourceError("Materiał źródłowy karty zmienił się przed odczytem CTA.")
    doc = Document(raw.decode("utf8"))
    node = doc.nodes[index - 1] if isinstance(index, int) and 1 <= index <= len(doc.nodes) else None
    attribute = finding.card.get("cta_attribute")
    inside_card = node and any(finding.locator == f"element:{p.index}" for p in (node, *node.ancestors()))
    href = node.attr(attribute) if inside_card and attribute in {"href", "data-href", "data-url"} else ""
    url = destination(href) if href else None
    if not url:
        return {"status": "failed", "content_status": "error", "reason_code": "invalid_card_evidence",
                "reason": "Brak poprawnego odnośnika we wskazanym elemencie karty."}
    database = options.get("domain_db")
    host = match_url(database, url)
    verified = match_verified_entity(url, options)
    timeout = options.get("landing_timeout", 22)
    if host:
        outcome = {"status": "trusted_domain", "content_status": "skipped", "reason_code": "trusted_domain",
                   "trusted_domain": host, "reason": skip_reason(host)}
    elif verified:
        code, reason = verified
        outcome = {"status": "skipped", "content_status": "skipped", "reason_code": code,
                   "reason": reason}
    elif defer:
        outcome = {"status": "queued", "content_status": "pending", "reason_code": "queued",
                   "reason": "Oczekuje na odczyt strony docelowej."}
    elif timeout < 2:
        outcome = {"status": "failed", "content_status": "error", "reason_code": "document_timeout",
                   "reason": "Brak czasu na pobranie CTA w tym przebiegu."}
    else:
        store = Path(options["state_dir"]) / "pages"
        outcome = visit(store, url, timeout, database) if database else visit(store, url, timeout)
    if "page_id" in outcome:
        archive = Path(options["state_dir"]) / "pages" / outcome["page_id"]
        shutil.copytree(archive, stage / "landing")
    return {"target_kind": target_identity(url)[0], **outcome, "element": index, "attribute": attribute,
            "href": public_url(urljoin("https://www.facebook.com/", href)), "label": finding.card["cta"],
            "target_basis": finding.card.get("cta_basis", "label"), "candidates": candidates}


def publish(sid, options, finding):
    state = Path(options["state_dir"])
    state.mkdir(parents=True, exist_ok=True)
    with staging(state) as stage:
        ad = stage / "ad"
        ad.mkdir()
        card = {**finding.card, "id": finding.ad_ref, "provider": options["provider"],
                "query_phrase": options["query_phrase"]}
        if options["mode"] != "import" or options.get("country_filter", True):
            card["query_country"] = options["query_country"]
        write_json(ad / "card.json", card)
        media = ([finding.image] if finding.image else []) + list(finding.media)
        for i, path in enumerate(dict.fromkeys(media)):
            if path.suffix.lower() not in IMAGES | AUDIO | VIDEO or path.stat().st_size > 50 * 1024**2:
                raise SourceError("Nieobsługiwany format lub rozmiar dostarczonego medium.")
            basename = "screenshot" if path == finding.image else "media"
            shutil.copyfile(path, ad / (f"{basename}-{i+1}" + path.suffix.lower()))
        visit = None
        from .engine import queue_landing
        if queue_landing(options, finding):
            visit = collect_landing(stage, options, finding, defer=True)
            finding.skipped_domain = visit.get("trusted_domain")
        elif options["mode"] == "live" and options["provider"] == "meta-ad-library":
            visit = collect_landing(stage, options, finding)
        packet = capture(stage, state / "captures", options["provider"], finding.observed_at, landing_visit=visit,
                         source_kind=finding.source_kind, acquisition_method=options["mode"],
                         upstream=(finding.original, finding.locator, finding.source_sha256))
    return packet.name
