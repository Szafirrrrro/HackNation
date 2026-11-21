"""Adapter wejścia: korpus v0 (docs/DATA_CONTRACT.md) albo luźny katalog plików.

Korpus v0: <root>/manifest.json, ads.jsonl, media/, opcjonalnie
observations/screenshots.jsonl (observation_group obrazu i przepisanego z niego tekstu).

Luźny katalog (np. data/sample albo dane od użytkownika): każdy plik obrazu/audio i każdy
*.txt staje się osobnym rekordem `Ad` (source.kind=upload). ad_id = "file-" + 16 znaków
SHA-256 zawartości, więc ponowny import i identyczne kopie dają to samo ID.

Z rekordów `Ad` powstają `Item`-y (jedno wejście dla modelu) z `origin_id` zgodnie z
kontraktem: tekst przepisany ze zrzutu dziedziczy origin_id obrazu.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".mp4", ".webm", ".mov", ".mkv"}
TEXT_EXT = {".txt"}


@dataclass
class Ad:
    ad_id: str
    record: dict                    # rekord w formacie v0 (do zapisania w ads.jsonl wyjścia)
    image: Path | None = None
    audio: Path | None = None
    text: str | None = None
    image_origin: str | None = None
    text_origin: str | None = None
    audio_origin: str | None = None


@dataclass
class Item:
    ad_id: str
    origin_id: str
    source_field: str               # pole Ad lub pochodne: "image_path", "text", "ocr.text@..."
    modality: str                   # image | text | audio
    path: str | None = None
    text: str | None = None

    @property
    def key(self) -> str:
        return f"{self.ad_id}|{self.source_field}"

    @property
    def label(self) -> str:
        return f"{self.ad_id} [{self.source_field}]"


@dataclass
class Corpus:
    root: Path
    dataset_id: str
    mode: str                       # v0 | files
    ads: list[Ad]
    report: dict = field(default_factory=dict)

    def items(self, modality: str) -> list[Item]:
        out = []
        for a in self.ads:
            if modality == "image" and a.image:
                out.append(Item(a.ad_id, a.image_origin, "image_path", "image", path=str(a.image)))
            elif modality == "text" and a.text:
                out.append(Item(a.ad_id, a.text_origin, "text", "text", text=a.text))
            elif modality == "audio" and a.audio:
                out.append(Item(a.ad_id, a.audio_origin, "audio_path", "audio", path=str(a.audio)))
        return out

    def missing(self, modality: str) -> list[Ad]:
        attr = {"image": "image", "text": "text", "audio": "audio"}[modality]
        return [a for a in self.ads if not getattr(a, attr)]


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _jsonl(p: Path, errors: list) -> list[dict]:
    rows = []
    if not p.exists():
        return rows
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            errors.append({"file": p.name, "line": i, "error": str(e)})
    return rows


def _load_v0(root: Path) -> Corpus:
    errors: list = []
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8")) \
        if (root / "manifest.json").exists() else {}
    shots = {r["ad_id"]: r for r in _jsonl(root / "observations" / "screenshots.jsonl", errors)
             if "ad_id" in r}
    ads, seen, skipped = [], set(), []
    for rec in _jsonl(root / "ads.jsonl", errors):
        ad_id = rec.get("ad_id")
        if not ad_id:
            errors.append({"file": "ads.jsonl", "error": "rekord bez ad_id"})
            continue
        if ad_id in seen:  # ponowny import tego samego ID jest idempotentny
            skipped.append(ad_id)
            continue
        seen.add(ad_id)
        shot = shots.get(ad_id, {})
        img_group = shot.get("observation_group") or f"{ad_id}#image_path"
        a = Ad(ad_id, rec)
        if rec.get("image_path"):
            p = root / rec["image_path"]
            if p.exists():
                a.image, a.image_origin = p, img_group
            else:
                errors.append({"ad_id": ad_id, "error": f"brak pliku {rec['image_path']}"})
        for k in ("audio_path", "video_path"):  # rozszerzenie kontraktu (multimedia)
            if rec.get(k) and (root / rec[k]).exists():
                a.audio, a.audio_origin = root / rec[k], f"{ad_id}#{k}"
                break
        if (rec.get("text") or "").strip():
            a.text = rec["text"].strip()
            from_shot = str(shot.get("text_source", "")).endswith("from_screenshot")
            a.text_origin = img_group if from_shot else f"{ad_id}#text"
        ads.append(a)
    return Corpus(root, manifest.get("dataset_id", root.name), "v0", ads,
                  {"errors": errors, "duplicate_ad_ids": skipped,
                   "manifest_schema": manifest.get("schema_version")})


def _load_files(root: Path) -> Corpus:
    ads: dict[str, Ad] = {}
    dups = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name.startswith("."):
            continue
        ext = p.suffix.lower()
        if ext not in IMG_EXT | AUDIO_EXT | TEXT_EXT:
            continue
        ad_id = "file-" + _sha256(p)[:16]
        rel = str(p.relative_to(root))
        if ad_id in ads:
            dups.append({"ad_id": ad_id, "path": rel, "same_as": ads[ad_id].record["source"]["ad_ref"]})
            continue
        ts = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
        rec = {"ad_id": ad_id, "source": {"kind": "upload", "provider": "local-files",
                                          "ad_ref": rel, "collected_at": ts}}
        a = Ad(ad_id, rec)
        if ext in IMG_EXT:
            rec["image_path"] = rel
            a.image, a.image_origin = p, f"{ad_id}#image_path"
        elif ext in AUDIO_EXT:
            rec["audio_path"] = rel
            a.audio, a.audio_origin = p, f"{ad_id}#audio_path"
        else:
            txt = p.read_text(encoding="utf-8", errors="replace").strip()
            if not txt:
                continue
            rec["text"] = txt
            a.text, a.text_origin = txt, f"{ad_id}#text"
        ads[ad_id] = a
    return Corpus(root, root.name, "files", list(ads.values()), {"duplicate_files": dups, "errors": []})


def load_corpus(root: str | Path) -> Corpus:
    root = Path(root)
    if (root / "ads.jsonl").exists():
        return _load_v0(root)
    return _load_files(root)
