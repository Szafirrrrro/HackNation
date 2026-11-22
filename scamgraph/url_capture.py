"""Manual URL acquisition shared by the analyst UI and future consumers."""
from pathlib import Path
import hashlib
from urllib.parse import urlunsplit

import idna

from .capture import capture, read_json
from .catalog import artifact_path
from .sources import address
from .discovery.landing_fetch import validate_url
from .discovery.landing_visit import visit


DEFAULT_STATE = Path(__file__).resolve().parents[1] / ".private-discovery" / "analyst"


def url_key(url: str) -> str:
    """Exact URL identity without storing query secrets in a graph card."""
    parsed = validate_url(url.strip())
    host = parsed.hostname.rstrip(".").lower()
    host = ("[" + host + "]" if ":" in host else
            idna.encode(host, uts46=True, std3_rules=True).decode("ascii"))
    port = parsed.port
    if port and port != (443 if parsed.scheme == "https" else 80):
        host += f":{port}"
    normalized = urlunsplit((parsed.scheme, host, parsed.path or "/", parsed.query, ""))
    return hashlib.sha256(normalized.encode()).hexdigest()


def existing_url_ids(url: str, cards: list[dict]) -> set[str]:
    key = url_key(url)
    matches = set()
    for card in cards:
        provenance = card.get("provenance", {})
        if provenance.get("url_key"):
            same = provenance["url_key"] == key
        else:
            saved = provenance.get("url", "")
            # Older page observations only retain host/path. Match them only
            # when the requested URL has no query and the path is not redacted.
            legacy = saved and "://" not in saved
            same = False
            if legacy and not validate_url(url.strip()).query and "[…]" not in saved:
                try:
                    same = url_key("https://" + saved) == url_key(
                        urlunsplit(validate_url(url.strip())._replace(scheme="https", fragment="")))
                except ValueError:
                    pass
            elif saved and not legacy:
                try:
                    same = url_key(saved) == key
                except ValueError:
                    pass
        if same:
            matches.add(card["ad_id"])
    return matches


def page_graph_card(folder: Path) -> dict | None:
    """Project a usable page observation into the graph's query format.

    The ID denotes a page capture, not an ad delivery. Never create AdPageLink
    or infer publication time from the time of the visit.
    """
    meta = read_json(folder / "manifest.json")
    extracted = read_json(artifact_path(folder, meta["result"]))
    visit_info = extracted.get("landing_visit", {})
    status = visit_info.get("http_status") or 0
    if (visit_info.get("content_status") != "usable" or visit_info.get("target_kind") != "web"
            or not 200 <= status < 300):
        return None
    # capture stores privacy-filtered URLs as host/path, without the scheme.
    target = address("https://" + visit_info["final_url"]) if visit_info.get("final_url") else None
    if not target or not extracted["pages"]:
        return None
    pixels = [*extracted["pixels"]]
    for item in [*extracted["pages"], *extracted["networks"]]:
        pixels.extend(item["pixels"])
    meta_ids = sorted({p["value"]["id"] for p in pixels if p["value"]["provider"] == "meta"})
    text = "\n".join(dict.fromkeys(row["value"] for page in extracted["pages"]
                                 for row in page["content"]))
    return {
        "ad_id": "page:" + meta["capture_id"],
        "provenance": {"source": "analyst_url", "record_kind": "page_capture",
                       "url": visit_info["url"], "fetched_at": meta["collected_at"],
                       "capture_id": meta["capture_id"], "snapshot": str(folder)},
        "infra": {"final_domain": target["host"]},
        "page": {"tracking_ids": {"meta_pixel": meta_ids[0]} if len(meta_ids) == 1 else {},
                 "script_hashes": sorted({a["sha256"] for a in meta["artifacts"]
                    if a["role"] == "asset" and a["type"] in {"text/javascript", "application/javascript"}})},
        "text": {"ad_text": text},
        "extensions": {"page_observation": extracted},
    }


def capture_url(url: str, state_dir: Path = DEFAULT_STATE) -> dict:
    """Archive and extract one page, without asserting an ad–page relationship.

    Failed/partial visits are retained too. Paths point to private local evidence;
    ``report`` describes acquisition, not the result of campaign matching.
    """
    url = url.strip()
    validate_url(url)
    # An explicit analyst request always acquires evidence, regardless of ranking.
    state = Path(state_dir).resolve()
    report = visit(state / "pages", url)
    archive = state / "pages" / report["page_id"]
    # Preserve the archive even when extraction cannot finish.
    result = {"report": report, "archive": str(archive), "capture": None, "card": None}
    try:
        extracted = capture(archive, state / "captures", source_kind="analyst_url",
                            acquisition_method="manual_url")
        result["capture"] = str(extracted)
        result["card"] = page_graph_card(extracted)
        if result["card"]:
            result["card"]["provenance"]["url_key"] = url_key(url)
    except (ValueError, OSError, RuntimeError) as exc:
        result["extraction_error"] = f"Nie ukończono ekstrakcji ({type(exc).__name__})."
    return result
