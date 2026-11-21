"""Wspólny interfejs ekstraktorów + zapis cech w formacie kontraktu.

Feature (docs/DATA_CONTRACT.md: typ obiektu i ID, rodzina, pole, wartość, origin_id,
lokalizacja źródła, wersja ekstraktora):
    object_type ("ad"), ad_id, family, field, value, origin_id, source_ref, method_version
+ pola pomocnicze tej warstwy:
    status ("ok" | "unavailable"), reason, source_field, extractor, use_case

Wektory (embeddingi) nie są wpisywane do JSONL: `value` zawiera
{"vector": "vectors/<slug>/<field>.npy", "row": i, "dim": d, "norm": "l2"|None, ...}.

method_version = <use_case>/<nazwa>@<wersja>[+<rewizja wag HF>][#p<hash parametrów>],
więc zmiana wag, promptów, etykiet lub progów zmienia wersję metody.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA = "features-v1"
MAX_PIXELS = 60_000_000
MAX_BYTES = 50 * 2**20
HF_HUB = Path(os.environ.get("HF_HOME", "/models/hf")) / "hub"


if __package__:  # import jako pakiet (testy z katalogu repozytorium)
    from .errors import Unavailable  # noqa: F401
else:            # kontener: moduły z /app/common na sys.path
    from errors import Unavailable  # noqa: F401 - re-eksport dla models.py


@dataclass
class Out:
    field: str
    value: Any = None                # JSON-able, np.ndarray, dict z "vector": ndarray albo "array": ndarray
    family: str | None = None        # nadpisuje rodzinę ekstraktora
    reason: str | None = None        # ustawione = to pole jest niedostępne (status unavailable)


def hf_revision(repo_id: str) -> str:
    """Rewizja wag pobranych do obrazu (refs/main w cache HF), skrócona do 10 znaków."""
    ref = HF_HUB / f"models--{repo_id.replace('/', '--')}" / "refs" / "main"
    try:
        return ref.read_text().strip()[:10]
    except OSError:
        return "unknown"


def params_hash(params: dict) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:8]


class Extractor:
    name = ""            # czytelna nazwa modelu
    use_case = ""
    family = "visual"    # text | visual | infrastructure | audio (kontrakt)
    modality = "image"   # image | text | audio
    primary_field = ""   # pole raportowane jako "unavailable", gdy brak wejścia / błąd całego wejścia
    version = ""         # wersja modelu/pakietu (część method_version)
    hf_repo = ""         # repo HF z wagami -> rewizja w method_version
    params: dict = {}    # prompty, etykiety, progi -> hash w method_version
    license = ""
    notes = ""
    consumes_derived_text = False  # True: przetwarza też ocr.text / asr.text z wcześniejszych ekstrakcji
    # Decyzja zespołu (README, tabela „Który eksperyment…”):
    #   default   - domyślny profil ekstrakcji,
    #   candidate - liczony w profilu eval do porównania z domyślnym,
    #   deferred  - odłożony (tylko PROFILE=all lub jawne MODELS),
    #   excluded  - odłożony i wyłączony z grupowania (grouping=False).
    stage = "default"
    decision = ""        # krótkie uzasadnienie statusu (trafia do runs/*.json)

    @property
    def grouping(self) -> bool:
        return self.stage != "excluded"

    @property
    def slug(self) -> str:
        return re.sub(r"[^a-zA-Z0-9]+", "_", f"{self.use_case}.{self.name}").strip("_").lower()

    @property
    def method_version(self) -> str:
        mv = f"{self.use_case}/{self.name}@{self.version}"
        if self.hf_repo:
            mv += f"+{hf_revision(self.hf_repo)}"
        if self.params:
            mv += f"#p{params_hash(self.params)}"
        return mv

    def load(self, threads: int) -> None:
        raise NotImplementedError

    def extract(self, item) -> list[Out]:
        raise NotImplementedError

    def summarize(self, outs: list[Out]) -> Any:
        """Krótki podgląd wyniku do raportu benchmarku (bez wektorów)."""
        res = {}
        for o in outs:
            v = o.value
            if o.reason:
                v = {"unavailable": o.reason}
            elif isinstance(v, np.ndarray):
                v = f"<vec {v.shape[-1]}>"
            elif isinstance(v, dict) and isinstance(v.get("vector"), np.ndarray):
                v = {k: x for k, x in v.items() if k != "vector"} | {"vector": f"<{v['vector'].shape[-1]}d>"}
            elif isinstance(v, dict) and isinstance(v.get("array"), np.ndarray):
                v = {k: x for k, x in v.items() if k != "array"} | {"array": f"<{list(v['array'].shape)}>"}
            if o.field in res:
                res[o.field] = res[o.field] if isinstance(res[o.field], list) else [res[o.field]]
                res[o.field].append(v)
            else:
                res[o.field] = v
        return res


# ------------------------------------------------------------------ helpers --
def load_rgb(path: str):
    """PIL RGB z walidacją formatu i rozmiaru (kontrakt: importer sprawdza format i rozmiar)."""
    from PIL import Image, UnidentifiedImageError
    try:
        if os.path.getsize(path) > MAX_BYTES:
            raise Unavailable(f"image_too_large: > {MAX_BYTES // 2**20} MB")
        with Image.open(path) as im:
            if im.size[0] * im.size[1] > MAX_PIXELS:
                raise Unavailable(f"image_too_large: {im.size[0]}x{im.size[1]} px")
            im.verify()
        im = Image.open(path)
        im.load()
        return im.convert("RGB")
    except FileNotFoundError:
        raise Unavailable("file_not_found")
    except Image.DecompressionBombError as e:
        raise Unavailable(f"image_too_large: {e}")
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as e:
        raise Unavailable(f"unreadable_image: {e}")


def load_bgr(path: str):
    """OpenCV BGR (przez PIL, żeby obsłużyć webp/gif i walidację)."""
    return np.ascontiguousarray(np.asarray(load_rgb(path))[:, :, ::-1])


def l2(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32).reshape(-1)
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


# Domeny z OCR to heurystyka: tylko TLD z listy (krajowe + popularne w kampaniach scamowych,
# skracacze jak bit.ly, .ai), żeby "tutaj.Sprawdz", "dokument.pdf" czy "dr.house" nie stawały się
# śladem infrastruktury. Domena z adresu e-mail (kontakt@promo-pl.online) też jest wykrywana.
# Kompromis fałszywe trafienia / pominięcia nie był mierzony.
TLDS = set("""
pl com net org info biz eu io co me app dev online site shop store top click xyz live ai ly
gg to sh in su mx br ca au nz za tr il ae sa cn jp kr vn th id my ph sg hk tw ar cl
life today world news club pro fun space website link icu buzz sbs cfd cyou bond lol
best vip tech cloud host press blog page win bid trade ltd group money finance cash
de uk us ru ua cz sk lt lv ee at ch fr it es nl be se no dk fi hu ro bg gr pt ie tv cc ws
""".split())
# TLD będące też krótkimi polskimi słowami: bez schematu, www. lub ścieżki "teraz.to" po zgubionej
# przez OCR spacji to zdanie, nie domena.
AMBIGUOUS_TLDS = {"to", "co", "my", "za", "in", "id", "me", "no", "sa", "do"}
URL_RE = re.compile(
    r"(?<![\w.-])(https?://)?(www\.)?"
    r"((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+([a-z]{2,24}))\b(/[^\s\"'<>]*)?", re.I)


def find_urls(text: str) -> list[str]:
    """Domeny/URL-e z tekstu (np. OCR), znormalizowane do małych liter hosta."""
    out = []
    for m in URL_RE.finditer(text or ""):
        scheme, www, host, tld, path = m.groups()
        tld = tld.lower()
        if tld not in TLDS:
            continue
        if tld in AMBIGUOUS_TLDS and not (scheme or www or (path and len(path) > 1)):
            continue
        out.append(host.lower() + (path or ""))
    return sorted(set(out))


def _json_default(o):
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Path):
        return str(o)
    raise TypeError(f"{type(o).__name__} nie jest serializowalny")


def _atomic_write(path: Path, text: str):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# ------------------------------------------------------------------- writer --
class FeatureWriter:
    """Zapisuje wynik jednego ekstraktora do <out>/features/<slug>.jsonl,
    wektory do <out>/vectors/<slug>/<field>.npy i metadane do <out>/runs/<slug>.json.
    Ponowne uruchomienie nadpisuje tylko pliki danego ekstraktora (idempotentne)."""

    def __init__(self, out_dir: Path, ext: Extractor):
        self.out, self.ext = out_dir, ext
        self.method_version = ext.method_version
        self.rows: list[dict] = []
        self.vecs: dict[str, list[np.ndarray]] = {}
        self.arrays: dict[str, list[np.ndarray]] = {}
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
            if o.reason:
                self.rows.append(self._row(item.ad_id, item.origin_id, item, o.field, None,
                                           o.family, "unavailable", o.reason))
                continue
            v = o.value
            if isinstance(v, np.ndarray):
                v = self._vec_ref(o.field, v, {})
            elif isinstance(v, dict) and isinstance(v.get("vector"), np.ndarray):
                v = self._vec_ref(o.field, v["vector"], {k: x for k, x in v.items() if k != "vector"})
            elif isinstance(v, dict) and isinstance(v.get("array"), np.ndarray):
                lst = self.arrays.setdefault(o.field, [])
                lst.append(v["array"])
                v = {"array": f"arrays/{self.ext.slug}/{o.field}.npz", "key": f"r{len(lst) - 1}",
                     "shape": list(v["array"].shape), "dtype": str(v["array"].dtype),
                     **{k: x for k, x in v.items() if k != "array"}}
            self.rows.append(self._row(item.ad_id, item.origin_id, item, o.field, v,
                                       o.family, "ok", None))

    def unavailable(self, ad_id, origin_id, item, reason):
        self.rows.append(self._row(ad_id, origin_id, item, self.ext.primary_field,
                                   None, None, "unavailable", reason))

    def _row(self, ad_id, origin_id, item, field, value, family, status, reason):
        source_field = item.source_field if item is not None else None
        source_ref = None
        if item is not None:
            source_ref = {"field": source_field.split("@", 1)[0]}
            if getattr(item, "source_value", None):
                source_ref["value"] = item.source_value
            if "@" in source_field:
                source_ref["method_version"] = source_field.split("@", 1)[1]
        return {"object_type": "ad", "ad_id": ad_id, "family": family or self.ext.family,
                "field": field, "value": value, "origin_id": origin_id, "source_ref": source_ref,
                "method_version": self.method_version, "status": status, "reason": reason,
                "source_field": source_field, "extractor": self.ext.name,
                "use_case": self.ext.use_case}

    def close(self, meta: dict):
        slug = self.ext.slug
        (self.out / "features").mkdir(parents=True, exist_ok=True)
        (self.out / "runs").mkdir(parents=True, exist_ok=True)
        # serializacja przed zapisem czegokolwiek: błąd typu nie zostawia połowicznego wyniku
        lines = "".join(json.dumps(r, ensure_ascii=False, default=_json_default) + "\n"
                        for r in self.rows)
        vdir = self.out / "vectors" / slug
        if vdir.exists():
            for f in vdir.glob("*.npy"):
                f.unlink()
        for field, lst in self.vecs.items():
            vdir.mkdir(parents=True, exist_ok=True)
            np.save(vdir / f"{field}.npy", np.stack(lst))
        adir = self.out / "arrays" / slug
        if adir.exists():
            for f in adir.glob("*.npz"):
                f.unlink()
        for field, lst in self.arrays.items():
            adir.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(adir / f"{field}.npz", **{f"r{i}": a for i, a in enumerate(lst)})
        _atomic_write(self.out / "features" / f"{slug}.jsonl", lines)
        ok = sum(r["status"] == "ok" for r in self.rows)
        meta = {"schema": SCHEMA, "extractor": self.ext.name, "slug": slug,
                "use_case": self.ext.use_case, "method_version": self.method_version,
                "family": self.ext.family, "primary_field": self.ext.primary_field,
                "params": self.ext.params, "license": self.ext.license, "notes": self.ext.notes,
                "stage": self.ext.stage, "grouping": self.ext.grouping, "decision": self.ext.decision,
                "image_id": os.environ.get("IMAGE_ID"), "code_rev": os.environ.get("GIT_REV"),
                "duration_s": round(time.time() - self.t0, 2),
                "rows_ok": ok, "rows_unavailable": len(self.rows) - ok,
                "vector_fields": {k: [len(v), int(v[0].shape[0])] for k, v in self.vecs.items()},
                **meta}
        _atomic_write(self.out / "runs" / f"{slug}.json",
                      json.dumps(meta, ensure_ascii=False, indent=2, default=_json_default))
        return meta
