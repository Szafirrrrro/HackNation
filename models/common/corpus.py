"""Adapter wejścia: korpus v0 (docs/DATA_CONTRACT.md) albo luźny katalog plików.

Korpus v0: <root>/manifest.json, ads.jsonl, media/, opcjonalnie
observations/screenshots.jsonl (observation_group obrazu i przepisanego z niego tekstu).

Luźny katalog (np. data/sample albo dane od użytkownika): każdy plik obrazu/audio i każdy
*.txt staje się osobnym rekordem `Ad` (source.kind=upload). ad_id = "file-" + 16 znaków
SHA-256 zawartości, więc ponowny import i identyczne kopie dają to samo ID.

Pochodzenie (kontrakt, sekcja „Pochodzenie”): jawne `image_origin`/`text_origin` z rekordu,
potem `observation_group` (rekord lub screenshots.jsonl); domyślnie tekst reklamy z obrazem
dziedziczy pochodzenie obrazu. Ścieżki mediów muszą leżeć w katalogu korpusu.

`dataset_id`: z manifestu; dla luźnego katalogu (i v0 bez dataset_id) nazwa katalogu po
stronie hosta (CORPUS_NAME albo basename CORPUS_HOST_PATH) - w kontenerze korpus jest zawsze
zamontowany jako /data. `fingerprint` (SHA-256 rekordów i bajtów mediów) wiąże cechy z wersją
korpusu.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".mp4", ".webm", ".mov", ".mkv"}
TEXT_EXT = {".txt"}
MODALITY_FIELD = {"image": "image_path", "text": "text", "audio": "audio_path"}


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
    audio_field: str = "audio_path"                # pole źródłowe nagrania: audio_path | video_path
    missing: dict = field(default_factory=dict)   # modality -> przyczyna (plik zadeklarowany, ale niedostępny)

    @property
    def ref(self) -> str:
        r = self.record
        return r.get("source", {}).get("ad_ref") or r.get("image_path") or r.get("audio_path") or r.get("video_path") or ""


@dataclass
class Item:
    ad_id: str
    origin_id: str
    source_field: str               # pole Ad lub pochodne: "image_path", "text", "ocr.text@..."
    modality: str                   # image | text | audio
    path: str | None = None
    text: str | None = None
    ref: str = ""                   # ad_ref / ścieżka względna - do czytelnych etykiet
    source_value: str | None = None  # wartość pola źródłowego (ścieżka względna pliku)

    @property
    def key(self) -> str:
        return f"{self.ad_id}|{self.source_field}"

    @property
    def label(self) -> str:
        ref = f" ({self.ref})" if self.ref else ""
        return f"{self.ad_id}{ref} [{self.source_field}]"


@dataclass
class Corpus:
    root: Path
    dataset_id: str
    mode: str                       # v0 | files
    ads: list[Ad]
    report: dict = field(default_factory=dict)
    fingerprint: str = ""

    def items(self, modality: str) -> list[Item]:
        out = []
        for a in self.ads:
            if modality == "image" and a.image:
                out.append(Item(a.ad_id, a.image_origin, "image_path", "image", path=str(a.image),
                                ref=a.ref, source_value=a.record.get("image_path")))
            elif modality == "text" and a.text:
                out.append(Item(a.ad_id, a.text_origin, "text", "text", text=a.text, ref=a.ref))
            elif modality == "audio" and a.audio:
                out.append(Item(a.ad_id, a.audio_origin, a.audio_field, "audio", path=str(a.audio),
                                ref=a.ref, source_value=a.record.get(a.audio_field)))
        return out

    def missing_reason(self, ad: Ad, modality: str) -> str:
        return ad.missing.get(modality) or f"no_{modality}_input"


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _jsonl(p: Path, errors: list) -> list[tuple[int, dict]]:
    rows = []
    if not p.exists():
        return rows
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append((i, json.loads(line)))
        except json.JSONDecodeError as e:
            errors.append({"file": p.name, "line": i, "error": f"invalid_json: {e}"})
    return rows


def _host_name(root: Path) -> str:
    name = os.environ.get("CORPUS_NAME") or Path(os.environ.get("CORPUS_HOST_PATH", "")).name
    return name or root.name


def _confined(root: Path, rel: str) -> Path | None:
    """Ścieżka mediów wewnątrz katalogu korpusu (kontrakt: „Błędy i czas”), inaczej None."""
    if not rel or os.path.isabs(rel):
        return None
    try:
        (root / rel).resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return root / rel


def _fingerprint(ads: list[Ad]) -> str:
    h = hashlib.sha256()
    for a in sorted(ads, key=lambda x: x.ad_id):
        h.update(json.dumps(a.record, sort_keys=True, ensure_ascii=False).encode())
        for p in (a.image, a.audio):
            if p is not None:
                h.update(_sha256(p).encode())
    return h.hexdigest()[:16]


def _load_v0(root: Path) -> Corpus:
    errors: list = []
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8")) \
        if (root / "manifest.json").exists() else {}
    shots = {r["ad_id"]: r for _, r in _jsonl(root / "observations" / "screenshots.jsonl", errors)
             if "ad_id" in r}
    ads, seen, skipped = [], set(), []
    for line, rec in _jsonl(root / "ads.jsonl", errors):
        ad_id = rec.get("ad_id")
        if not ad_id:
            errors.append({"file": "ads.jsonl", "line": line, "error": "missing_ad_id"})
            continue
        if ad_id in seen:  # ponowny import tego samego ID jest idempotentny
            skipped.append(ad_id)
            continue
        seen.add(ad_id)

        def err(msg):
            errors.append({"file": "ads.jsonl", "line": line, "ad_id": ad_id, "error": msg})

        shot = shots.get(ad_id, {})
        group = rec.get("observation_group") or shot.get("observation_group")
        a = Ad(ad_id, rec)
        a.image_origin = rec.get("image_origin") or group or f"{ad_id}#image_path"
        if rec.get("image_path"):
            p = _confined(root, rec["image_path"])
            if p is None:
                a.missing["image"] = f"path_outside_corpus: {rec['image_path']}"
                err(a.missing["image"])
            elif not p.is_file():
                a.missing["image"] = f"file_not_found: {rec['image_path']}"
                err(a.missing["image"])
            else:
                a.image = p
        for k in ("audio_path", "video_path"):  # rozszerzenie kontraktu (multimedia)
            if rec.get(k):
                p = _confined(root, rec[k])
                if p is None or not p.is_file():
                    a.missing["audio"] = f"{'path_outside_corpus' if p is None else 'file_not_found'}: {rec[k]}"
                    err(a.missing["audio"])
                else:
                    a.audio, a.audio_field = p, k
                    a.audio_origin = rec.get("audio_origin") or f"{ad_id}#{k}"
                break
        if (rec.get("text") or "").strip():
            a.text = rec["text"].strip()
            # domyślnie tekst reklamy z obrazem dziedziczy pochodzenie obrazu
            a.text_origin = rec.get("text_origin") or (
                a.image_origin if rec.get("image_path") else f"{ad_id}#text")
        if not (a.text or rec.get("image_path") or rec.get("landing_url")
                or rec.get("audio_path") or rec.get("video_path")):
            err("no_usable_field")
        ads.append(a)
    ds = manifest.get("dataset_id") or _host_name(root)
    return Corpus(root, ds, "v0", ads,
                  {"errors": errors, "duplicate_ad_ids": skipped,
                   "manifest_schema": manifest.get("schema_version")}, _fingerprint(ads))


def _load_files(root: Path) -> Corpus:
    ads: dict[str, Ad] = {}
    dups, errors = [], []
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
                errors.append({"file": rel, "error": "empty_text"})
                continue
            rec["text"] = txt
            a.text, a.text_origin = txt, f"{ad_id}#text"
        ads[ad_id] = a
    lst = list(ads.values())
    return Corpus(root, _host_name(root), "files", lst,
                  {"duplicate_files": dups, "errors": errors}, _fingerprint(lst))


def load_corpus(root: str | Path) -> Corpus:
    root = Path(root)
    if (root / "ads.jsonl").exists():
        return _load_v0(root)
    return _load_files(root)
