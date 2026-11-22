"""Local image acquisition and reference cards for the analyst graph.

Uses the laboratory's ImageHash pHash64 and the capture adapter's local OCR.
No URL inferred from OCR is visited or promoted to infrastructure evidence.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
from pathlib import Path
import subprocess
import tempfile

from PIL import Image, ImageOps, UnidentifiedImageError
import imagehash

from models.common.corpus import load_corpus
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
                           "fetched_at": datetime.now(timezone.utc).isoformat()},
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
    corpus = load_corpus(root)
    report = deepcopy(corpus.report)
    report["dataset_id"] = corpus.dataset_id
    report["fingerprint"] = corpus.fingerprint
    report.setdefault("errors", [])
    cards, extracted = [], {}
    for ad in corpus.ads:
        card = {"ad_id": ad.ad_id, "provenance": {"source": "image_reference", "record_kind": "image_reference"},
                "text": {}, "visual": {}, "extraction": {"evidence": [], "warnings": []}}
        if ad.image:
            try:
                if ad.image.stat().st_size > MAX_BYTES:
                    raise ValueError("Zdjęcie przekracza 20 MiB.")
                data = ad.image.read_bytes()
                sha = hashlib.sha256(data).hexdigest()
                if sha not in extracted:
                    extracted[sha] = image_card(data, state_dir)
                card = deepcopy(extracted[sha])
                card["ad_id"] = ad.ad_id
                card["provenance"].update(source="image_reference", record_kind="image_reference",
                                          source_ref=str(ad.image), dataset_id=corpus.dataset_id)
                # Keep source observation identity; SHA only identifies shared bytes.
                card["visual"]["origin_id"] = ad.image_origin
                card["text"]["ocr_origin_id"] = ad.image_origin
                for row in card["extraction"]["evidence"]:
                    row["origin_id"] = ad.image_origin
            except (ValueError, OSError) as exc:
                report["errors"].append({"ad_id": ad.ad_id, "error": str(exc)})
        if ad.text and not card["text"].get("ocr_text"):
            card["text"].update(ad_text=ad.text, ocr_text=ad.text, ocr_origin_id=ad.text_origin)
            card["extraction"]["evidence"].append({"field": "text.ocr_text", "origin_id": ad.text_origin,
                "source_ref": f"{root}/ads.jsonl#{ad.ad_id}.text", "method_version": "source-transcription/v0"})
        if card["visual"] or card["text"]:
            card["provenance"]["original_ad_id"] = ad.ad_id
            card["provenance"]["dataset_id"] = corpus.dataset_id
            card["ad_id"] = f"reference:{corpus.dataset_id}:{ad.ad_id}"
            cards.append(card)
    report["accepted"] = len(cards)
    if not cards:
        raise ValueError("Katalog nie zawiera użytecznych zdjęć PNG/JPEG/WebP ani tekstów referencyjnych.")
    return cards, report


def analyze_image(data: bytes, reference_dir: str | None = None, state_dir: Path = DEFAULT_STATE) -> dict:
    if reference_dir is None:
        reference_dir = str(DEFAULT_REFERENCES) if DEFAULT_REFERENCES.is_dir() else ""
    card = image_card(data, state_dir)
    refs, report = image_references(reference_dir, state_dir) if reference_dir.strip() else ([], {})
    return {"card": card, "references": refs, "report": report}
