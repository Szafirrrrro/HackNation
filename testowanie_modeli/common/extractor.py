"""Wspólny interfejs ekstraktorów + zapis cech w formacie kontraktu.

Feature (docs/DATA_CONTRACT.md):
    ad_id, family, field, value, origin_id, method_version
+ pola pomocnicze tej warstwy:
    status ("ok" | "unavailable"), reason, source_field, extractor, use_case

Wektory (embeddingi) nie są wpisywane do JSONL: `value` zawiera
{"vector": "vectors/<slug>/<field>.npy", "row": i, "dim": d, "norm": "l2"|None, ...}.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA = "features-v1"
MAX_PIXELS = 60_000_000


class Unavailable(Exception):
    """Wejście nie nadaje się do analizy - powód trafia do Feature.reason."""


@dataclass
class Out:
    field: str
    value: Any                       # JSON-able, np.ndarray albo dict z kluczem "vector": ndarray
    family: str | None = None        # nadpisuje rodzinę ekstraktora


class Extractor:
    name = ""            # czytelna nazwa modelu
    use_case = ""
    family = "visual"    # text | visual | infrastructure (kontrakt)
    modality = "image"   # image | text | audio
    primary_field = ""   # pole raportowane jako "unavailable", gdy brak wejścia
    version = ""         # wersja modelu/pakietu (część method_version)
    license = ""
    notes = ""
    consumes_derived_text = False  # True: przetwarza też ocr.text / asr.text z wcześniejszych ekstrakcji

    @property
    def slug(self) -> str:
        return re.sub(r"[^a-zA-Z0-9]+", "_", f"{self.use_case}.{self.name}").strip("_").lower()

    @property
    def method_version(self) -> str:
        return f"{self.use_case}/{self.name}@{self.version}"

    def load(self, threads: int) -> None:
        raise NotImplementedError

    def extract(self, item) -> list[Out]:
        raise NotImplementedError

    def summarize(self, outs: list[Out]) -> Any:
        """Krótki podgląd wyniku do raportu benchmarku (bez wektorów)."""
        res = {}
        for o in outs:
            v = o.value
            if isinstance(v, np.ndarray):
                v = f"<vec {v.shape[-1]}>"
            elif isinstance(v, dict) and isinstance(v.get("vector"), np.ndarray):
                v = {k: x for k, x in v.items() if k != "vector"} | {"vector": f"<{v['vector'].shape[-1]}d>"}
            if o.field in res:
                res[o.field] = res[o.field] if isinstance(res[o.field], list) else [res[o.field]]
                res[o.field].append(v)
            else:
                res[o.field] = v
        return res


# ------------------------------------------------------------------ helpers --
def load_rgb(path: str):
    """PIL RGB z walidacją (uszkodzony / za duży obraz -> Unavailable)."""
    from PIL import Image, UnidentifiedImageError
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(path) as im:
            im.verify()
        im = Image.open(path)
        im.load()
        return im.convert("RGB")
    except FileNotFoundError:
        raise Unavailable("file_not_found")
    except Image.DecompressionBombError:
        raise Unavailable("image_too_large")
    except (UnidentifiedImageError, OSError, SyntaxError) as e:
        raise Unavailable(f"unreadable_image: {e}")


def load_bgr(path: str):
    """OpenCV BGR (przez PIL, żeby obsłużyć webp/gif i walidację)."""
    return np.ascontiguousarray(np.asarray(load_rgb(path))[:, :, ::-1])


def l2(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32).reshape(-1)
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


URL_RE = re.compile(
    r"(?:(?:https?://)?(?:www\.)?)"
    r"((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24})(/[^\s\"'<>]*)?", re.I)


def find_urls(text: str) -> list[str]:
    """Domeny/URL-e z tekstu (np. OCR). Heurystyka: wymagamy TLD z liter."""
    out = []
    for m in URL_RE.finditer(text or ""):
        host = m.group(1).lower().rstrip(".")
        if host.split(".")[-1] in {"jpg", "png", "gif", "jpeg", "webp"}:
            continue
        out.append(host + (m.group(2) or ""))
    return sorted(set(out))


# ------------------------------------------------------------------- writer --
class FeatureWriter:
    """Zapisuje wynik jednego ekstraktora do <out>/features/<slug>.jsonl,
    wektory do <out>/vectors/<slug>/<field>.npy i metadane do <out>/runs/<slug>.json.
    Ponowne uruchomienie nadpisuje tylko pliki danego ekstraktora (idempotentne)."""

    def __init__(self, out_dir: Path, ext: Extractor):
        self.out, self.ext = out_dir, ext
        self.rows: list[dict] = []
        self.vecs: dict[str, list[np.ndarray]] = {}
        self.t0 = time.time()

    def _vec_ref(self, field: str, vec: np.ndarray, extra: dict) -> dict:
        lst = self.vecs.setdefault(field, [])
        v = np.asarray(vec, dtype=np.float32).reshape(-1)
        lst.append(v)
        n = float(np.linalg.norm(v))
        return {"vector": f"vectors/{self.ext.slug}/{field}.npy", "row": len(lst) - 1,
                "dim": int(v.shape[0]), "norm": "l2" if abs(n - 1) < 1e-3 else None, **extra}

    def add(self, item, outs: list[Out]):
        for o in outs:
            v = o.value
            if isinstance(v, np.ndarray):
                v = self._vec_ref(o.field, v, {})
            elif isinstance(v, dict) and isinstance(v.get("vector"), np.ndarray):
                v = self._vec_ref(o.field, v["vector"], {k: x for k, x in v.items() if k != "vector"})
            self.rows.append(self._row(item.ad_id, item.origin_id, item.source_field,
                                       o.field, v, o.family, "ok", None))

    def unavailable(self, ad_id, origin_id, source_field, reason):
        self.rows.append(self._row(ad_id, origin_id, source_field, self.ext.primary_field,
                                   None, None, "unavailable", reason))

    def _row(self, ad_id, origin_id, source_field, field, value, family, status, reason):
        return {"ad_id": ad_id, "family": family or self.ext.family, "field": field,
                "value": value, "origin_id": origin_id,
                "method_version": self.ext.method_version, "status": status, "reason": reason,
                "source_field": source_field, "extractor": self.ext.name,
                "use_case": self.ext.use_case}

    def close(self, meta: dict):
        slug = self.ext.slug
        (self.out / "features").mkdir(parents=True, exist_ok=True)
        (self.out / "runs").mkdir(parents=True, exist_ok=True)
        vdir = self.out / "vectors" / slug
        if vdir.exists():
            for f in vdir.glob("*.npy"):
                f.unlink()
        for field, lst in self.vecs.items():
            vdir.mkdir(parents=True, exist_ok=True)
            np.save(vdir / f"{field}.npy", np.stack(lst))
        with (self.out / "features" / f"{slug}.jsonl").open("w", encoding="utf-8") as f:
            for r in self.rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        ok = sum(r["status"] == "ok" for r in self.rows)
        meta = {"schema": SCHEMA, "extractor": self.ext.name, "slug": slug,
                "use_case": self.ext.use_case, "method_version": self.ext.method_version,
                "family": self.ext.family, "license": self.ext.license, "notes": self.ext.notes,
                "duration_s": round(time.time() - self.t0, 2),
                "rows_ok": ok, "rows_unavailable": len(self.rows) - ok,
                "vector_fields": {k: [len(v), int(v[0].shape[0])] for k, v in self.vecs.items()},
                **meta}
        (self.out / "runs" / f"{slug}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return meta
