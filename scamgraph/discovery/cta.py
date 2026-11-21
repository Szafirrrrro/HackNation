"""Resolve visible calls to action within one Meta card."""
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from ..sources import clean
from .landing_fetch import public_url


LABEL = re.compile(r"obejrzyj (?:więcej|teraz)|oglądaj (?:więcej|teraz)|kup teraz|dowiedz się więcej|"
                   r"zobacz (?:więcej|ofertę)|sprawdź ofertę|zamów teraz|zarejestruj się|skorzystaj z oferty|"
                   r"watch (?:more|now)|shop now|buy now|learn more|see offer|get offer|order now|"
                   r"sign up|subscribe|subskrybuj|book now|apply now|download|contact us", re.I)

FACEBOOK = {"facebook.com", "www.facebook.com", "m.facebook.com", "web.facebook.com", "fb.watch"}
OBJECT_ID = r"(?:[0-9]+|pfbid[A-Za-z0-9]+)"
FACEBOOK_PATHS = {
    "facebook_marketplace": rf"/marketplace/item/({OBJECT_ID})",
    "facebook_post": rf"/(?:[^/]+|groups/[^/]+)/posts/({OBJECT_ID})",
    "facebook_video": rf"/(?:reel|watch|(?:[^/]+/)?videos)/({OBJECT_ID})",
}
FILE_TYPES = {
    "pdf": {"pdf"}, "image": {"png", "jpg", "jpeg", "gif", "webp"},
    "audio": {"mp3", "wav", "ogg", "m4a"}, "video": {"mp4", "webm"},
}


def target_identity(url):
    parsed = urlsplit(url)
    path = parsed.path.rstrip("/")
    host = (parsed.hostname or "").rstrip(".")
    if host in FACEBOOK:
        for kind, pattern in FACEBOOK_PATHS.items():
            if match := re.fullmatch(pattern, path):
                return kind, match[1]
        for kind, paths, key in (("facebook_post", {"/permalink.php", "/story.php", "/photo.php", "/photo"}, "story_fbid"),
                                 ("facebook_video", {"/watch", "/video.php"}, "v")):
            if path in paths:
                query = parse_qs(parsed.query)
                ids = query.get("fbid" if path.startswith("/photo") else key, [])
                if len(ids) == 1 and re.fullmatch(OBJECT_ID, ids[0]):
                    return kind, ids[0]
        if host == "fb.watch" and re.fullmatch(r"/[A-Za-z0-9_-]+", path):
            return "facebook_video", None
        if match := re.fullmatch(r"/share/([pvr])/[A-Za-z0-9_-]+", path):
            return ("facebook_post" if match[1] == "p" else "facebook_video"), None
    if host in FACEBOOK or host.endswith(".facebook.com"):
        return "facebook_other", None
    extension = path.rpartition(".")[2].lower()
    return next((kind for kind, extensions in FILE_TYPES.items() if extension in extensions), "web"), None


def destination(href):
    try:
        url = urljoin("https://www.facebook.com/", href)
        parsed = urlsplit(url)
        facebook_wrapper = parsed.hostname in {"www.facebook.com", "l.facebook.com", "lm.facebook.com", "facebook.com"}
        if (facebook_wrapper and parsed.path == "/l.php") or (parsed.hostname == "l.instagram.com" and parsed.path == "/"):
            targets = parse_qs(parsed.query).get("u", [])
            if len(targets) != 1:
                return None
            url = targets[0]
            parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if (not host or parsed.scheme not in {"http", "https"} or parsed.username is not None
                or parsed.password is not None or parsed.port not in {None, 80, 443}
                or ((host == "facebook.com" or host.endswith(".facebook.com"))
                    and (host not in FACEBOOK or target_identity(url)[0] == "facebook_other"))):
            return None
        return url
    except ValueError:
        return None


def links(node):
    for key in ("href", "data-href", "data-url"):
        if node.attr(key):
            target = destination(node.attr(key))
            if target:
                yield target, key


def card_cta(root):
    targets = {}
    linked = {}
    preview = {}
    seen_label = None
    for anchor in root.descendants():
        if anchor.tag not in {"a", "button"} and anchor.attr("role") not in {"button", "link"}:
            continue
        if any(node.tag == "nav" or node.attr("role") == "navigation"
               for node in (anchor, *anchor.ancestors()) if node is not root):
            continue
        children = list(anchor.descendants())
        for url, key in links(anchor):
            linked.setdefault(url, (anchor.index, key))
            in_chrome = any(n.tag in {"header", "footer"} for n in (anchor, *anchor.ancestors()) if n is not root)
            image_preview = (urljoin("https://www.facebook.com/", anchor.attr(key)) != url and any(
                child.tag in {"img", "video"} and not re.search(r"\b(?:logo|logotyp|profil|profile|avatar)\b", child.attr("alt"), re.I)
                for child in children))
            if (not in_chrome and (image_preview or any(child.attr("role") in {"button", "link"} for child in children))):
                preview.setdefault(url, (anchor.index, key))
        labels = [anchor.attr("aria-label"), anchor.attr("title"), anchor.words()]
        for child in children:
            labels.extend((child.attr("aria-label"), child.attr("alt"), child.attr("title")))
            labels.extend(part for part in child.parts if isinstance(part, str))
        label = next((clean(s) for s in labels if LABEL.fullmatch(clean(s))), None)
        if not label:
            continue
        seen_label = label
        for node in (anchor, *anchor.ancestors()):
            for target, key in links(node):
                targets.setdefault(target, (label, node.index, key))
            if node is root:
                break
    candidates = {**linked, **{url: value[1:] for url, value in targets.items()}}
    result = {"landing_candidates": []}
    for url, (element, attribute) in candidates.items():
        kind, object_id = target_identity(url)
        candidate = {"url": public_url(url), "kind": kind, "element": element, "attribute": attribute}
        if object_id:
            candidate["object_id"] = object_id
        result["landing_candidates"].append(candidate)
    if len(targets) == 1 or (not targets and len(linked) == 1 and preview):
        if targets:
            label, index, key = next(iter(targets.values()))
            basis = "label"
        else:
            index, key = next(iter(preview.values()))
            label, basis = "Odnośnik w podglądzie reklamy", "preview"
        return {**result, "cta": label, "cta_element": index, "cta_attribute": key, "cta_basis": basis}
    if seen_label:
        return {**result, "cta": seen_label, "landing_missing_reason": "Kilka celów CTA na karcie." if targets
                else "Przycisk CTA bez dostępnego odnośnika do strony docelowej."}
    if len(linked) == 1:
        return {**result, "landing_missing_reason": "Karta zawiera odnośnik do celu bez rozpoznanej etykiety CTA."}
    if linked:
        return {**result, "landing_missing_reason": "Karta zawiera kilka różnych celów bez rozpoznanej etykiety CTA."}
    return {**result, "landing_missing_reason": "Brak odnośnika do celu w zapisie karty."}
