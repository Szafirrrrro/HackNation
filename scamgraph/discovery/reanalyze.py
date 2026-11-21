"""Build immutable analyses of saved landing documents without contacting any provider."""
import hashlib
import json
import os
from pathlib import Path
import shutil

from ..capture import append_landing, read_json, recover_response_text, staging, verified, write_json
from ..landing import landing
from ..landing_quality import ANALYSIS_VERSION, summarize
from ..sources import digest
from ..page_text import text_exports
from .engine import connection


def rendition(store, cid):
    src = store / cid
    if src.resolve().parent != store.resolve() or src.name != cid or not cid.isalnum():
        raise ValueError("Niepoprawna ścieżka pakietu")
    manifest = read_json(src / "manifest.json")
    if manifest["capture_id"] != cid:
        raise ValueError("Niezgodny identyfikator pakietu")
    verified(src, manifest)
    result = read_json(src / "extracted.json")
    if result.get("landing_analysis_version") == ANALYSIS_VERSION:
        return cid
    artifacts = manifest["artifacts"]
    html = [a for a in artifacts if a["role"] == "html"]
    pages = {a["path"] for a in html}
    result["pages"] = []
    result["opinions"] = [r for r in result["opinions"] if r["evidence"]["file"] not in pages]
    result["signals"] = [r for r in result["signals"] if r["evidence"]["file"] not in pages]
    result["issues"] = [r for r in result["issues"] if r["evidence"]["file"] not in pages]
    for item in html:
        append_landing(result, landing(src / item["path"], item), item)
    recover_response_text(src, artifacts, result)
    result["landing_analysis_version"] = ANALYSIS_VERSION
    result["method"] += "+" + ANALYSIS_VERSION
    result["landing_summary"] = summarize(src, artifacts, result)
    result["opinion_source"] = "available" if result["opinions"] or result["pages"] else "missing"
    result["partial"] = bool(result["issues"] or result.get("landing_visit", {}).get("issues")
                             or any(not v["available"] for v in manifest["availability"].values()))
    new_id = hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]
    result["capture_id"] = new_id
    for link in result["ad_page_links"]:
        link["capture_id"] = new_id
    target = store / new_id
    with staging(store) as temp:
        folder = temp / "capture"
        folder.mkdir()
        for area in ("ad", "landing", "network"):
            (folder / area).mkdir()
        for item in artifacts:
            source = src / item["path"]
            dest = folder / item["path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
        exports = text_exports(folder, result["pages"], artifacts)
        write_json(folder / "extracted.json", result)
        new_manifest = {**manifest, "capture_id": new_id, "dataset_id": new_id,
                        "landing_summary": result["landing_summary"], "derived_files": exports,
                        "reanalyzed_from": {"capture_id": cid, "manifest_sha256": digest(src / "manifest.json")},
                        "result": {**manifest["result"], "sha256": digest(folder / "extracted.json")}}
        write_json(folder / "manifest.json", new_manifest)
        verified(folder, new_manifest)
        try:
            os.rename(folder, target)
        except OSError:
            if not target.is_dir() or read_json(target / "manifest.json") != new_manifest:
                raise
            verified(target, new_manifest)
    return new_id


def reanalyze_run(config, run_id, phrase):
    state = Path(config["state_dir"])
    db_path = state / "discovery.sqlite3"
    def selected(db):
        return [tuple(r) for r in db.execute(
            "SELECT seq,capture_id FROM observations WHERE run_id=? AND phrase=? ORDER BY seq", (run_id, phrase))]
    with connection(db_path) as db:
        status = db.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()
        rows = selected(db)
        if not rows or not status or status[0] == "running":
            raise ValueError("Wymagany zakończony przebieg z zapisaną obserwacją dla wybranej frazy")
    updated = {cid: rendition(state / "captures", cid) for cid in dict.fromkeys(cid for _, cid in rows)}
    with connection(db_path, write=True) as db:
        if rows != selected(db):
            raise ValueError("W trakcie analizy zmieniły się obserwacje. Ponów odczyt.")
        db.executemany("UPDATE observations SET capture_id=? WHERE seq=? AND capture_id=?",
                       [(updated[cid], seq, cid) for seq, cid in rows if updated[cid] != cid])
    return updated
