"""Comparable features and source locators for saved observations."""
import hashlib
import json
from pathlib import Path

from .catalog import artifact_path


TEXT_METHOD = "char-wb-3-5-hash1024-l2/v1"
SCRIPT_TYPES = {"text/javascript", "application/javascript"}


def text_features(body, origin_id, *, source_refs=()):
    features = {"ad_text": body}
    if origin_id and len(body.split()) >= 4 and len(body.strip()) >= 24:
        from sklearn.feature_extraction.text import HashingVectorizer

        vectorizer = HashingVectorizer(analyzer="char_wb", ngram_range=(3, 5), n_features=1024)
        features.update(embedding=vectorizer.transform([body]).toarray()[0].round(6).tolist(),
                        method=TEXT_METHOD, origin_id=origin_id)
        if source_refs:
            features["source_refs"] = list(source_refs)
    return features


def image_artifacts(manifest):
    """Keep referenced logos and landing assets out of ad comparisons."""
    return [a for a in manifest.get("artifacts", [])
            if a["role"] == "image" and a.get("media_kind") != "card_attachment"]


def source_artifacts(manifest):
    return [a for a in manifest.get("artifacts", [])
            if a["role"] in {"source_record", "card", "card_html", "html", "har", "page_metadata"}
            or (a["role"] == "asset" and (a["type"] in SCRIPT_TYPES or a["type"] == "text/html"))]


def verified_sources(folder, manifest):
    valid = set()
    for item in source_artifacts(manifest):
        try:
            artifact_path(folder, item)
        except (OSError, ValueError):
            continue
        valid.add((item["path"], item["sha256"]))
    return valid


def is_verified(ref, valid):
    return (ref.get("file"), ref.get("origin_id")) in valid


def image_artifact(manifest, preferred):
    candidates = image_artifacts(manifest)
    if preferred:
        return next((a for a in candidates if a["path"] == preferred), None)
    if len(candidates) == 1:
        return candidates[0]


def image_features(folder: Path, artifact):
    if not artifact:
        return {}
    from .image_query import HASH_METHOD, MAX_BYTES, validate_image
    from imagehash import phash

    path = (folder / artifact["path"]).resolve()
    if not path.is_relative_to(folder.resolve()):
        return {}
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        sha = hashlib.sha256(data).hexdigest()
        if sha != artifact["sha256"]:
            return {}
        image, _ = validate_image(data)
    except (OSError, ValueError):
        return {}
    return {"sha256": sha, "phash": str(phash(image)), "origin_id": sha,
            "method": HASH_METHOD, "source_ref": {"file": artifact["path"], "origin_id": sha}}


def page_features(result, manifest, *, networks, valid):
    """Project a verified page or set of captures of the same page."""
    pages = [page for page in result["pages"] if is_verified(page.get("evidence", {}), valid)]
    sources = [page["evidence"] for page in pages]
    origins = {ref["origin_id"] for ref in sources}
    # All observations of a single document represent one dependency for scoring.
    origin = next(iter(origins)) if len(origins) == 1 else "page:" + manifest["capture_id"]
    pixels = list(result["pixels"])
    for item in [*pages, *networks]:
        pixels.extend(item["pixels"])
    pixels = [p for p in pixels if is_verified(p.get("evidence", {}), valid)]
    pixel_ids = {p["value"]["id"] for p in pixels if p["value"]["provider"] == "meta"}
    scripts = [a for a in manifest["artifacts"]
               if a["role"] == "asset" and a["type"] in SCRIPT_TYPES and (a["path"], a["sha256"]) in valid]
    page = {"origin_id": origin,
            "tracking_ids": {"meta_pixel": next(iter(pixel_ids))} if len(pixel_ids) == 1 else {},
            "script_hashes": sorted({a["sha256"] for a in scripts}),
            "source_refs": {"tracking_ids": [p["evidence"] for p in pixels
                                              if p["value"]["provider"] == "meta" and "evidence" in p]
                            if len(pixel_ids) == 1 else [],
                            "script_hashes": [{"file": a["path"], "origin_id": a["sha256"]} for a in scripts]}}
    templates = [p for p in pages if p.get("dom_template_minhash")]
    signatures = {json.dumps(p["dom_template_minhash"], sort_keys=True) for p in templates}
    if len(signatures) == 1:
        template = templates[0]["dom_template_minhash"]
        refs = [p["evidence"] for p in templates if p.get("evidence")]
        if refs:
            template = {**template, "origin_id": origin, "source_refs": refs}
        page["dom_template_minhash"] = template

    # Reading text preserves document order, and excludes UI/consent scaffolding.
    # Old bundles predate reading_text and retain comparable prose in content.
    texts = {}
    for document in pages:
        rows = ([r for r in document["reading_text"] if r["section"] == "content"]
                if "reading_text" in document else document.get("content", []))
        rows = [r for r in rows if is_verified(r.get("evidence", {}), valid)]
        if rows:
            body = "\n".join(dict.fromkeys(r["value"] for r in rows))
            texts[body] = [r["evidence"] for r in rows if r.get("evidence")]
    if len(texts) == 1:
        body, refs = next(iter(texts.items()))
        page["text"] = text_features(body, origin if refs else None, source_refs=refs)
    return page
