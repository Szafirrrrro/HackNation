"""Atomic ingestion of one private, offline observation."""
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from .cards import card
from .landing import Document, html_text, landing, library_identity
from .landing_quality import ANALYSIS_VERSION, summarize
from .page_text import consent_candidate, text_exports, transcript
from .media import AUDIO, IMAGES, VIDEO, ocr, screen_fields, transcribe
from .sources import digest, evidence, network, safe_url, script_pixels

VERSION = "scamgraph-capture/2"
DEFAULT_STORE = Path("data/captures")
HTML = {".html", ".htm"}


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


@contextmanager
def staging(store):
    # Inherit the private store's ACL, including access for the worker account.
    tmp = store / (".import-" + uuid4().hex)
    tmp.mkdir()
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp)


def files(source):
    if source.is_symlink() or source.is_junction():
        raise ValueError("Dowiązanie poza inwentarzem obserwacji")
    if source.is_file():
        yield source
    else:
        for child in sorted(source.iterdir()):
            yield from files(child)


def html_inputs(inputs, root):
    resources, cards, media = {}, set(), set()
    for path in inputs:
        if path.suffix.lower() not in HTML or path.parent not in {root, root / "ad"}:
            continue
        for node in Document(html_text(path)).nodes:
            if library_identity(node):
                cards.add(path)
            if node.tag not in {"img", "script", "link", "source", "video", "audio"}:
                continue
            try:
                url = urlsplit(node.attr("src") or node.attr("href"))
                if not url.netloc and not url.scheme and url.path:
                    local = (path.parent / unquote(url.path)).resolve()
                    if local.is_relative_to(root):
                        resources.setdefault(local, set()).add(path)
                        if node.tag in {"img", "video", "audio", "source"}:
                            media.add((path, local))
            except (ValueError, OSError):
                continue
    return resources, cards, media


def page_archive(source):
    return (source.is_dir() and (source / "metadata.json").is_file()
            and ((source / "page_files").is_dir() or (source / "network.har").is_file()))


def archive_metadata(source):
    meta = read_json(source / "metadata.json")
    if (not isinstance(meta, dict) or meta.get("status") not in ("success", "partial", "failed")
            or not isinstance(meta.get("errors"), list) or not isinstance(meta.get("captured_at"), str)
            or not isinstance(meta.get("input_url"), str)
            or not isinstance(meta.get("final_url"), (str, type(None)))):
        raise ValueError("Niepoprawne metadane pobrania strony.")
    return meta


def inventory(source, ad_card=False):
    root = source if source.is_dir() else source.parent
    inputs = []
    if source.is_dir():
        inputs = list(files(source))
    else:
        inputs = list(files(source))
        assets = source.with_name(source.stem + "_files")
        if source.suffix.lower() in HTML and assets.is_dir():
            inputs.extend(files(assets))
    flat_page = page_archive(source)
    nested_page = page_archive(root / "landing")
    resources, detected_cards, media = html_inputs(inputs, root) if not flat_page else ({}, set(), set())
    if ad_card:
        if not source.is_file() or source.suffix.lower() not in HTML:
            raise ValueError("--ad-card wymaga pojedynczego pliku HTML")
        detected_cards.add(source)
    found = []
    for path in inputs:
        rel = path.relative_to(root)
        suffix = path.suffix.lower()
        area = rel.parts[0] if len(rel.parts) > 1 and rel.parts[0] in {"ad", "landing", "network"} else None
        sub = Path(*rel.parts[1:]) if area else rel
        linked_media = any((owner in detected_cards or owner.parent == root / "ad")
                           for owner in resources.get(path, ()) if (owner, path) in media)
        card_resource = any(rel.parts[0] == page.stem + "_files" or page in resources.get(path, ())
                            for page in detected_cards)
        if flat_page or (area == "landing" and nested_page):
            area = "landing"
            role = {"network.har": "har", "page.html": "html", "metadata.json": "page_metadata"}.get(sub.as_posix(), "asset")
        elif linked_media and suffix in IMAGES | AUDIO | VIDEO:
            area = "ad"
            role = "image" if suffix in IMAGES else "audio" if suffix in AUDIO else "video"
        elif card_resource or (area == "ad" and len(sub.parts) > 1 and sub.parts[0].endswith("_files")):
            area, role = "ad", "card_asset"
        elif area == "landing" and (suffix not in HTML or len(sub.parts) > 1):
            role = "asset"
        elif area is None and (path in resources or len(rel.parts) > 1):
            area, role = "landing", "asset"
        elif suffix == ".har":
            area, role = "network", "har"
        elif suffix in HTML:
            area = area or ("ad" if path in detected_cards else "landing")
            role = "card_html" if area == "ad" else "html"
        elif suffix == ".json":
            area, role = "ad", "card"
        elif suffix in IMAGES | AUDIO | VIDEO:
            area = "ad"
            role = "image" if suffix in IMAGES else "audio" if suffix in AUDIO else "video"
        else:
            raise ValueError(f"Nieznana rola pliku {rel}. Zasoby strony umieść w landing/.")
        target = Path(area) / sub
        if any(item["path"] == target.as_posix() for _, item in found):
            raise ValueError("Kolizja ścieżek plików obserwacji")
        item = {"path": target.as_posix(), "role": role}
        if linked_media:
            item["media_kind"] = "card_attachment"
        found.append((path, item))
    if not found:
        raise ValueError("Pusta obserwacja")
    return found


def mime(path):
    if path.suffix.lower() == ".har":
        return "application/json"
    if path.name.lower().endswith((".js.pobrane", ".js.download")):
        return "text/javascript"
    value = mimetypes.guess_type(path.name)[0]
    if not value:
        with path.open("rb") as stream:
            prefix = stream.read(512).lstrip()
        if prefix.startswith((b"/*", b"!function", b"(function", b"var ", b"if(")):
            return "text/javascript"
    return value or "application/octet-stream"


def verified(folder, manifest):
    for item in [*manifest["artifacts"], *manifest.get("derived_files", []), manifest["result"]]:
        path = (folder / item["path"]).resolve()
        if not path.is_relative_to(folder.resolve()) or not path.is_file() or digest(path) != item["sha256"]:
            raise ValueError("Niezgodna suma pliku pakietu")


def _shortened_id(digits, card_id):
    if not card_id.isdecimal() or len(digits) >= len(card_id):
        return False
    # OCR can drop digits in the middle as well as at either end.
    remaining = iter(card_id)
    return all(digit in remaining for digit in digits)


def append_landing(result, page, item):
    result["opinions"].extend(page.pop("opinions"))
    result["signals"].extend(page.pop("signals"))
    result["pages"].append({**page, "evidence": evidence(item, document=True)})


def recover_response_text(folder, artifacts, result):
    original = next((a for a in artifacts if a["path"] == "landing/original/response.html"), None)
    for page in result["pages"]:
        if (not original or page["evidence"]["file"] not in {"landing/index.html", "landing/page.html"} or
                any(r["section"] == "content" for r in page["reading_text"])):
            continue
        try:
            doc = Document(html_text(folder / original["path"]))
            dialogs = {n.index for n in doc.nodes if consent_candidate(n) and re.search(r"cookie|ciastecz", n.words()[:250], re.I)}
            rows = transcript(doc, original, dialogs)
        except (ValueError, OSError, RuntimeError) as exc:
            result["issues"].append({"role": "html", "reason": f"Błąd odczytu tekstu pierwotnej odpowiedzi ({type(exc).__name__})",
                                     "evidence": evidence(original, document=True)})
            continue
        if any(r["section"] == "content" for r in rows):
            page["reading_text"] = rows
            page["reading_source"] = evidence(original, document=True)


def analyze(stage, artifacts, model_dir):
    result = {"method": VERSION, "ad_fields": [], "ocr": [], "asr": [], "pages": [], "networks": [],
              "pixels": [], "opinions": [], "signals": [], "issues": [], "ad_page_links": []}
    providers = set()
    for item in artifacts:
        path, role = stage / item["path"], item["role"]
        try:
            if role == "card":
                provider, fields, rows = card(read_json(path), item)
                if provider:
                    providers.add(provider)
                result["ad_fields"].extend(fields)
                result["opinions"].extend(rows)
            elif role in {"html", "card_html"}:
                page = landing(path, item, ad_card=role == "card_html")
                if role == "html":
                    append_landing(result, page, item)
                else:
                    for node in Document(html_text(path)).nodes:
                        identity = library_identity(node)
                        if identity:
                            attr, ad_ref = identity
                            ref = evidence(item, element=node.index, tag=node.tag, line=node.line, attribute=attr)
                            providers.add("meta-ad-library")
                            result["ad_fields"].append({"field": "provider", "value": "meta-ad-library", "evidence": ref})
                            if ad_ref:
                                result["ad_fields"].append({"field": "ad_ref", "value": ad_ref, "evidence": ref})
                    result["opinions"].extend(page["opinions"])
                    lines = page["content"]
                    result["ad_fields"].extend(screen_fields(lines))
                    result["ad_fields"].extend({"field": "text", **line} for line in lines)
            elif role == "har":
                result["networks"].append({**network(path, item), "evidence": evidence(item, document=True)})
            elif role == "asset" and (item["type"] in {"text/javascript", "application/javascript"} or path.name.isdecimal()):
                result["pixels"].extend(script_pixels(html_text(path), item))
            elif role == "image":
                lines = ocr(path, item)
                result["ocr"].extend(lines)
                result["ad_fields"].extend(screen_fields(lines))
                if not lines:
                    raise ValueError("Brak odczytanego tekstu OCR")
            elif role in {"video", "audio"}:
                result["asr"].append(transcribe(path, item, model_dir))
        except (ValueError, KeyError, TypeError, AttributeError, OSError, ImportError, RuntimeError,
                subprocess.SubprocessError) as exc:
            # Third-party error strings can contain raw source bytes, paths or URLs.
            local_reason = str(exc) if type(exc) is ValueError and str(exc).startswith(
                ("Brak ", "Nie wykryto", "Nagranie przekracza", "Obraz przekracza", "Pakiet wymaga")) else None
            result["issues"].append({"role": role, "reason": local_reason or f"Błąd analizy ({type(exc).__name__})",
                                     "evidence": evidence(item, document=True)})
    if len(providers) > 1:
        raise ValueError("Karty kilku dostawców w jednej obserwacji")
    id_fields = [field for field in result["ad_fields"] if field["field"] == "ad_ref"]
    card_ids = {str(field["value"]) for field in id_fields if "bbox" not in field["evidence"]["locator"]}
    for field in id_fields:
        if "bbox" in field["evidence"]["locator"]:
            digits = str(field["value"])
            if digits not in card_ids and any(_shortened_id(digits, ref) for ref in card_ids):
                result["ad_fields"].remove(field)
    return next(iter(providers), None), result


def capture(source, store=DEFAULT_STORE, provider=None, collected_at=None, model_dir=None, ad_card=False,
            *, upstream=None, acquisition_method="offline_import", source_kind="upload", landing_visit=None,
            parent_observation=None):
    source, store = Path(source).absolute(), Path(store).resolve()
    if not source.exists() or store.is_relative_to(source.resolve()) or source.resolve().is_relative_to(store):
        raise ValueError("Wskaż istniejące źródło oddzielone od katalogu wyników")
    found = inventory(source, ad_card)
    if page_archive(source):
        metadata = archive_metadata(source)
        collected_at = collected_at or metadata["captured_at"]
        landing_visit = {"status": metadata["status"], "url": safe_url(metadata["input_url"]),
                         "final_url": safe_url(metadata["final_url"]) if metadata["final_url"] else None,
                         "issues": [] if not metadata["errors"] else
                         [f"Liczba błędów zapisu strony: {len(metadata['errors'])}"]}
    if collected_at and datetime.fromisoformat(collected_at).utcoffset() is None:
        raise ValueError("Czas pozyskania wymaga strefy")
    if upstream:
        raw, locator, expected_sha = upstream
        found.append((raw, {"path": "ad/original/source" + raw.suffix.lower(), "role": "source_record",
                            "locator": locator}))
    store.mkdir(parents=True, exist_ok=True)
    with staging(store) as tmp:
        stage = Path(tmp) / "capture"
        for area in ("ad", "landing", "network"):
            (stage / area).mkdir(parents=True)
        artifacts = []
        for path, item in found:
            target = stage / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            artifact = {**item, "type": mime(target), "sha256": digest(target), "size": target.stat().st_size}
            if item["role"] == "source_record" and expected_sha and artifact["sha256"] != expected_sha:
                raise ValueError("Materiał źródłowy zmienił się od czasu odczytu.")
            if item["role"] == "image" and re.search(r"screenshot|screen.shot|zrzut|capture", target.stem, re.I):
                artifact["media_kind"] = "screenshot"
            artifacts.append(artifact)
        artifacts.sort(key=lambda a: a["path"])
        inferred, result = analyze(stage, artifacts, model_dir)
        recover_response_text(stage, artifacts, result)
        if inferred and provider and inferred != provider:
            raise ValueError("Zadeklarowany dostawca różni się od dostawcy karty")
        provider = inferred or provider or "unknown"
        identity = [provider, collected_at, [(i["path"], i["sha256"]) for i in artifacts]]
        if upstream:
            identity.extend((source_kind, acquisition_method, locator))
            result["method"] += "+discovery-1"
        if landing_visit is not None:
            result["landing_visit"] = landing_visit
        result["landing_analysis_version"] = ANALYSIS_VERSION
        result["landing_summary"] = summarize(stage, artifacts, result)
        evidence_id = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:20]
        observation_id = parent_observation or evidence_id
        # A new extractor or newly available OCR/ASR gets an immutable rendition.
        # Retries with identical evidence and analysis select the same directory.
        version = [observation_id, evidence_id, result] if parent_observation else [observation_id, result]
        rendition = json.dumps(version, sort_keys=True, ensure_ascii=False).encode()
        capture_id = hashlib.sha256(rendition).hexdigest()[:20]
        target = store / capture_id
        imported = datetime.now(timezone.utc).isoformat()
        refs = {str(f["value"]) for f in result["ad_fields"] if f["field"] == "ad_ref" and
                (not upstream or "pointer" in f["evidence"]["locator"])}
        if len(refs) > 1:
            raise ValueError("Kilka identyfikatorów emisji w jednej obserwacji")
        ad_ref = next(iter(refs), None)
        roles = {item["role"] for item in artifacts}
        availability = {}
        for name, expected in {"card": {"card", "card_html"}, "image": {"image"}, "recording": {"video", "audio"},
                               "landing": {"html"}, "assets": {"asset"}, "har": {"har"}}.items():
            available = bool(roles & expected)
            availability[name] = {"available": available, "reason": None if available else "Nie dostarczono w obserwacji"}
        if landing_visit is not None:
            availability["assets"]["available"] = any(a["path"].startswith(("landing/index_files/", "landing/page_files/"))
                                                       or a["path"] == "landing/scripts.zip" for a in artifacts)
            if not availability["assets"]["available"]:
                availability["assets"]["reason"] = "Brak osobno pobranych zasobów strony."
            for name in ("landing", "assets", "har"):
                if not availability[name]["available"] and landing_visit.get("reason"):
                    availability[name]["reason"] = landing_visit["reason"]
            has_screen = any(a["path"] == "landing/screenshot.png" for a in artifacts)
            availability["landing_screenshot"] = {"available": has_screen, "reason": None if has_screen else
                landing_visit.get("reason") or "Brak zrzutu renderowanej strony CTA."}
            full = any(a["path"] in {"landing/full-page.png", "landing/screenshot_full.png"} for a in artifacts)
            clipped = any(a["path"] == "landing/page-partial.png" for a in artifacts)
            availability["full_page_screenshot"] = {"available": full, "reason": None if full else
                "Zapisano ograniczony obszar strony." if clipped else
                landing_visit.get("reason") or "Brak pełnego zrzutu w czasie obserwacji."}
        screenshot = any(i.get("media_kind") == "screenshot" for i in artifacts)
        availability["screenshot"] = {"available": screenshot, "reason": None if screenshot else "Brak pliku rozpoznanego jako zrzut"}
        if not screenshot:
            reason = next((f["value"] for f in result["ad_fields"] if f["field"] == "screenshot_missing_reason"), None)
            if reason:
                availability["screenshot"]["reason"] = reason
        opinion_source = bool(result["opinions"] or result["pages"])
        result.update(capture_id=capture_id, opinion_source="available" if opinion_source else "missing")
        result["partial"] = bool(result["issues"] or (landing_visit or {}).get("issues")
                                 or any(not v["available"] for v in availability.values()))
        source_info = {"kind": source_kind, "provider": provider, "ad_ref": ad_ref,
                       "collected_at": collected_at or imported}
        ad_fields = result["ad_fields"]
        ad = {"ad_id": f"{provider}/{ad_ref}" if ad_ref else observation_id, "source": source_info}
        for role, key in (("image", "image_path"), ("audio", "audio_path"), ("video", "video_path")):
            item = next((i for i in artifacts if i["role"] == role and i.get("media_kind") != "card_attachment"), None)
            if item and not any(e["evidence"]["file"] == item["path"] and role == "image" and
                                e["reason"].endswith("(UnidentifiedImageError)") for e in result["issues"]):
                ad[key] = item["path"]
                ad[role + "_origin"] = item["sha256"]
        for field in ad_fields:
            if field["field"] == "advertiser_ref":
                ad["advertiser_ref"] = field["value"]
            if field["field"] == "text" and "text" not in ad:
                ad.update(text=field["value"], text_origin=field["evidence"]["origin_id"])
        result["ad"] = ad if any(k in ad for k in ("text", "image_path", "audio_path", "video_path")) else None
        if upstream:
            original = next(i for i in artifacts if i["role"] == "source_record")
            result["source_record"] = evidence(original, record=locator)
            if landing_visit and "document_entry" in landing_visit and availability["landing"]["available"]:
                har = next(i for i in artifacts if i["role"] == "har" and i["path"] in {"network/landing.har", "landing/network.har"})
                element = landing_visit["element"]
                result["ad_page_links"].append({
                    "ad_id": ad["ad_id"], "capture_id": capture_id, "origin_id": original["sha256"],
                    "observed_at": landing_visit["observed_at"],
                    "source_ref": {"file": original["path"], "record_id": ad_ref, "element": element,
                                   "field": landing_visit["attribute"], "value": landing_visit["href"]},
                    "evidence": evidence(original, element=element, attribute=landing_visit["attribute"]),
                    "navigation_evidence": evidence(har, entry=landing_visit["document_entry"]),
                    "final_url": landing_visit["final_url"]})
                ad.update(landing_url=landing_visit["url"], url_origin=original["sha256"])
                result["ad"] = ad
            if source_kind == "organizer" and original["path"].endswith(".jsonl"):
                ad["ad_id"] = ad_ref
                source_info["ad_ref"] = next((f["value"] for f in ad_fields if f["field"] == "library_ref"), None)
                if ad.get("image_origin") and ad.get("text"):
                    ad["text_origin"] = ad["image_origin"]
        exports = text_exports(stage, result["pages"], artifacts)
        write_json(stage / "extracted.json", result)
        manifest = {"schema_version": "capture-v1", "dataset_id": capture_id, "capture_id": capture_id, "observation_id": observation_id,
                    "source_description": "Lokalny import zapisanej obserwacji", "acquisition_method": acquisition_method,
                    "collected_at": collected_at or imported, "source_observed_at": collected_at, "imported_at": imported,
                    "provider": provider, "ad_ref": ad_ref, "availability": availability, "artifacts": artifacts,
                    "landing_summary": result["landing_summary"], "derived_files": exports,
                    "result": {"path": "extracted.json", "type": "application/json", "sha256": digest(stage / "extracted.json")}}
        write_json(stage / "manifest.json", manifest)
        try:
            os.rename(stage, target)
        except OSError:
            if not target.is_dir():
                raise
            prior = read_json(target / "manifest.json")
            verified(target, prior)
            if (prior["artifacts"] != artifacts or prior["provider"] != provider or prior["source_observed_at"] != collected_at):
                raise ValueError("Konflikt identyfikatora obserwacji")
        return target
