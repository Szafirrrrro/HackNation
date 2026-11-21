"""Read committed bundles and compare individual review occurrences."""
import re
import unicodedata
import json
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urljoin

from .capture import read_json
from .cards import card
from .landing import Document, html_text, structured, library_identity
from .landing_fields import badge, rating_icons
from .sources import PIXEL, clean, digest, network, pixel_from_url


def catalog(store, errors=None):
    records = {}
    for manifest in sorted(Path(store).glob("*/manifest.json")):
        if manifest.parent.name.startswith(".") or manifest.parent.is_symlink():
            continue
        try:
            meta = read_json(manifest)
            if meta["capture_id"] != manifest.parent.name:
                raise ValueError("Niezgodny identyfikator")
            result = artifact_path(manifest.parent, meta["result"])
            records[meta["capture_id"]] = (manifest.parent, meta, read_json(result))
        except (ValueError, OSError, KeyError) as exc:
            if errors is None:
                raise
            errors.append(f"{manifest.parent.name} ({type(exc).__name__})")
    return records


def normalize(text):
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))


def matches(records, selected):
    left = records[selected][2]["opinions"]
    for other, (_, _, result) in records.items():
        if records[other][1].get("observation_id", other) == records[selected][1].get("observation_id", selected):
            continue
        for first in left:
            a = normalize(first["text"])
            if not a:
                continue
            for second in result["opinions"]:
                b = normalize(second["text"])
                if a == b:
                    yield first, other, second, 1.0
                elif min(len(a), len(b)) >= 20:
                    model = SequenceMatcher(None, a, b, autojunk=False)
                    if model.quick_ratio() >= .88:
                        score = model.ratio()
                        if score >= .88:
                            yield first, other, second, score


def artifact_path(folder, artifact):
    path = (folder / artifact["path"]).resolve()
    if not path.is_relative_to(folder.resolve()) or digest(path) != artifact["sha256"]:
        raise ValueError("Dowód nie zgadza się z manifestem")
    return path


def pointer_value(obj, pointer):
    for raw in pointer.split("/")[1:]:
        key = raw.replace("~1", "/").replace("~0", "~")
        obj = obj[int(key) if isinstance(obj, list) else key]
    return obj


def preview(folder, meta, ref, excerpt=None):
    item = next((item for item in meta["artifacts"] if item["path"] == ref["file"] and item["sha256"] == ref["origin_id"]), None)
    if not item:
        raise ValueError("Brak dowodu w manifeście")
    path = artifact_path(folder, item)
    loc = ref["locator"]
    if item["role"] == "source_record" and "record" in loc:
        record = loc["record"]
        if record.startswith("element:"):
            node = Document(html_text(path)).nodes[int(record.split(":")[1]) - 1]
            return "text", node.words(True)
        if record.startswith("line:"):
            line = int(record.split(":")[1])
            with path.open(encoding="utf-8-sig") as stream:
                obj = next(json.loads(raw) for number, raw in enumerate(stream, 1) if number == line)
        else:
            obj = pointer_value(read_json(path), record)
        public_fields = ("ad_id", "text", "meta_ad_library_id", "nazwa_na_karcie", "daty_jak_na_karcie",
                         "obserwacja", "status", "page_name", "id", "removal_notice", "tekst", "komunikat_platformy")
        return "json", {k: clean(obj[k]) for k in public_fields if isinstance(obj.get(k), (str, int))}
    if "element" in loc:
        doc = Document(html_text(path))
        if "text_parts" in loc:
            values = [(doc.nodes[i-1] if i else doc.root).parts[j] for i, j in loc["text_parts"]]
            if not all(isinstance(value, str) for value in values):
                raise ValueError("Niepoprawne odwołanie do tekstu dokumentu")
            return "text", clean("".join(values))
        node = doc.nodes[loc["element"] - 1]
        if node.tag == "svg" and "rating" in node.keys:
            icons = rating_icons(node)
            if icons:
                return "json", icons
        aggregate = badge(node, lambda n: {"element": n.index})
        if aggregate:
            return "json", {k: aggregate[k] for k in ("rating", "count", "value")}
        if item["role"] == "source_record" and loc.get("attribute") in {"href", "data-url", "data-href"}:
            attr = loc["attribute"]
            return "json", {"przycisk": clean(node.words() or node.attr("aria-label")),
                            attr: clean(urljoin("https://www.facebook.com/", node.attr(attr)))}
        if "attribute" in loc and library_identity(node):
            return "json", {"provider": "meta-ad-library", "ad_ref": library_identity(node)[1],
                            "source": clean(node.attr(loc["attribute"]))}
        if "json_pointer" in loc:
            obj = pointer_value(json.loads("".join(node.parts)), loc["json_pointer"])
            selected = {"products": [], "prices": [], "opinions": []}
            structured(obj, ref, selected)
            for opinion in selected["opinions"]:
                opinion.pop("source_kind")
            return "json", {k: v for k,v in selected.items() if v}
        if "offset" in loc:
            source = "".join(node.parts)
        elif node.tag in {"img", "script"} and pixel_from_url(node.attr("src")):
            return "json", pixel_from_url(node.attr("src"))
        else:
            value = node.words(True)
            if not value and node.attr("itemprop").lower() in {"price", "pricecurrency", "name"}:
                value = clean(node.attr("content"))
            return "text", value
    elif "offset" in loc:
        source = html_text(path)
    if "offset" in loc:
        fragment = source[loc["offset"]:loc["end"]]
        if not PIXEL.fullmatch(fragment):
            raise ValueError("Niezgodna lokalizacja inicjalizacji piksela")
        return "text", fragment
    if "pointer" in loc:
        obj = read_json(path)
        value = pointer_value(obj, loc["pointer"])
        if isinstance(value, (int, float, bool, str)):
            return "text", clean(value)
        _, _, opinions = card(obj, item)
        row = next(row for row in opinions if row["evidence"] == ref)
        return "json", {key:row[key] for key in ("text", "signature", "visible_time", "rating", "reactions")}
    if "entry" in loc:
        return "json", network(path, item)["entries"][loc["entry"]]
    if "bbox" in loc:
        from PIL import Image
        with Image.open(path) as im:
            return "image", im.crop(tuple(loc["bbox"]))
    if "start" in loc:
        return item["role"], path
    raise ValueError("Nieobsługiwana lokalizacja dowodu")
