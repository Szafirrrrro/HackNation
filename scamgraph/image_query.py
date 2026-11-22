"""Local image acquisition and reference cards for the analyst graph.

Uses the laboratory's ImageHash pHash64 and the capture adapter's local OCR.
No URL inferred from OCR is visited or promoted to infrastructure evidence.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile

from PIL import Image, ImageOps, UnidentifiedImageError
import imagehash

from models.common.corpus import Corpus, load_corpus
from .media import ocr

DEFAULT_STATE = Path(__file__).resolve().parents[1] / ".private-discovery/analyst/images"
DEFAULT_REFERENCES = Path(__file__).resolve().parents[1] / "data/nask-hacknation-2026"
MAX_BYTES = 20 * 1024**2
MAX_PIXELS = 32_000_000
HASH_METHOD = f"imagehash-{imagehash.__version__}/phash64+sha256/exif-transpose"


def validate_image(data: bytes) -> tuple[Image.Image, str]:
    if not data or len(data) > MAX_BYTES:
        raise ValueError("Zdjęcie musi mieć od 1 bajtu do 20 MiB.")
    try:
        with Image.open(io.BytesIO(data)) as source:
            fmt = source.format
            if fmt not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("Obsługiwane zdjęcia: PNG, JPEG i WebP.")
            if source.width * source.height > MAX_PIXELS:
                raise ValueError("Zdjęcie przekracza 32 miliony pikseli.")
            if getattr(source, "n_frames", 1) != 1:
                raise ValueError("Prześlij pojedynczy kadr zamiast animacji.")
            source.verify()
        with Image.open(io.BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.load()
        return image, {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[fmt]
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Nie można odczytać zdjęcia lub obraz przekracza limit pikseli.") from exc


def image_card(data: bytes, state_dir: Path = DEFAULT_STATE) -> dict:
    """Validate before writing; original bytes are private and content-addressed."""
    image, suffix = validate_image(data)
    collected_at = datetime.now(timezone.utc).isoformat()
    sha = hashlib.sha256(data).hexdigest()
    origin = "sha256:" + sha
    state_dir = Path(state_dir).resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / (sha + suffix)
    if not path.exists():
        path.write_bytes(data)
    artifact = {"path": str(path), "sha256": sha}
    evidence = [{"field": "visual.sha256", "origin_id": origin, "source_ref": str(path),
                 "method_version": "sha256"},
                {"field": "visual.phash", "origin_id": origin, "source_ref": str(path),
                 "method_version": HASH_METHOD}]
    warnings = []
    text, rows = "", []
    # OCR receives the same EXIF-normalized pixels as pHash, without modifying evidence.
    try:
        with tempfile.TemporaryDirectory(dir=state_dir) as temporary:
            normalized = Path(temporary) / "ocr.png"
            image.save(normalized)
            rows = ocr(normalized, artifact)
        text = "\n".join(row["value"] for row in rows)
        evidence.append({"field": "text.ocr_text", "origin_id": origin,
                         "source_ref": str(path), "method_version": rows[0]["method"] if rows else "local-ocr",
                         "coordinate_space": "exif-transposed RGB pixels",
                         "lines": rows})
        if not text.strip():
            warnings.append("OCR nie odczytał tekstu; porównanie obrazu nadal działa.")
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        warnings.append(f"OCR niedostępny ({type(exc).__name__}): {exc}")
    return {"ad_id": "image:" + sha[:24],
            "provenance": {"source": "upload", "record_kind": "image_query", "image_path": str(path),
                           "collected_at": collected_at, "extracted_at": datetime.now(timezone.utc).isoformat()},
            "visual": {"sha256": sha, "phash": str(imagehash.phash(image)), "origin_id": origin},
            "text": {"ad_text": text, "ocr_text": text, "ocr_origin_id": origin},
            "extraction": {"evidence": evidence, "warnings": warnings}}


def image_references(folder: str | Path, state_dir: Path = DEFAULT_STATE) -> tuple[list[dict], dict]:
    """Reuse v0 import identity/path rules; sharing bytes never merges deliveries."""
    root = Path(folder).resolve()
    if not root.is_dir():
        raise ValueError(f"Nie ma katalogu zdjęć referencyjnych: {root}")
    # The v0 importer confines declared media; also cover symlinks in loose files
    # before load_corpus reads/hashes them.
    for path in root.rglob("*"):
        if path.is_symlink() and not path.resolve().is_relative_to(root):
            raise ValueError(f"Ścieżka poza katalogiem referencji: {path.name}")
    cards, report = reference_cards(load_corpus(root), state_dir)
    if not cards:
        raise ValueError("Katalog nie zawiera użytecznych zdjęć PNG/JPEG/WebP ani tekstów referencyjnych.")
    return cards, report


def reference_cards(corpus: Corpus, state_dir: Path = DEFAULT_STATE) -> tuple[list[dict], dict]:
    """Materialize supported v0 comparison features while retaining source fields."""
    from .graph_features import text_features

    report = deepcopy(corpus.report)
    report["dataset_id"] = corpus.dataset_id
    report["fingerprint"] = corpus.fingerprint
    report.setdefault("errors", [])
    cards, extracted = [], {}
    for ad in corpus.ads:
        record = ad.record
        source = record.get("source", {})
        origin_ref = f"{corpus.ads_path}:{ad.source_line}" if ad.source_line else str(corpus.root)
        provenance = {"source": source.get("provider") or "image_reference", "provider": source.get("provider"),
                      "ad_ref": source.get("ad_ref"), "source_kind": source.get("kind"),
                      "record_kind": "image_reference", "original_ad_id": ad.ad_id,
                      "dataset_id": corpus.dataset_id, "source_ref": origin_ref,
                      "url": source.get("record_url"), "collected_at": source.get("collected_at"),
                      "published_at": source.get("published_at") or record.get("published_at"),
                      "published_at_field": "source.published_at" if source.get("published_at") else "published_at"}
        card = {"ad_id": f"reference:{corpus.dataset_id}:{ad.ad_id}", "provenance": provenance,
                "text": {}, "visual": {}, "extraction": {"evidence": [], "warnings": [], "missing": dict(ad.missing)}}
        extraction = card["extraction"]
        if ad.image:
            try:
                if ad.image.stat().st_size > MAX_BYTES:
                    raise ValueError("Zdjęcie przekracza 20 MiB.")
                data = ad.image.read_bytes()
                sha = hashlib.sha256(data).hexdigest()
                if sha not in extracted:
                    extracted[sha] = image_card(data, state_dir)
                projected = deepcopy(extracted[sha])
                card.update(visual=projected["visual"], text=projected["text"])
                provenance.update(image_path=projected["provenance"]["image_path"],
                                  image_source=str(ad.image), extracted_at=projected["provenance"]["extracted_at"])
                # Keep source observation identity; SHA only identifies shared bytes.
                card["visual"]["origin_id"] = ad.image_origin
                card["text"]["ocr_origin_id"] = ad.image_origin
                extraction.update(projected["extraction"])
                for row in extraction["evidence"]:
                    row["origin_id"] = ad.image_origin
                    row["source_ref"] = str(ad.image)
            except (ValueError, OSError) as exc:
                extraction["missing"]["image"] = str(exc)
                report["errors"].append({"ad_id": ad.ad_id, "source_ref": origin_ref, "error": str(exc)})
        if ad.text:
            card["text"].update(text_features(ad.text, ad.text_origin, source_refs=[f"{origin_ref}#text"]))
            if not card["text"].get("ocr_text"):
                card["text"].update(ocr_text=ad.text, ocr_origin_id=ad.text_origin)
                extraction["evidence"].append({"field": "text.ocr_text", "origin_id": ad.text_origin,
                    "source_ref": f"{origin_ref}#text", "method_version": "source-transcription/v0"})
            extraction["evidence"].append({"field": "text.ad_text", "origin_id": ad.text_origin,
                "source_ref": f"{origin_ref}#text", "method_version": "source-transcription/v0"})
        if target := record.get("landing_url"):
            from graph.ftf_graph.card import normalize_domain
            if isinstance(target, str) and normalize_domain(target):
                origin = record.get("url_origin") or f"{ad.ad_id}#landing_url"
                card["infra"] = {"final_domain": target, "origin_id": origin}
                extraction["evidence"].append({"field": "infra.final_domain", "origin_id": origin,
                    "source_ref": f"{origin_ref}#landing_url", "method_version": "v0/landing-url", "value": target})
            else:
                extraction["missing"]["landing_url"] = "Nieprawidłowy adres celu."
        if ad.audio:
            extraction["missing"]["audio"] = "Wykryto plik nagrania. Import v0 nie wykonuje ekstrakcji audio."
        if card["visual"] or card["text"] or card.get("infra") or ad.audio:
            cards.append(card)
        else:
            report["errors"].append({"ad_id": ad.ad_id, "source_ref": origin_ref, "error": "no_comparable_input"})
    report["accepted"] = len(cards)
    hashes = [card["visual"]["sha256"] for card in cards if "sha256" in card["visual"]]
    report["repeated_images"] = len(hashes) - len(set(hashes))
    return cards, report


def analyze_image(data: bytes, reference_dir: str | None = None, state_dir: Path = DEFAULT_STATE) -> dict:
    card = image_card(data, state_dir)
    refs, report = image_references(reference_dir, state_dir) if reference_dir and reference_dir.strip() else ([], {})
    return {"card": card, "references": refs, "report": report}


def supplement_query(card: dict | None, description: str, landing_url: str, independent_text: bool) -> dict | None:
    """Preserve usable form fields and provenance even if one input is damaged."""
    from urllib.parse import urlsplit
    from graph.ftf_graph.card import normalize_domain
    from .graph_features import text_features

    description, landing_url = description.strip(), landing_url.strip()
    if not description and not landing_url:
        return card
    warnings = []
    if landing_url:
        try:
            parsed = urlsplit(landing_url)
            if (parsed.scheme not in {"http", "https"} or not normalize_domain(landing_url)
                    or parsed.username is not None or parsed.port == 0):
                raise ValueError
        except ValueError:
            warnings.append("Pominięto nieprawidłowy adres celu. Podaj pełny adres HTTP lub HTTPS.")
            landing_url = ""
    if card is None and not (description or landing_url):
        raise ValueError(warnings[0])
    if not description and not landing_url:
        card["extraction"]["warnings"].extend(warnings)
        return card
    payload = [card.get("visual", {}).get("sha256") if card else None, description, landing_url, independent_text]
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()[:24]
    card = card or {"provenance": {"source": "upload", "collected_at": datetime.now(timezone.utc).isoformat()},
                    "visual": {}, "text": {}, "extraction": {"warnings": [], "evidence": []}}
    card["ad_id"] = "ad-query:" + digest
    card["provenance"].update(record_kind="ad_query", source_ref="Formularz analityka")
    extraction = card["extraction"]
    extraction["warnings"].extend(warnings)
    if description:
        source = "Formularz analityka#tekst_reklamy"
        origin = f"{card['ad_id']}#text" if independent_text else card["visual"].get("origin_id")
        origin = origin or f"{card['ad_id']}#text"
        card["text"].update(text_features(description, origin, source_refs=[source]))
        extraction["evidence"].append({"field": "text.ad_text", "origin_id": origin, "source_ref": source,
            "method_version": "analyst-ad-text/v1", "source_kind": "opis reklamy" if independent_text else "transkrypcja"})
    if landing_url:
        source = "Formularz analityka#znany_adres_celu"
        origin = f"{card['ad_id']}#landing_url"
        card["infra"] = {"final_domain": landing_url, "origin_id": origin, "source_ref": source}
        extraction["evidence"].append({"field": "infra.final_domain", "origin_id": origin, "source_ref": source,
                                      "method_version": "analyst-target/v1", "value": landing_url})
    return card
