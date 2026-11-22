"""Resolve visible calls to action within one Meta card."""
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from ..sources import clean
from .authoritive_corpora import MULTI_TENANT_HOSTS, extract_etld_plus_1, is_multi_tenant_host
from .landing_fetch import public_url


LABEL = re.compile(r"obejrzyj (?:więcej|teraz)|oglądaj (?:więcej|teraz)|kup teraz|dowiedz się więcej|"
                   r"zobacz (?:więcej|ofertę)|sprawdź ofertę|zamów teraz|zarejestruj się|skorzystaj z oferty|"
                   r"watch (?:more|now)|shop now|buy now|learn more|see offer|get offer|order now|"
                   r"sign up|subscribe|subskrybuj|book now|apply now|download|contact us|"
                   # Polskie i angielskie etykiety przycisków CTA z Biblioteki Meta (decyzja zespołu, lista otwarta).
                   r"więcej informacji|zapisz się|pobierz|zainstaluj(?: teraz)?|zarezerwuj(?: teraz)?|"
                   r"aplikuj(?: teraz)?|złóż wniosek|uzyskaj ofertę|odbierz ofertę|zamów|skontaktuj się z nami|"
                   r"wyślij wiadomość|zadzwoń(?: teraz)?|get quote|get started|install now|send message|call now|"
                   r"use app|play game|zagraj", re.I)

FACEBOOK = {"facebook.com", "www.facebook.com", "m.facebook.com", "web.facebook.com", "fb.watch"}
# Zaślepka Biblioteki Meta: l.php?u=http://fb.me/ bez ścieżki, gdy platforma nie ujawnia celu reklamy.
HIDDEN_HOSTS = {"fb.me", "www.fb.me"}
# Strony informacyjne Meta linkowane z komunikatów biblioteki (standardy, zastrzeżenia), nie cel reklamodawcy.
META_INFO_HOSTS = {"transparency.meta.com", "about.meta.com", "www.meta.com", "help.instagram.com"}
HIDDEN_REASON = "Biblioteka Meta ukryła adres docelowy reklamy (zaślepka fb.me)."
# Profile platform i kanały kontaktu: nie są stroną docelową wybieraną automatycznie (decyzja zespołu).
PLATFORM_HOSTS = {"instagram.com", "www.instagram.com", "threads.net", "www.threads.net", "m.me", "wa.me",
                  "api.whatsapp.com", "chat.whatsapp.com", "t.me", "telegram.me", "msng.link"}
# Cel wybrany regułą zamiast etykiety przycisku lub analityka (kontrakt: docs/DATA_CONTRACT.md).
AUTO_BASES = {"single_link", "dominant_domain", "caption"}
BASIS_LABEL = {"single_link": "Jedyny odnośnik na karcie", "dominant_domain": "Wspólna domena odnośników karty",
               "caption": "Domena z podpisu karty"}
CAPTION = re.compile(r"(?:https?://)?((?:www\.)?(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+([a-z]{2,24}))(/\S*)?", re.I)
FILE_SUFFIXES = {"jpg", "jpeg", "png", "gif", "webp", "mp4", "mov", "pdf", "zip", "js", "css", "html", "htm", "php"}
# Podpis musi kończyć się dwuliterowym ccTLD albo jedną z popularnych domen ogólnych (bez listy PSL offline),
# żeby „Dr.Oetker” czy „Kup.Teraz” nie stawały się adresami.
GTLDS = {"com", "net", "org", "info", "biz", "edu", "gov", "shop", "store", "online", "site", "website", "xyz", "app",
         "dev", "pro", "club", "top", "live", "life", "health", "care", "clinic", "money", "finance", "capital",
         "invest", "trade", "markets", "bank", "news", "blog", "page", "link", "click", "space", "tech", "digital",
         "agency", "company", "group", "global", "world", "today", "email", "fun", "vip", "win", "bet", "casino",
         "beauty", "fit", "diet", "fashion", "travel", "estate", "homes", "house", "academy", "media", "tv",
         "icu", "sbs", "cfd", "buzz", "cyou", "bond", "lat", "rest", "monster", "quest", "cam", "help"}
# Hosty, których sam podpis nie wskazuje strony reklamodawcy (sklepy z aplikacjami, serwisy wideo).
CAPTION_SKIP = {"play.google.com", "apps.apple.com", "youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com",
                "tiktok.com", "www.tiktok.com", "amazon.com", "www.amazon.com", "google.com", "www.google.com"}
# Skracacze: różne ścieżki to różne cele, więc wspólny host nie oznacza wspólnej domeny reklamodawcy.
SHORTENERS = {"bit.ly", "tiny.pl", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "cutt.ly", "rebrand.ly",
              "shorturl.at", "rb.gy", "s.id", "lnk.to"}
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


def unwrap(href):
    """Adres po zdjęciu przekierowania l.facebook.com / l.instagram.com albo None."""
    url = urljoin("https://www.facebook.com/", href)
    parsed = urlsplit(url)
    facebook_wrapper = parsed.hostname in {"www.facebook.com", "l.facebook.com", "lm.facebook.com", "facebook.com"}
    if (facebook_wrapper and parsed.path == "/l.php") or (parsed.hostname == "l.instagram.com" and parsed.path == "/"):
        targets = parse_qs(parsed.query).get("u", [])
        if len(targets) != 1:
            return None
        url = targets[0]
    return url


def _placeholder(parsed):
    return ((parsed.hostname or "").lower().rstrip(".") in HIDDEN_HOSTS
            and parsed.path in {"", "/"} and not parsed.query)


def hidden_target(href):
    """Biblioteka Meta podstawia sam korzeń fb.me zamiast adresu docelowego, którego nie ujawnia."""
    try:
        url = unwrap(href)
        return bool(url) and _placeholder(urlsplit(url))
    except ValueError:
        return False


def destination(href):
    try:
        url = unwrap(href)
        if url is None:
            return None
        parsed = urlsplit(url)
        if _placeholder(parsed):
            return None
        host = (parsed.hostname or "").lower().rstrip(".")
        if host in META_INFO_HOSTS:
            return None
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


def caption_url(text):
    """Adres z widocznego podpisu domeny na karcie (np. „inwestycja.zikom.pl/”) albo None."""
    match = CAPTION.fullmatch(clean(text or ""))
    tld = match[2].lower() if match else ""
    if not match or tld in FILE_SUFFIXES or not (len(tld) == 2 or tld in GTLDS):
        return None
    host = match[1].lower()
    if host in HIDDEN_HOSTS or host in PLATFORM_HOSTS or host in CAPTION_SKIP or host in MULTI_TENANT_HOSTS:
        return None
    if extract_etld_plus_1(host) in {"facebook.com", "fb.com", "instagram.com", "meta.com", "whatsapp.com"}:
        return None
    return destination("https://" + host + (match[3] or "/"))


def own_text(node):
    return clean("".join(part for part in node.parts if isinstance(part, str)))


def linked_node(node):
    """Tekst opisuje odnośnik, a nie cel reklamy: najbliższy odnośnik ma własny adres (inny niż zaślepka
    fb.me) albo którykolwiek odnośnik nad elementem prowadzi do Facebooka (np. nazwa strony → profil)."""
    nearest = True
    for item in (node, *node.ancestors()):
        if item.tag != "a" and item.attr("role") not in {"link", "button"}:
            continue
        values = [v for v in (item.attr(key) for key in ("href", "data-href", "data-url")) if v and not hidden_target(v)]
        if any(destination(value) is None for value in values) or (nearest and values):
            return True
        nearest = False
    return False


def card_caption(root):
    """Podpis domeny z podglądu reklamy: widoczny element, którego cały własny tekst jest adresem.

    Pomija tekst odnośników z adresem (link w treści reklamy, nazwa strony prowadząca do profilu),
    bo taki tekst opisuje sam odnośnik, a nie cel reklamy. W Bibliotece Meta podpis stoi w stopce
    podglądu bez własnego atrybutu href.
    """
    for node in root.descendants():
        text = own_text(node)
        if (not text or len(text) > 120 or node.hidden() or any(p.hidden() for p in node.ancestors())
                or linked_node(node)):
            continue
        url = caption_url(text)
        if url:
            return node.index, text, url
    return None


def site(url):
    """Domena rejestrowa; dla hostingu wielu najemców i skracaczy pełny host jest osobnym właścicielem."""
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    if is_multi_tenant_host(host) or host in SHORTENERS:
        return host
    return extract_etld_plus_1(host)


def auto_target(targets, linked, caption, label):
    """Wybór celu bez potwierdzenia analityka (decyzja zespołu). Zwraca pola CTA albo None.

    Kolejność: wspólna domena kilku odnośników, jedyny odnośnik do strony, odnośnik zgodny z podpisem
    domeny, sam podpis domeny. Kanały kontaktu i profile platform nie są stroną docelową.
    """
    pages = {url: value for url, value in linked.items()
             if (urlsplit(url).hostname or "").lower().rstrip(".") not in PLATFORM_HOSTS}
    named = {url: value[1:] for url, value in targets.items() if url in pages}
    pool = named or pages
    domains = {site(url) for url in pool}
    shortened = any((urlsplit(url).hostname or "").lower().rstrip(".") in SHORTENERS for url in pool)
    pick = None
    if len(pool) > 1 and len(domains) == 1 and "" not in domains and not shortened:
        pick = next(iter(pool.items())), "dominant_domain"
    elif len(pool) == 1:
        pick = next(iter(pool.items())), "single_link"
    elif caption and pool:
        matching = [item for item in pool.items() if site(item[0]) == site(caption[2])]
        if len({site(url) for url, _ in matching}) == 1:
            pick = matching[0], "caption"
    if pick:
        (_, (index, key)), basis = pick
        return {"cta": label or BASIS_LABEL[basis], "cta_element": index, "cta_attribute": key, "cta_basis": basis}
    if caption and not pool:
        return {"cta": label or BASIS_LABEL["caption"], "cta_element": caption[0], "cta_attribute": "text",
                "cta_basis": "caption"}
    return None


def card_cta(root, auto=True):
    """Cel CTA karty. auto=False (konfiguracja auto_target=false) wyłącza wybór celu regułą."""
    targets = {}
    linked = {}
    preview = {}
    seen_label = None
    hidden = False
    profile = set()
    for anchor in root.descendants():
        if anchor.tag not in {"a", "button"} and anchor.attr("role") not in {"button", "link"}:
            continue
        if any(node.tag == "nav" or node.attr("role") == "navigation"
               for node in (anchor, *anchor.ancestors()) if node is not root):
            continue
        hidden = hidden or any(hidden_target(anchor.attr(key)) for key in ("href", "data-href", "data-url")
                               if anchor.attr(key))
        children = list(anchor.descendants())
        logo_only = not anchor.words() and any(
            child.tag == "img" and re.search(r"\b(?:logo|logotyp|profil|profile|avatar)\b", child.attr("alt"), re.I)
            for child in children)
        for url, key in links(anchor):
            linked.setdefault(url, (anchor.index, key))
            if logo_only:
                profile.add(url)
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
    caption = card_caption(root)
    if caption:
        result["cta_caption"] = caption[1]
    if len(targets) == 1 or (not targets and len(linked) == 1 and preview):
        if targets:
            label, index, key = next(iter(targets.values()))
            basis = "label"
        else:
            index, key = next(iter(preview.values()))
            label, basis = "Odnośnik w podglądzie reklamy", "preview"
        return {**result, "cta": label, "cta_element": index, "cta_attribute": key, "cta_basis": basis}
    guess = auto and auto_target(targets, {url: v for url, v in linked.items() if url not in profile}, caption, seen_label)
    if guess:
        return {**result, **guess}
    if hidden and not targets:
        # Pozostałe odnośniki karty (np. adres w treści) zostają kandydatami do potwierdzenia.
        return {**result, **({"cta": seen_label} if seen_label else {}), "landing_missing_reason": HIDDEN_REASON}
    if seen_label:
        return {**result, "cta": seen_label, "landing_missing_reason": "Kilka celów CTA na karcie." if targets
                else "Przycisk CTA bez dostępnego odnośnika do strony docelowej."}
    if len(linked) == 1:
        return {**result, "landing_missing_reason": "Karta zawiera odnośnik do celu bez rozpoznanej etykiety CTA."}
    if linked:
        return {**result, "landing_missing_reason": "Karta zawiera kilka różnych celów bez rozpoznanej etykiety CTA."}
    return {**result, "landing_missing_reason": "Brak odnośnika do celu w zapisie karty."}
