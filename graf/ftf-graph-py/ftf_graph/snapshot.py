"""Offline PageCapture extraction. Never executes page code or loads model weights."""
from __future__ import annotations

import ast
import base64
import hashlib
import io
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin as _urljoin, urlsplit as _urlsplit, urlunsplit

MAX_FILE = 32 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
VERSION = "snapshot-v1"


def urlsplit(value):
    try:
        return _urlsplit(value)
    except (ValueError, TypeError):
        return _urlsplit("")


def urljoin(base, value):
    try:
        return _urljoin(base, value)
    except (ValueError, TypeError):
        return ""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_url(value):
    """Keep host/path, drop credentials, query and fragment (may contain sessions)."""
    try:
        p = urlsplit(value)
        if p.scheme not in ("http", "https") or not p.hostname:
            return None
        return urlunsplit((p.scheme, p.hostname + (f":{p.port}" if p.port else ""), p.path, "", ""))
    except (ValueError, TypeError):
        return None


def obj(value):
    return value if isinstance(value, dict) else {}


def seq(value):
    return value if isinstance(value, list) else []


@dataclass
class Resource:
    data: bytes
    source: dict
    url: str = ""
    mime: str = ""


class Document(HTMLParser):
    """Structural normalization v1; explicit hidden only, no CSS visibility engine."""
    VOID = set("area base br col embed hr img input link meta param source track wbr".split())

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.structure, self.text, self.hidden, self.scripts = [], [], [], []
        self.refs, self.forms, self.links, self.icons = [], [], [], []
        self.stack = []
        self.script = None
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        hidden = ("hidden" in a or a.get("aria-hidden", "").lower() == "true" or
                  bool(re.search(r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\s*(?:!important)?\s*(?:;|$)", a.get("style", ""), re.I)))
        hidden = hidden or any(x[1] for x in self.stack)
        # Only semantic, bounded attribute values: no IDs, classes, URLs or text.
        features = {k: a[k] for k in ("type", "role", "method") if a.get(k) in {
            "text", "email", "tel", "password", "submit", "button", "checkbox", "radio",
            "hidden", "search", "number", "get", "post", "GET", "POST", "navigation", "main", "form"}}
        self.structure.append(["open", tag, sorted(features.items())])
        if tag == "script":
            self.script = [a.get("src"), []]
        if tag == "form":
            self.forms.append(a.get("action", ""))
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag == "link" and "icon" in a.get("rel", "").lower():
            if a.get("href"):
                self.icons.append(a["href"])
        for key in ("src", "href"):
            if a.get(key):
                self.refs.append(a[key])
        if tag not in self.VOID:
            self.stack.append((tag, hidden))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "script" and self.script is not None:
            self.scripts.append((self.script[0], "".join(self.script[1])))
            self.script = None
        self.structure.append(["close", tag])
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.script is not None:
            self.script[1].append(data)
        if any(t in ("script", "style", "noscript", "template") for t, _ in self.stack):
            return
        value = " ".join(data.split())
        if value:
            (self.hidden if any(h for _, h in self.stack) else self.text).append(value)


def literal_config(text):
    """Parse a JSON/JS literal subset after window.aio=, reject expressions/functions."""
    found = re.search(r"\bwindow\.aio\s*=\s*", text)
    if not found:
        return None
    # JSON.parse of a literal string is data decoding, not execution of page code.
    encoded = re.match(r"JSON\.parse\(\s*", text[found.end():])
    if encoded:
        position = found.end() + encoded.end()
        m = re.match(r'''("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')''', text[position:])
        if not m:
            raise ValueError("JSON.parse requires a string literal")
        raw = m[0]
        try:
            decoded = json.loads(raw) if raw.startswith('"') else ast.literal_eval(raw)
            value = json.loads(decoded)
        except (ValueError, SyntaxError):
            raise ValueError("invalid JSON.parse literal")
        suffix = text[position + len(raw):].lstrip()
        if not suffix.startswith(')') or (suffix[1:].lstrip() and not suffix[1:].lstrip().startswith((';', '</'))):
            raise ValueError("JSON.parse expression suffix")
        return obj(value)
    # Tokenizer consumes only a literal, never evals JS. ast handles quoted strings only.
    token = re.compile(r'''\s*(?:("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|([A-Za-z_$][\w$]*)|(-?\d+(?:\.\d+)?)|([{}\[\]:,]))''')
    pos = found.end()

    def take():
        nonlocal pos
        m = token.match(text, pos)
        if not m:
            raise ValueError("nonliteral")
        pos = m.end()
        if m[1]:
            try:
                return "value", json.loads(m[1])
            except json.JSONDecodeError:
                return "value", ast.literal_eval(m[1])
        if m[2]:
            return "word", m[2]
        if m[3]:
            return "value", json.loads(m[3])
        return "punct", m[4]

    def parse(first=None, depth=0):
        if depth > 40:
            raise ValueError("depth")
        kind, v = first or take()
        if kind == "value":
            return v
        if kind == "word" and v in ("true", "false", "null"):
            return {"true": True, "false": False, "null": None}[v]
        if v not in ("{", "["):
            raise ValueError("expression")
        result = {} if v == "{" else []
        end = "}" if v == "{" else "]"
        item = take()
        while item != ("punct", end):
            if isinstance(result, dict):
                if item[0] not in ("word", "value") or not isinstance(item[1], str):
                    raise ValueError("key")
                if take() != ("punct", ":"):
                    raise ValueError("colon")
                result[item[1]] = parse(depth=depth + 1)
            else:
                result.append(parse(item, depth + 1))
            item = take()
            if item == ("punct", end):
                break
            if item != ("punct", ","):
                raise ValueError("comma")
            item = take()
        return result

    value = parse()
    # Reject assignments whose RHS continues with an operator or property access.
    tail = text[pos:].lstrip()
    if tail and not tail.startswith((";", "</", "//", "/*")):
        raise ValueError("expression suffix")
    return obj(value)


def empty_result(snapshot):
    return {
        "ad_id": None, "provenance": {"source": "provided_snapshot", "url": None,
            "fetched_at": None, "snapshot": snapshot},
        "first_seen": None, "last_seen": None, "status": "unknown",
        "infra": {"redirect_chain": [], "final_domain": None,
            "rdap": {"registered": None, "registrar": None, "nameservers": []},
            "dns": {"ip": None, "asn": None}, "cert": {"id": None, "san": []},
            "favicon": {"mmh3": None, "phash": None}},
        "page": {"tracking_ids": {"meta_pixel": None, "ga": None}, "script_hashes": [],
            "form_endpoint": None, "contacts": {"phones": [], "telegram": [], "crypto": []},
            "dom_template_hash": None, "hidden_text_hash": None},
        "text": {"ad_text": None, "ocr_text": None, "keywords": [], "embedding": None},
        "visual": {"phash": None, "clip_embedding": None}, "faces": [], "extensions": {},
        "extraction": {"schema_version": "1.0", "evidence": {}, "warnings": []}}


def extract_snapshot(folder, *, screenshot=None, extractors=()):
    """Return a JSON-compatible record. screenshot is an explicit relative ad image.

    extractors: already loaded laboratory Extractor instances; no load() calls here.
    Only OCR and CLIP outputs are mapped, per image; no identity inference.
    """
    root = Path(folder).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("snapshot must be a directory")
    out = empty_result(root.name)
    ext, ev, warnings = out["extensions"], out["extraction"]["evidence"], out["extraction"]["warnings"]

    def warn(msg):
        if msg not in warnings:
            warnings.append(msg)

    def evidence(field, source, method=VERSION):
        ev.setdefault(field, []).append({**source, "method": method})

    resources, entries, pages = [], [], []
    total = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file() or root not in path.resolve().parents:
            continue
        rel = path.relative_to(root).as_posix()
        try:
            size = path.stat().st_size
            if size > MAX_FILE or total + size > MAX_TOTAL:
                warn(f"size_limit: {rel}")
                continue
            data = path.read_bytes()
            total += len(data)
        except OSError:
            warn(f"unreadable_file: {rel}")
            continue
        source = {"file": rel}
        if data.lstrip().startswith(b"{"):
            try:
                log = obj(json.loads(data)).get("log")
            except (ValueError, UnicodeError):
                log = None
                if path.suffix.lower() == ".har":
                    warn(f"invalid_har: {rel}")
            if isinstance(log, dict):
                for i, p in enumerate(seq(log.get("pages"))):
                    pages.append((obj(p), {**source, "json_path": f"$.log.pages[{i}]"}))
                for i, entry in enumerate(seq(log.get("entries"))):
                    if not isinstance(entry, dict):
                        warn(f"invalid_har_entry: {rel} #{i}")
                        continue
                    src = {**source, "har_entry": i, "json_path": f"$.log.entries[{i}]"}
                    entries.append((entry, src))
                    content = obj(obj(entry.get("response")).get("content"))
                    body = content.get("text")
                    if isinstance(body, str):
                        try:
                            decoded = base64.b64decode(body, validate=True) if content.get("encoding") == "base64" else body.encode("utf-8")
                            if len(decoded) > MAX_FILE or total + len(decoded) > MAX_TOTAL:
                                raise ValueError("size")
                            total += len(decoded)
                            resources.append(Resource(decoded, {**src, "json_path": src["json_path"] + ".response.content.text"},
                                str(obj(entry.get("request")).get("url", "")), str(content.get("mimeType", ""))))
                        except (ValueError, TypeError):
                            warn(f"invalid_har_body: {rel} #{i}")
                continue
        resources.append(Resource(data, source))

    def is_html(r):
        return "html" in r.mime.lower() or bool(re.search(br"<(?:!doctype\s+html|html|head|body)\b", r.data[:4096], re.I))

    htmls = [r for r in resources if is_html(r)]
    def navigation_entry(e):
        kind = e.get("_resourceType")
        if kind and kind != "document":
            return False
        headers = seq(obj(e.get("request")).get("headers"))
        dest = next((obj(h).get("value") for h in headers if str(obj(h).get("name", "")).lower() == "sec-fetch-dest"), None)
        return dest in (None, "", "document")

    candidates = []
    for e, src in entries:
        req, resp = obj(e.get("request")), obj(e.get("response"))
        headers = {str(h.get("name", "")).lower(): str(h.get("value", "")) for h in seq(req.get("headers")) if isinstance(h, dict)}
        mime = str(obj(resp.get("content")).get("mimeType", ""))
        if navigation_entry(e) and (headers.get("sec-fetch-dest") == "document" or e.get("_resourceType") == "document" or "html" in mime):
            if safe_url(req.get("url")):
                candidates.append((e, src))
    # Explicit navigation wins over generic HTML responses; pageref limits mixing captures.
    explicit = [x for x in candidates if x[0].get("_resourceType") == "document" or any(
        str(obj(h).get("name", "")).lower() == "sec-fetch-dest" and obj(h).get("value") == "document"
        for h in seq(obj(x[0].get("request")).get("headers")))]
    if explicit:
        candidates = explicit
    saved = []
    for r in htmls:
        text = r.data.decode("utf-8", errors="replace")
        m = re.search(r"<!--\s*saved from url=\(\d+\)(https?://.*?)\s*-->", text, re.I)
        if m and safe_url(m[1]):
            saved.append((safe_url(m[1]), r))
    main = None
    if candidates:
        main = candidates[0]
        if saved:
            matches = [x for x in candidates if safe_url(obj(x[0].get("request")).get("url")) == saved[0][0]]
            if len(matches) == 1:
                main = matches[0]
        else:
            page_urls = {safe_url(p.get("title")) for p, _ in pages if safe_url(p.get("title"))}
            page_matches = [x for x in candidates if safe_url(obj(x[0].get("request")).get("url")) in page_urls]
            if len(page_matches) == 1:
                main = page_matches[0]
        # Recover predecessors when the saved HTML identifies the final document.
        predecessor_seen = set()
        while id(main[0]) not in predecessor_seen:
            predecessor_seen.add(id(main[0]))
            target_url = obj(main[0].get("request")).get("url")
            predecessors = []
            for ee, ss in entries:
                if not navigation_entry(ee) or ss["file"] != main[1]["file"] or ss["har_entry"] >= main[1]["har_entry"]:
                    continue
                rr = obj(ee.get("response"))
                target = rr.get("redirectURL") or next((obj(h).get("value") for h in seq(rr.get("headers")) if str(obj(h).get("name", "")).lower() == "location"), None)
                if rr.get("status") in (301, 302, 303, 307, 308) and isinstance(target, str) and urljoin(str(obj(ee.get("request")).get("url", "")), target) == target_url and ee.get("pageref") == main[0].get("pageref"):
                    predecessors.append((ee, ss))
            if len(predecessors) != 1:
                break
            main = predecessors[0]
        # Only follow recorded HTTP redirects with an actual target request in same page.
        chain, used = [], set()
        current = main
        while current and id(current[0]) not in used:
            e, src = current
            used.add(id(e))
            url = str(obj(e.get("request")).get("url", ""))
            chain.append(safe_url(url))
            evidence("infra.redirect_chain", src, "recorded-http-redirect-v1")
            resp = obj(e.get("response"))
            target = resp.get("redirectURL")
            if not target:
                target = next((h.get("value") for h in seq(resp.get("headers")) if isinstance(h, dict) and str(h.get("name", "")).lower() == "location"), None)
            if resp.get("status") not in (301, 302, 303, 307, 308) or not isinstance(target, str) or not target:
                break
            target = urljoin(url, target)
            nxt = [(ee, ss) for ee, ss in entries if navigation_entry(ee) and ss["file"] == src["file"] and ss["har_entry"] > src["har_entry"] and obj(ee.get("request")).get("url") == target and ee.get("pageref") == e.get("pageref") and id(ee) not in used]
            if len(nxt) != 1:
                warn("redirect_target_not_uniquely_recorded")
                break
            current = nxt[0]
        final, final_src = current
        e, src = main
        out["provenance"]["url"] = safe_url(obj(e.get("request")).get("url"))
        timestamp = e.get("startedDateTime")
        if isinstance(timestamp, str):
            from .card import parse_iso
            dt = parse_iso(timestamp)
            if dt and dt.tzinfo:
                out["provenance"]["fetched_at"] = timestamp
            else:
                warn("invalid_main_document_timestamp")
        evidence("provenance.url", {**src, "json_path": src["json_path"] + ".request.url"})
        evidence("provenance.fetched_at", {**src, "json_path": src["json_path"] + ".startedDateTime"})
        out["infra"]["redirect_chain"] = chain if len(chain) > 1 else []
        final_url = safe_url(obj(final.get("request")).get("url"))
        out["infra"]["final_domain"] = urlsplit(final_url).hostname
        evidence("infra.final_domain", {**final_src, "json_path": final_src["json_path"] + ".request.url"}, "URL hostname")
        out["infra"]["dns"]["ip"] = final.get("serverIPAddress") if isinstance(final.get("serverIPAddress"), str) else None
        evidence("infra.dns.ip", {**final_src, "json_path": final_src["json_path"] + ".serverIPAddress"}, "HAR connection IP; not DNS or verified origin")
        ext["historical_http"] = {"status": obj(final.get("response")).get("status"), "observed_at": final.get("startedDateTime")}
        evidence("extensions.historical_http", final_src)
        selected = [r for r in htmls if safe_url(r.url) == final_url and r.data.strip()]
        local_matches = [r for u, r in saved if u == final_url and not r.url]
        document = (local_matches or selected or [None])[0]
        if document is None:
            local_htmls = [r for r in htmls if not r.url]
            if len(local_htmls) == 1:
                document = local_htmls[0]
                warn("local_html_association_unverified: single local HTML used with HAR document")
        if len(candidates) > len(used):
            warn("multiple_document_candidates: selected one navigation; other documents not merged")
    else:
        document = (htmls or [None])[0]
        url = saved[0][0] if saved else next((safe_url(p.get("title")) for p, _ in pages if safe_url(p.get("title"))), None)
        out["provenance"]["url"] = url
        out["infra"]["final_domain"] = urlsplit(url).hostname if url else None
        if saved:
            evidence("provenance.url", saved[0][1].source, "saved-from-url-comment")
        elif url:
            evidence("provenance.url", next(src for p, src in pages if safe_url(p.get("title")) == url), "HAR log.pages.title URL")
        warn("main_document_har_missing: fetched_at unavailable")
    url = out["provenance"]["url"]
    ext["url_candidates"] = []
    for u, r in saved:
        ext["url_candidates"].append({"url": u, "source": r.source, "kind": "saved_from_url"})
        if url and u != url and u != (locals().get("final_url")):
            warn("url_conflict: saved_from_url differs from HAR navigation")
    for p, src in pages:
        u = safe_url(p.get("title"))
        if u:
            ext["url_candidates"].append({"url": u, "source": src, "kind": "log.pages.title"})
            if url and u != url and u != locals().get("final_url"):
                warn("url_conflict: log.pages differs from selected document")

    doc = None
    scripts = []
    if document:
        doc = Document(document.data.decode("utf-8-sig", errors="replace"))
        ext["landing_text"] = " ".join(doc.text)
        evidence("extensions.landing_text", document.source, "HTML text excluding scripts/style and explicit hidden")
        normalized = json.dumps(doc.structure, ensure_ascii=False, separators=(",", ":")).encode()
        out["page"]["dom_template_hash"] = digest(normalized)
        evidence("page.dom_template_hash", document.source, "dom-structure-v1")
        if doc.hidden:
            out["page"]["hidden_text_hash"] = digest(" ".join(doc.hidden).encode())
            evidence("page.hidden_text_hash", document.source, "explicit-hidden-text-v1")
        warn("visibility_partial: hidden/aria-hidden/inline display:none/visibility:hidden only")
    else:
        warn("html_missing: DOM, landing text and contacts not fully analyzed")

    def resolve(ref):
        if ref.startswith(("http:", "https:")) and not safe_url(ref):
            return []
        # Saved browser resource references often differ from original URL paths.
        decoded = unquote(urlsplit(ref).path)
        direct = [r for r in resources if r.source.get("file") == decoded and not r.url]
        if direct:
            return direct
        full = urljoin(locals_base, ref)
        matches = [r for r in resources if r.url and r.url == full]
        if matches:
            return matches
        names = [r for r in resources if not r.url and Path(r.source["file"]).name == Path(decoded).name]
        return names if len(names) == 1 else []

    locals_base = locals().get("final_url") or url or ""
    if doc:
        for i, (src, body) in enumerate(doc.scripts):
            if src:
                resolved = resolve(src)
                if not resolved:
                    warn(f"script_body_missing: script #{i}")
                scripts.extend((r, src) for r in resolved)
            else:
                scripts.append((Resource(body.encode(), {**document.source, "html_script": i}), "inline"))
    # MIME and JS signatures cover extensionless / .pobrane HAR and local assets.
    for r in resources:
        if not is_html(r) and ("javascript" in r.mime or re.search(br"(?:fbq\s*\(|window\.aio\s*=|^\s*(?:!function|\(function|function\s|const\s|var\s|let\s))", r.data[:4096])):
            scripts.append((r, r.url or r.source["file"]))
    hashes = {}
    analysis = [(document.data.decode("utf-8", errors="replace"), document.source)] if document else []
    for r, name in scripts:
        h = digest(r.data)
        common = bool(re.search(r"fbevents|googletagmanager|google-analytics|jquery|bootstrap", name, re.I))
        record = hashes.setdefault(h, {"sha256": h, "common_library": False, "sources": [], "method": "sha256-decoded-bytes-v1"})
        record["common_library"] |= common
        if r.source not in record["sources"]:
            record["sources"].append(r.source)
        analysis.append((r.data.decode("utf-8", errors="replace"), r.source))
    ext["scripts"] = [hashes[h] for h in sorted(hashes)]
    out["page"]["script_hashes"] = sorted(hashes)
    for h in sorted(hashes):
        for s in hashes[h]["sources"]:
            evidence("page.script_hashes", s, "sha256-decoded-bytes-v1")
    for e, src in entries:
        analysis.append((str(obj(e.get("request")).get("url", "")), {**src, "json_path": src["json_path"] + ".request.url"}))
    ids = {"meta_pixel": set(), "ga": set(), "gtm": set(), "google_ads": set()}
    patterns = {
        "meta_pixel": [r"fbq\s*\(\s*['\"]init['\"]\s*,\s*['\"]?(\d+)", r"signals/config/(\d+)", r"facebook\.com/tr/?\?[^\s'\"<>]*?\bid=(\d+)"],
        "ga": [r"\b(G-[A-Z0-9]+|UA-\d+-\d+)\b"], "gtm": [r"\b(GTM-[A-Z0-9]+)\b"], "google_ads": [r"\b(AW-\d+)\b"]}
    allow = {"visit": {"fields": ["fb_ad_id", "fb_campaign_id", "fb_ad_set_id", "fb_pixel"]},
             "campaign": ["uuid", "owner_uuid"], "landing": ["uuid", "lander_template_uuid", "lander_type_uuid"]}
    ext["aio"] = {}
    for text, src in analysis:
        for kind, pats in patterns.items():
            for pat in pats:
                for value in re.findall(pat, text):
                    ids[kind].add(value)
                    evidence(f"extensions.tracking_ids.{kind}", src, "tracking-patterns-v1")
        try:
            config = literal_config(text)
        except (ValueError, SyntaxError, RecursionError):
            warn("aio_not_literal: configuration not executed")
            continue
        if config is not None:
            for section, keys in allow.items():
                values = obj(config.get(section))
                prefix = section
                if section == "visit":
                    values = obj(values.get("fields"))
                    keys = keys["fields"]
                    prefix += ".fields"
                for key in keys:
                    value = values.get(key)
                    if isinstance(value, (str, int)) and not isinstance(value, bool) and len(str(value)) <= 200:
                        name = f"{prefix}.{key}"
                        ext["aio"].setdefault(name, [])
                        if value not in ext["aio"][name]:
                            ext["aio"][name].append(value)
                        evidence(f"extensions.aio.{name}", src, "safe-literal-allowlist-v1; page declaration")
                        if key == "fb_pixel" and str(value).isdigit():
                            ids["meta_pixel"].add(str(value))
                            evidence("extensions.tracking_ids.meta_pixel", src, "safe-literal-allowlist-v1; page declaration")
    ext["tracking_ids"] = {k: sorted(v) for k, v in ids.items()}
    for k in ("meta_pixel", "ga"):
        out["page"]["tracking_ids"][k] = next(iter(sorted(ids[k])), None)
        ev[f"page.tracking_ids.{k}"] = ev.get(f"extensions.tracking_ids.{k}", [])
    ext["declared_ad_ids"] = [{"type": "fb_ad_id", "value": v, "source": "window.aio.visit.fields; page declaration, not Meta Ad Library mapping"} for v in ext["aio"].get("visit.fields.fb_ad_id", [])]

    ext["form_endpoints"] = []
    if doc:
        for action in doc.forms:
            endpoint = safe_url(urljoin(locals_base, action))
            if endpoint:
                ext["form_endpoints"].append({"url": endpoint, "kind": "html_form_action", "source": document.source})
                evidence("page.form_endpoint", document.source, "HTML form action; submission not asserted")
        out["page"]["form_endpoint"] = next((x["url"] for x in ext["form_endpoints"]), None)
    for text, src in analysis:
        for value in re.findall(r"(?:fetch|\.post)\s*\(\s*['\"]([^'\"]+)['\"]", text):
            endpoint = safe_url(urljoin(locals_base, value))
            if endpoint:
                ext["form_endpoints"].append({"url": endpoint, "kind": "code_candidate", "source": src})
    ext["post_requests"] = []
    for e, src in entries:
        req = obj(e.get("request"))
        if req.get("method") == "POST":
            endpoint = safe_url(req.get("url"))
            telemetry = bool(re.search(r"facebook\.com|google-analytics|/tr/?$|/collect|/telemetry|/session|/events", endpoint or "", re.I))
            ext["post_requests"].append({"url": endpoint, "kind": "telemetry" if telemetry else "unclassified_post", "source": src})
    if doc:
        contact_text = "\n".join(doc.text + doc.links)
        pats = {"phones": r"(?<![\w\d])(?:\+\d{1,3}[ -]?(?:\d[ -]?){8,11}\d|[1-9]\d{2}[ -]\d{3}[ -]\d{3}|[1-9]\d{8})(?![\w\d])",
                "telegram": r"(?:https?://)?(?:t\.me|telegram\.me)/[A-Za-z0-9_]+",
                "crypto": r"\b(?:0x[a-fA-F0-9]{40}|bc1[a-z0-9]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b"}
        ext["contact_candidates"] = []
        for kind, pat in pats.items():
            for m in re.finditer(pat, contact_text):
                value = m[0].strip()
                out["page"]["contacts"][kind].append(value)
                ext["contact_candidates"].append({"kind": kind, "value": value,
                    "context": contact_text[max(0, m.start()-40):m.end()+40], "source": document.source,
                    "method": "visible-text-and-links-pattern-v1; crypto checksum not verified"})
            out["page"]["contacts"][kind] = sorted(set(out["page"]["contacts"][kind]))
            evidence(f"page.contacts.{kind}", document.source, "visible-text-and-links-pattern-v1")

    image_models = [m for m in extractors if getattr(m, "modality", "image") == "image" and (getattr(m, "use_case", "") == "ocr" or "clip" in m.name.lower())]
    if screenshot:
        selected_path = (root / screenshot).resolve()
        if root not in selected_path.parents or not selected_path.is_file():
            raise ValueError("screenshot must be inside snapshot")
        ext["selected_screenshot"] = {"file": selected_path.relative_to(root).as_posix(),
            "sha256": digest(selected_path.read_bytes())}
    _images(root, resources, doc, resolve, screenshot, image_models, out, evidence, warn)
    if doc:
        from types import SimpleNamespace
        item = SimpleNamespace(text=ext["landing_text"], path=None, ad_id=None,
            origin_id=digest(document.data), source_field="extensions.landing_text")
        for model in extractors:
            if getattr(model, "modality", None) != "text":
                continue
            try:
                for result in model.extract(item):
                    if getattr(result, "reason", None):
                        warn(f"optional_model_unavailable: {model.name}: {result.field}")
                        continue
                    if result.field == "text.embedding":
                        vector = [float(x) for x in result.value]
                        if all(__import__('math').isfinite(x) for x in vector):
                            ext["landing_embedding"] = vector
                            evidence("extensions.landing_embedding", document.source, model.method_version)
            except Exception:
                warn(f"optional_model_failed: {model.name}: landing text")
    warn("offline_only: RDAP, ASN, certificate and current status not queried")
    warn("single_snapshot: ad history and Meta library identity unknown; landing text is not ad text")
    if not extractors:
        warn("optional_models_not_configured: OCR, text embedding, CLIP and faces not analyzed")
    else:
        warn("ad_text_embedding_and_faces_not_analyzed: no confirmed ad text or identity inference; check per-file model results")
    return out


def _images(root, resources, doc, resolve, screenshot, extractors, out, evidence, warn):
    ext = out["extensions"]
    ext["images"] = []
    icons = resolve(doc.icons[0]) if doc and doc.icons else []
    if not icons:
        icons = [r for r in resources if "icon" in r.mime or urlsplit(r.url).path.endswith("/favicon.ico")]
    unique_icons = {digest(r.data): r for r in icons}
    if len(unique_icons) > 1:
        warn("favicon_ambiguous: multiple distinct icons")
    icon = next(iter(unique_icons.values())) if len(unique_icons) == 1 else None
    if icon:
        try:
            import mmh3
            # Shodan convention: MIME base64 with 76-column lines and trailing LF.
            out["infra"]["favicon"]["mmh3"] = mmh3.hash(base64.encodebytes(icon.data), signed=True)
            evidence("infra.favicon.mmh3", icon.source, "mmh3-x86-32-signed/mime-base64-76-LF-v1")
        except ImportError:
            warn("mmh3_unavailable: favicon mmh3 not calculated")
    try:
        from PIL import Image
        import imagehash
    except ImportError:
        warn("image_dependencies_unavailable: install requirements-snapshot.txt for pHash")
        return
    selected = None
    if screenshot:
        path = (root / screenshot).resolve()
        if root not in path.parents or not path.is_file():
            raise ValueError("screenshot must be an existing file inside snapshot")
        selected = path.relative_to(root).as_posix()
    model_cache = {}
    for r in resources:
        magic = r.data[:16]
        possible = (r.mime.startswith("image/") or magic.startswith((b"\x89PNG", b"\xff\xd8", b"GIF8", b"RIFF", b"\x00\x00\x01\x00")))
        if not possible:
            continue
        sha = digest(r.data)
        # Record per source even for identical bytes, but reuse computed pHash.
        try:
            with Image.open(io.BytesIO(r.data)) as im:
                if im.width * im.height > 60_000_000:
                    raise ValueError("image pixel limit")
                ph = str(imagehash.phash(im.convert("RGB")))
        except Exception:
            warn(f"unreadable_or_unsupported_image: {r.source['file']}" + (f" #{r.source['har_entry']}" if "har_entry" in r.source else ""))
            continue
        row = {"source": r.source, "sha256": sha, "phash": ph, "method": "imagehash-phash64-v1"}
        ext["images"].append(row)
        if icon and sha == digest(icon.data):
            out["infra"]["favicon"]["phash"] = ph
            evidence("infra.favicon.phash", r.source, "imagehash-phash64-v1")
        if selected and r.source == {"file": selected}:
            out["visual"]["phash"] = ph
            evidence("visual.phash", r.source, "explicit-ad-screenshot/imagehash-phash64-v1")
        # Cache completed local inference only. A HAR copy must not suppress OCR.
        if extractors and not r.url:
            from types import SimpleNamespace
            if sha not in model_cache:
                cached = model_cache[sha] = {}
                item = SimpleNamespace(path=str(root / r.source["file"]), ad_id=None,
                    origin_id=sha, source_field=r.source["file"])
                for model in extractors:
                    try:
                        for result in model.extract(item):
                            if getattr(result, "reason", None):
                                warn(f"optional_model_unavailable: {model.name}: {result.field}")
                                continue
                            if result.field == "ocr.text":
                                cached["ocr_text"] = str(result.value)
                                cached["ocr_method"] = model.method_version
                            elif result.field == "image.embedding" and "clip" in model.name.lower():
                                vector = [float(x) for x in result.value]
                                if all(__import__('math').isfinite(x) for x in vector):
                                    cached["clip_embedding"] = vector
                                    cached["clip_method"] = model.method_version
                    except Exception:
                        warn(f"optional_model_failed: {model.name}: {r.source['file']}")
            cached = model_cache[sha]
            row.update(cached)
            if selected == r.source["file"]:
                if "ocr_text" in cached:
                    out["text"]["ocr_text"] = cached["ocr_text"]
                    evidence("text.ocr_text", r.source, cached["ocr_method"])
                if "clip_embedding" in cached:
                    out["visual"]["clip_embedding"] = cached["clip_embedding"]
                    evidence("visual.clip_embedding", r.source, cached["clip_method"])
    if not selected:
        warn("ad_screenshot_not_selected: image features kept per file; visual.phash unset")
    elif out["visual"]["phash"] is None:
        warn("selected_screenshot_not_decodable")


def write_snapshot(folder, output, **kwargs):
    """Write UTF-8 JSON (also accepted as a one-record JSONL by existing tooling)."""
    result = extract_snapshot(folder, **kwargs)
    Path(output).write_text(json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return result
