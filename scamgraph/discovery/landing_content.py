"""Identify usable content and cite the exact response or DOM that carries it."""
import io
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit
import wave

from PIL import Image

from ..landing import Document, html_text
from ..page_text import consent_candidate, transcript
from ..sources import clean
from .cta import target_identity


BLOCKED = re.compile(r"^(?:access denied|forbidden|just a moment|attention required|security check|"
                     r"verify (?:that )?you are human|log in (?:or sign up )?to (?:continue|facebook)|"
                     r"log into facebook|facebook\s*[–-]\s*(?:log in|zaloguj)|odmowa dostępu|"
                     r"zaloguj się(?:, aby kontynuować| (?:do|na) facebook[ua]?))\b", re.I)
UNAVAILABLE = re.compile(r"^(?:page not found|not found|404(?:\b|$)|this content (?:isn't|is not) available|"
                         r"nie znaleziono strony|ta zawartość jest niedostępna)\b", re.I)
ERROR = re.compile(r"^(?:bad gateway|service unavailable|internal server error|something went wrong|"
                   r"site (?:is )?under maintenance|wystąpił błąd|coś poszło nie tak|błąd serwera)\b", re.I)
GENERIC_META = {"facebook", "facebook marketplace", "marketplace", "watch", "facebook watch", "reels", "facebook reels"}
META_BOILERPLATE = re.compile(r"^(?:see posts,? photos and more|see more (?:on|of)|connect with friends|"
                              r"log in|log into|join facebook|sign up|zaloguj|zobacz (?:więcej|posty|zdjęcia)|"
                              r"dołącz do facebooka|kontaktuj się ze znajomymi)\b", re.I)
MIME_FILES = {
    "application/pdf": ("pdf", "pdf"), "image/png": ("image", "png"), "image/jpeg": ("image", "jpg"),
    "image/gif": ("image", "gif"), "image/webp": ("image", "webp"),
    "audio/wav": ("audio", "wav"), "audio/x-wav": ("audio", "wav"),
    "audio/mp4": ("audio", "m4a"), "audio/x-m4a": ("audio", "m4a"), "video/mp4": ("video", "mp4"),
}


def mp4_boxes(data):
    position = 0
    while position < len(data):
        if len(data) - position < 8:
            raise ValueError("Incomplete MP4 box")
        header = data[position:position + 8]
        size = int.from_bytes(header[:4], "big")
        width = 8
        if size == 1:
            size, width = int.from_bytes(data[position + 8:position + 16], "big"), 16
        elif size == 0:
            size = len(data) - position
        if not width <= size <= len(data) - position:
            raise ValueError("Invalid MP4 box length")
        yield bytes(header[4:8]), data[position + width:position + size]
        position += size


def mp4_media(body, extension):
    try:
        boxes = list(mp4_boxes(memoryview(body)))
        media_bytes = sum(len(data) for kind, data in boxes if kind == b"mdat")
        if not media_bytes or not any(kind == b"ftyp" and len(data) >= 8 for kind, data in boxes):
            return False
        wanted = b"vide" if extension == "mp4" else b"soun"
        fragmented = any(int.from_bytes(run[4:8], "big") > 0
                         for kind, fragment in boxes if kind == b"moof"
                         for kind, track in mp4_boxes(fragment) if kind == b"traf"
                         for kind, run in mp4_boxes(track) if kind == b"trun")
        for kind, movie in boxes:
            if kind != b"moov":
                continue
            for tag, track in mp4_boxes(movie):
                if tag != b"trak":
                    continue
                for tag, media in mp4_boxes(track):
                    if tag != b"mdia":
                        continue
                    chunks = dict(mp4_boxes(media))
                    if chunks.get(b"hdlr", b"")[8:12] != wanted:
                        continue
                    info = dict(mp4_boxes(chunks.get(b"minf", b"")))
                    samples = dict(mp4_boxes(info.get(b"stbl", b"")))
                    descriptions = list(mp4_boxes(samples.get(b"stsd", b"")[8:]))
                    if not any(len(description) >= 16 for _, description in descriptions):
                        continue
                    sizes = samples.get(b"stsz", b"")
                    if len(sizes) < 12:
                        continue
                    size, count = (int.from_bytes(sizes[i:i+4], "big") for i in (4, 8))
                    if fragmented or (count and size and size * count <= media_bytes):
                        return True
                    if count and not size and len(sizes) == 12 + 4 * count:
                        total = sum(int.from_bytes(sizes[i:i+4], "big") for i in range(12, len(sizes), 4))
                        if 0 < total <= media_bytes:
                            return True
        return False
    except ValueError:
        return False


def file_format(mime, body, hint):
    if mime in {"application/octet-stream", "application/mp4"}:
        return next((result for fmt, (kind, _) in MIME_FILES.items() if kind == hint
                     and (result := file_format(fmt, body, hint))), None)
    if mime not in MIME_FILES:
        return None
    kind, extension = MIME_FILES[mime]
    if kind == "image":
        try:
            with Image.open(io.BytesIO(body), formats=[{"jpg": "JPEG"}.get(extension, extension.upper())]) as image:
                if image.width * image.height <= 32_000_000:
                    image.verify()
                    return kind, extension
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
            return None
        return None
    if extension == "pdf":
        marker = re.search(br"startxref\s+(\d{1,12})\s+%%EOF\s*\Z", body[-1024:])
        start = int(marker[1]) if marker else len(body)
        xref = body[start:start + 4096]
        valid = body.startswith(b"%PDF-") and (xref.startswith(b"xref") and b"/Root" in body or
                bool(re.match(br"\d+\s+\d+\s+obj\b", xref) and re.search(br"/Type\s*/XRef\b", xref)))
    elif extension == "wav":
        try:
            with wave.open(io.BytesIO(body), "rb") as audio:
                frame_size = audio.getnchannels() * audio.getsampwidth()
                frames = audio.getnframes()
                valid = frames > 0 and len(audio.readframes(frames)) == frames * frame_size
        except (wave.Error, EOFError, ValueError):
            valid = False
    else:
        valid = mp4_media(body, extension)
    return (kind, extension) if valid else None


def screen_status(text):
    for pattern, status, reason in ((BLOCKED, "blocked", "access_screen"),
                                    (UNAVAILABLE, "unavailable", "unavailable_screen"),
                                    (ERROR, "error", "error_screen")):
        if pattern.match(text):
            return status, reason, None
    return None


def html_content(path, relative, final_url, expected):
    doc = Document(html_text(path))
    headings = [n for n in doc.nodes if n.tag in {"title", "h1"} and not n.hidden()
                and not any(p.hidden() for p in n.ancestors())]
    for node in headings:
        if status := screen_status(node.words()):
            return status
    dialogs = {n.index for n in doc.nodes if consent_candidate(n) or n.tag == "aside"}
    rows = [row for row in transcript(doc, {"path": relative, "sha256": ""}, dialogs) if row["section"] == "content"]
    if rows and (status := screen_status(rows[0]["value"])):
        return status
    final = target_identity(final_url)
    if expected[0].startswith("facebook_") or final[0].startswith("facebook_"):
        if final[0] == "facebook_other":
            return "unsupported", "unsupported_facebook_target", None
        if expected[0].startswith("facebook_") and (expected[0] != final[0] or expected[1] and expected[1] != final[1]):
            return "error", "target_mismatch", None
        identities = [n for n in doc.nodes if (n.tag == "link" and n.attr("rel").lower() == "canonical")
                      or (n.tag == "meta" and n.attr("property") == "og:url")]
        verified = []
        for identity in identities:
            value = identity.attr("href" if identity.tag == "link" else "content").strip()
            try:
                if not urlsplit(value).path:
                    continue
                identified = target_identity(urljoin(final_url, value))
            except ValueError:
                continue
            if not identified[1]:
                continue
            if not final[1] or identified != final:
                return "error", "target_mismatch", None
            verified.append(identity)
        if not verified:
            return "error", "unverified_facebook_object", None
        nodes = [(n, clean(n.attr("content"))) for n in doc.nodes if n.tag == "meta"
                 and n.attr("property") in {"og:title", "og:description"}]
        nodes += [(n, n.words()) for n in headings if n.tag == "h1"]
        for node, value in nodes:
            normalized = re.sub(r"\s*\|\s*Facebook$", "", value, flags=re.I)
            if (len(normalized) >= 8 and normalized.lower() not in GENERIC_META
                    and not (screen_status(value) or META_BOILERPLATE.match(value))):
                identity = next((n for n in verified if n.tag == "meta"), verified[0])
                return "usable", None, {"file": relative, "element": node.index,
                                        "identity_element": identity.index, "text": value[:260]}
        article_error = None
        for row in rows:
            value, locator = row["value"], row["evidence"]["locator"]
            if locator["element"] and locator["tag"] in {"p", "blockquote"} and len(value.split()) >= 3:
                node = doc.nodes[locator["element"] - 1]
                if any(n.tag == "article" or n.attr("role") == "article" for n in node.ancestors()):
                    if status := screen_status(value):
                        article_error = status
                        continue
                    if META_BOILERPLATE.match(value):
                        continue
                    return "usable", None, {"file": relative, **locator,
                                            "identity_element": verified[0].index, "text": value[:260]}
        for node in doc.nodes:
            if node.tag not in {"img", "video"} or node.hidden() or any(n.hidden() for n in node.ancestors()):
                continue
            if not any(n.tag == "article" or n.attr("role") == "article" for n in node.ancestors()):
                continue
            media = node.attr("src").removeprefix("./")
            match = re.fullmatch(r"page_files/[a-f0-9]{32}\.(jpg|png|gif|webp|mp4)", media)
            local = path.parent / Path(media)
            if not match or not local.is_file():
                continue
            mime = next(fmt for fmt, (_, extension) in MIME_FILES.items() if extension == match[1])
            if file_format(mime, local.read_bytes(), None):
                return "usable", None, {"file": relative, "element": node.index,
                                        "identity_element": verified[0].index, "media_file": f"landing/{media}"}
        return article_error or ("error", "unverified_facebook_object", None)
    for row in rows:
        value = row["value"]
        if (len(value.split()) >= 3 and not re.match(
                r"^(?:cookie|ciastecz|log in|zaloguj|we use cookies|używamy plików cookie)", value, re.I)
                and not screen_status(value)):
            return "usable", None, {"file": relative, **row["evidence"]["locator"], "text": value[:260]}
    return "error", "content_missing", None
