"""Bounded, credential-free HTTP reads for a public CTA and its page resources."""
import base64
import ipaddress
import json
import re
import socket
import ssl
import zlib
from datetime import datetime, timezone
from functools import cache
from time import monotonic
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

import certifi
import idna
import urllib3

from ..sources import address
from .trusted_domains import match_url, skip_reason


class LandingError(ValueError):
    pass


class DocumentTimeout(LandingError):
    pass


class TrustedDestination(LandingError):
    def __init__(self, host):
        super().__init__(skip_reason(host))
        self.host = host


def origin_of(url):
    parsed = urlsplit(url)
    return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


def public_url(url):
    parts = address(url)
    if not parts:
        return "[adres]"
    parsed = urlsplit(url)
    host = parts["host"]
    if ":" in host:
        host = "[" + host + "]"
    if parsed.port and parsed.port != (443 if parsed.scheme == "https" else 80):
        host += f":{parsed.port}"
    return urlunsplit((parsed.scheme, host, parts["path"], "", ""))


def validate_url(url):
    parsed = urlsplit(url)
    host = parsed.hostname
    if (not host or parsed.scheme not in {"https", "http"} or parsed.username is not None
            or parsed.password is not None or parsed.port not in {None, 80, 443}
            or any(ord(c) < 33 or c == "\\" for c in url)):
        raise LandingError("Niedozwolony adres strony lub zasobu.")
    return parsed


@cache
def tls_context():
    context = ssl.create_default_context()
    context.load_verify_locations(certifi.where())
    return context


def response_mime(headers):
    values = headers.getlist("Content-Type")
    kinds = {v.partition(";")[0].strip().lower() for v in values}
    if len(kinds) == 1:
        return values[-1]
    return "application/octet-stream" if values else ""


def read_public(url, budget, seconds, origin=None):
    parsed = validate_url(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    host = parsed.hostname
    authority = parsed.netloc
    if not host.isascii():
        host = idna.encode(host, uts46=True, std3_rules=True).decode("ascii")
        authority = host if parsed.port is None else f"{host}:{parsed.port}"
    ips = [ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]
    if not ips or any(not ip.is_global or ip.is_multicast or (ip.version == 6 and (
            ip.ipv4_mapped or ip.sixtofour or ip.teredo or ip in ipaddress.ip_network("64:ff9b::/96")))
            for ip in ips):
        raise LandingError("Adres poza publiczną siecią.")
    # Connect to the validated IP. Keep the original host for Host, TLS SNI and certificate checks.
    if parsed.scheme == "https":
        pool = urllib3.HTTPSConnectionPool(str(ips[0]), port, server_hostname=host, assert_hostname=host,
                                           ssl_context=tls_context())
    else:
        pool = urllib3.HTTPConnectionPool(str(ips[0]), port)
    path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    headers = request_headers(authority, origin)
    with pool:
        with pool.urlopen("GET", path, headers=headers,
                          timeout=urllib3.Timeout(total=seconds), retries=False, redirect=False,
                          preload_content=False) as response:
            status = response.status
            wire_headers = [{"name": k, "value": v} for k, v in response.headers.iteritems()]
            response_headers = dict(response.headers)
            received_at = monotonic()
            chunks = bytearray()
            read_error = None
            try:
                while len(chunks) <= budget:
                    chunk = response.read1(min(65536, budget + 1 - len(chunks)), decode_content=False)
                    if not chunk:
                        break
                    chunks.extend(chunk)
            except (OSError, urllib3.exceptions.HTTPError) as exc:
                read_error = exc
            raw = bytes(chunks)
            encoding = response.headers.get("Content-Encoding", "identity").lower()
            data, error = raw, None
            if len(raw) > budget:
                data, error = None, "Przekroczony limit rozmiaru odpowiedzi."
            elif encoding in {"gzip", "deflate"}:
                try:
                    inflater = zlib.decompressobj(31 if encoding == "gzip" else zlib.MAX_WBITS)
                    data = inflater.decompress(raw, budget + 1)
                    if len(data) > budget or not inflater.eof or inflater.unused_data:
                        data, error = None, "Niepełna lub zbyt duża skompresowana odpowiedź."
                except zlib.error:
                    data, error = None, "Błędna skompresowana odpowiedź."
            elif encoding not in {"", "identity"}:
                data, error = None, "Nieobsługiwane kodowanie odpowiedzi."
            expected = response.headers.get("Content-Length", "")
            if read_error or (status not in {204, 304} and expected.isdecimal() and int(expected) != len(raw)):
                error = error or "Niepełna treść odpowiedzi HTTP."
            location = response.headers.get("Location") if status in {301, 302, 303, 307, 308} else None
            wire = {"ip": str(ips[0]), "protocol": {10:"HTTP/1.0", 11:"HTTP/1.1"}.get(response.version, ""),
                    "headers": wire_headers, "reason": response.reason, "error": error,
                    "timeout": isinstance(read_error, (TimeoutError, urllib3.exceptions.TimeoutError)),
                    "receive": int((monotonic() - received_at) * 1000), "body_size": len(raw) if len(raw) <= budget else -1,
                    "charged": max(len(raw), len(data or b""))}
            return status, response_mime(response.headers), data, location, response_headers, wire


def request_headers(authority, origin):
    headers = {"Host": authority, "Accept-Encoding": "identity", "User-Agent": urllib3.util.SKIP_HEADER}
    if origin:
        headers["Origin"] = origin
    return headers


def pairs(values):
    return [{"name": key, "value": value} for key, value in values]


def content(body, mime):
    value = {"size": len(body), "mimeType": mime or "application/octet-stream"}
    if re.search(r"^(text/|[^;]*(?:json|javascript|ecmascript|xml|svg))", mime, re.I):
        charset = re.search(r"""charset\s*=\s*["']?([\w.-]+)""", mime, re.I)
        try:
            value["text"] = body.decode(charset[1] if charset else "utf-8")
            return value
        except (LookupError, UnicodeDecodeError):
            pass
    return {**value, "encoding": "base64", "text": base64.b64encode(body).decode("ascii")}


class PageReads:
    def __init__(self, seconds, journal=None, domain_db=None):
        self.domain_db = domain_db
        self.deadline = monotonic() + seconds
        self.remaining = 16 * 1024 * 1024
        self.entries = []
        self.requests = 0
        self.journal = journal

    def record(self, url, method, headers, observed_at, elapsed, *, status=0, mime="", body=None,
               target=None, wire=None, request_body=None, error=None, browser_headers=None, pending=False):
        wire = wire or {}
        version = wire.get("protocol", "")
        query = parse_qsl(urlsplit(url).query, keep_blank_values=True)
        request = {"method": method, "url": url, "httpVersion": version, "headers": headers, "cookies": [],
                   "queryString": pairs(query), "headersSize": -1, "bodySize": len(request_body or b"")}
        if browser_headers:
            request["_browserHeaders"] = browser_headers
        if request_body is not None:
            request_mime = next((h["value"] for h in headers if h["name"].lower() == "content-type"), "")
            data = content(request_body, request_mime)
            request["postData"] = {"mimeType": data["mimeType"], "text": data["text"]}
            if "encoding" in data:
                request["postData"]["_encoding"] = data["encoding"]
        response = {"status": status, "statusText": wire.get("reason", ""), "httpVersion": version,
                    "headers": wire.get("headers", []), "cookies": [], "headersSize": -1,
                    "bodySize": wire.get("body_size", len(body) if body is not None else -1), "redirectURL": target or "",
                    "content": content(body, mime) if body is not None else {"size": 0, "mimeType": mime}}
        receive = min(elapsed, wire.get("receive", 0))
        entry = {"pageref": "page_1", "startedDateTime": observed_at, "time": elapsed,
                 "request": request, "response": response, "cache": {},
                 "timings": {"send": 0, "wait": elapsed - receive, "receive": receive}}
        if wire.get("ip"):
            entry["serverIPAddress"] = wire["ip"]
        if error:
            entry["_error"] = error
        if pending:
            if self.journal:
                entry["_pendingIndex"] = len(self.entries)
                temp = self.journal.with_name(".pending.tmp")
                temp.write_text(json.dumps(entry), encoding="utf8")
                temp.replace(self.journal.with_name(".pending.json"))
            return
        self.entries.append(entry)
        if self.journal:
            with self.journal.open("a", encoding="utf8") as stream:
                stream.write(json.dumps(entry, ensure_ascii=True) + "\n")
            self.journal.with_name(".pending.json").unlink(missing_ok=True)

    def blocked(self, req, reason):
        self.record(req.url, req.method, req.headers_array(), datetime.now(timezone.utc).isoformat(),
                    0, request_body=req.post_data_buffer, error=reason)

    def get(self, url, origin=None, *, resource=False, browser_headers=None, document=False):
        for _ in range(6):
            if document:
                host = match_url(self.domain_db, url)
                if host:
                    raise TrustedDestination(host)
            start = monotonic()
            observed = datetime.now(timezone.utc).isoformat()
            headers = {"Host": urlsplit(url).netloc, "Accept-Encoding": "identity"}
            if origin:
                headers["Origin"] = origin
            try:
                seconds = self.deadline - start
                if seconds <= 0:
                    raise LandingError("Wyczerpano czas na żądania HTTP strony.")
                if self.requests >= 64:
                    raise LandingError("Osiągnięto limit 64 żądań HTTP strony.")
                if self.remaining <= 0:
                    raise LandingError("Osiągnięto limit 16 MiB odpowiedzi strony.")
                self.requests += 1
                self.record(url, "GET", pairs(headers.items()), observed, 0, browser_headers=browser_headers,
                            error="Przerwano oczekiwanie na odpowiedź.", pending=True)
                status, mime, body, redirect, response_headers, *details = read_public(
                    url, min((8 if document else 4) * 1024 * 1024, self.remaining),
                    min(6 if document else 4, seconds), origin)
            except (OSError, ValueError, urllib3.exceptions.HTTPError) as exc:
                self.record(url, "GET", pairs(headers.items()), observed, int((monotonic()-start)*1000),
                            error=str(exc) if isinstance(exc, LandingError) else type(exc).__name__,
                            browser_headers=browser_headers)
                if document and isinstance(exc, (TimeoutError, urllib3.exceptions.TimeoutError)):
                    raise DocumentTimeout("Upłynął czas pobierania głównego dokumentu.") from exc
                raise
            wire = details[0] if details else {"headers": pairs(response_headers.items())}
            self.remaining -= wire.get("charged", len(body or b""))
            target = urljoin(url, redirect) if redirect else None
            self.record(url, "GET", pairs(headers.items()), observed, int((monotonic()-start)*1000),
                        status=status, mime=mime, body=body, target=target, browser_headers=browser_headers,
                        wire=wire, error=wire.get("error"))
            if document and wire.get("timeout"):
                raise DocumentTimeout("Upłynął czas pobierania głównego dokumentu.")
            if wire.get("error"):
                raise LandingError(wire["error"])
            response_headers = urllib3.HTTPHeaderDict(response_headers)
            if target:
                if resource and origin_of(target) != origin_of(url):
                    raise LandingError("Przekierowanie zasobu do innego źródła. Pominięto zasób.")
                if resource and origin and origin_of(origin) != origin_of(url):
                    if response_headers.get("Access-Control-Allow-Origin") not in {origin, "*"}:
                        raise LandingError("Serwer nie udostępnił przekierowania tej stronie (CORS).")
                url = target
                continue
            if not document and not 200 <= status < 300:
                raise LandingError(f"HTTP {status} przy pobieraniu strony lub zasobu.")
            return url, mime, body, response_headers
        raise LandingError("Zbyt wiele przekierowań.")
