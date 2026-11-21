"""Offline evidence locators and allowlisted infrastructure fields."""
import hashlib
import json
import re
from collections import defaultdict
from urllib.parse import parse_qs, unquote, urljoin, urlsplit


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def address(value):
    """Keep only a host and public-looking path components."""
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        parts = []
        redact_next = False
        for part in parsed.path.split("/"):
            decoded = unquote(part)
            private = (redact_next or "@" in decoded or "=" in decoded or ";" in decoded
                       or re.search(r"[A-Za-z0-9_-]{30,}|\+?\d{9,}", decoded))
            parts.append("[…]" if private else part)
            redact_next = bool(re.fullmatch(r"[\w.-]*token|auth|session(?:id)?|user|email|phone|password|(?:api[_-]?)?key|reset", decoded, re.I))
        return {"host": parsed.hostname, "path": "/".join(parts) or "/"}
    except ValueError:
        return None


def safe_url(value):
    parsed = address(value)
    return parsed["host"] + parsed["path"] if parsed else "[adres]"


PRIVATE_FIELD = re.compile(
    r"""(?ix)(?P<label>["']?(?:[\w.-]*token|api[_-]?key|(?:client[_-]?)?secret|session(?:id)?|password|cookie|authorization)["']?\s*[:=]\s*)"""
    r'''(?:\[…\]|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;&}\]]+)'''
)


def clean(value):
    value = re.sub(r"(?im)\b(?:set-cookie|cookie|authorization)\s*:\s*[^\r\n]*", "[…]", str(value))
    value = re.sub(r"(?i)\b(bearer\s+)[\w.+/=-]+", r"\1[…]", value)
    value = PRIVATE_FIELD.sub(r"\g<label>[…]", value)
    value = re.sub(r"https?://[^\s<>\"']+", lambda m: safe_url(m[0]), value, flags=re.I)
    return " ".join(value.split())


def evidence(artifact, **location):
    return {"file": artifact["path"], "origin_id": artifact["sha256"], "locator": location}


def fact(value, ref):
    return {"value": value, "evidence": ref}


def pixel_from_url(value):
    target = address(value)
    if not target:
        return []
    url = urlsplit(value)
    query = parse_qs(url.query)
    hits = []
    if target["host"] in {"www.facebook.com", "facebook.com"} and url.path.rstrip("/") == "/tr":
        hits.extend(("meta", v) for v in query.get("id", []) if v.isdigit())
    match = re.fullmatch(r"/signals/config/(\d+)/?", url.path)
    if target["host"] == "connect.facebook.net" and match:
        hits.append(("meta", match[1]))
    if target["host"] == "analytics.tiktok.com":
        hits.extend(("tiktok", v) for v in query.get("sdkid", []) if re.fullmatch(r"[A-Z0-9]{8,32}", v))
    return hits


PIXEL = re.compile(r"""(?P<engine>fbq|ttq\.load)\s*\(\s*(?:['"]init['"]\s*,\s*)?['"](?P<id>[A-Za-z0-9]{6,32})['"]""")


def script_pixels(source, artifact):
    return [fact({"provider": "meta" if m["engine"] == "fbq" else "tiktok", "id": m["id"]},
                 evidence(artifact, offset=m.start(), end=m.end()))
            for m in PIXEL.finditer(source) if m["engine"] != "fbq" or m["id"].isdigit()]


def network(path, artifact):
    entries = json.loads(path.read_text(encoding="utf-8-sig"))["log"]["entries"]
    if not isinstance(entries, list):
        raise ValueError("Niepoprawna lista wpisów HAR")
    rows, pixels = [], []
    resources = defaultdict(list)
    for index, entry in enumerate(entries):
        request = entry.get("request", {})
        response = entry.get("response", {})
        url = request.get("url", "")
        target = address(url)
        ref = evidence(artifact, entry=index)
        row = {"index": index, "evidence": ref, "address": target, "status": response.get("status")}
        if isinstance(row["status"], int) and 300 <= row["status"] < 400:
            dest = response.get("redirectURL") or next((h.get("value") for h in response.get("headers", [])
                                                        if h.get("name", "").lower() == "location"), None)
            if dest:
                row["redirect"] = address(urljoin(url, dest))
        rows.append(row)
        if target:
            resources[(target["host"], urlsplit(url).path or "/")].append(row)
        for provider, pixel in pixel_from_url(url):
            value = {"provider": provider, "id": pixel}
            pixels.append(fact(value, ref))
            row.setdefault("pixels", []).append(value)
    repeats = [{**group[0]["address"], "evidence": [row["evidence"] for row in group]}
               for group in resources.values() if len(group) > 1]
    return {"entries": rows, "pixels": pixels, "repeated_resources": repeats}
