"""Resolve visible calls to action within one Meta card."""
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from ..sources import clean


LABEL = re.compile(r"obejrzyj (?:więcej|teraz)|oglądaj (?:więcej|teraz)|kup teraz|dowiedz się więcej|"
                   r"zobacz (?:więcej|ofertę)|sprawdź ofertę|zamów teraz|zarejestruj się|skorzystaj z oferty|"
                   r"watch (?:more|now)|shop now|buy now|learn more|see offer|get offer|order now|"
                   r"sign up|subscribe|subskrybuj|book now|apply now|download|contact us", re.I)


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
                or ((host == "facebook.com" or host.endswith(".facebook.com")) and not
                    re.search(r"^/(watch(?:/|$)|marketplace/item/|reel/)|/videos/", parsed.path))):
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
    linked_urls = set()
    seen_label = None
    for anchor in root.descendants():
        if anchor.tag not in {"a", "button"} and anchor.attr("role") not in {"button", "link"}:
            continue
        linked_urls.update(url for url, _ in links(anchor))
        labels = [anchor.attr("aria-label"), anchor.attr("title"), anchor.words()]
        for child in anchor.descendants():
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
    if len(targets) == 1:
        label, index, key = next(iter(targets.values()))
        return {"cta": label, "cta_element": index, "cta_attribute": key}
    if seen_label:
        return {"cta": seen_label, "landing_missing_reason": "Kilka celów CTA na karcie." if targets
                else "Przycisk CTA bez dostępnego odnośnika do strony docelowej."}
    if len(linked_urls) == 1:
        return {"landing_missing_reason": "Karta zawiera odnośnik do celu bez rozpoznanej etykiety CTA."}
    if linked_urls:
        return {"landing_missing_reason": "Karta zawiera kilka różnych celów bez rozpoznanej etykiety CTA."}
    return {"landing_missing_reason": "Brak odnośnika do celu w zapisie karty."}
