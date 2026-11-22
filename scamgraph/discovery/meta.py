"""Public Meta Ad Library. Live and manual HTML go through the same visible-card parser."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from html import unescape
from importlib.util import find_spec
from pathlib import Path
from time import monotonic
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit
from uuid import uuid4

from ..landing import Document, Node
from ..media import AUDIO, IMAGES, VIDEO
from ..sources import clean
from .types import Finding, Query, SourceError
from .cta import card_cta

LIBRARY = "https://www.facebook.com/ads/library/"
MAX_BYTES = 12 * 1024 * 1024
ID = re.compile(
    r"\b(?:identyfikator\s+(?:w\s+)?bibliote(?:ki|ce)(?:\s+reklam)?|id\s+biblioteki(?:\s+reklam)?|library\s+id)\s*[:#]?\s*(\d{1,30})\b",
    re.I,
)
STATUS = re.compile(r"(?:active|inactive|aktywn[aye]|nieaktywn[aye]|nieaktywne|nie emitowana)", re.I)
SPONSORED = re.compile(r"^(?:sponsored|sponsorowan[aye])$", re.I)
REMOVED = re.compile(
    r"(?:ta reklama|treść reklamy|this ad|ad content).{0,140}(?:usunięt|wycofan|niedostępn|removed|unavailable)|"
    r"(?:reklama|reklamę|ad).{0,200}(?:wyłącz|wył[ąa]czon|disabled|deactivated).{0,140}(?:kont|stron|account|page|standard)|"
    r"(?:konto|strona|account|page).{0,150}(?:wyłącz|usunięt|disabled|deactivated)|"
    r"(?:wyłącz\w*|disabled).{0,70}(?:stron|kont|account|page).{0,90}(?:standard|zasad|polic)",
    re.I,
)
DATE = re.compile(
    r"^(?:(?:started running|ran from|rozpocz[ęe]to|początek emisji|wyświetlan[aoe]|emisja od)\b|"
    r"(?:\d{1,2}[\s.\-/–—]+(?:\d{1,2}[\s.]+)?(?:sty|lut|mar|kwi|maj|cze|lip|sie|wrz|paź|lis|gru|jan|feb|apr|may|jun|jul|aug|sep|oct|nov|dec)|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\.?\s+\d{1,2}\b|\d{4}-\d{2}-\d{2}\b))",
    re.I,
)
EMPTY = re.compile(
    r"^(?:brak (?:wyników|reklam)(?: wyszukiwania)?|nie znaleziono (?:żadnych )?(?:wyników|reklam)|"
    r"no (?:ads|results)(?: found)?|0 (?:reklam|wyników|ads|results))(?:[.! ]|$)",
    re.I,
)
BLOCKED = re.compile(
    r"(?:^zaloguj się, aby kontynuować|^log in to continue|captcha|potwierdź, że jesteś człowiekiem|"
    r"temporarily blocked|tymczasowo zablokowan|verify you are human|security check required|"
    r"^something went wrong|^coś poszło nie tak|^this page isn't available)",
    re.I,
)
CHROME = re.compile(
    r"^(?:zobacz szczegóły reklamy|see ad details|see summary details|szczegóły reklamy|"
    r"platform[sy]?|learn more|dowiedz się więcej|zobacz więcej|see more|sponsored|sponsorowane|"
    r"biblioteka reklam|ad library|menu|więcej opcji|more options)$",
    re.I,
)
BLOCKS = set("article section main header footer aside nav form h1 h2 h3 h4 h5 p div li tr td br button a time".split())


def search_url(query):
    return LIBRARY + "?" + urlencode(
        {
            "active_status": "all",
            "ad_type": "all",
            "country": query.country,
            "search_type": "keyword_exact_phrase",
            "q": query.phrase,
        }
    )


def _scope(url, query):
    parsed = urlsplit(unescape(url))
    if parsed.hostname not in {"facebook.com", "www.facebook.com", "m.facebook.com"} or parsed.path.rstrip("/") != "/ads/library":
        return False
    params = parse_qs(parsed.query)
    return (
        params.get("country") == [query.country]
        and params.get("q") == [query.phrase]
        and params.get("search_type") == ["keyword_exact_phrase"]
    )


def _lines(node, exclude=(), *, prose=False):
    pieces = []
    blocks = BLOCKS - {"a", "time", "br"} if prose else BLOCKS

    def visit(part):
        if isinstance(part, str):
            pieces.append(re.sub(r"\s+", " ", part) if prose else part)
        elif part not in exclude and not part.hidden() and part.tag not in {"head", "nav", "footer"}:
            if prose and part.tag == "br":
                pieces.append(" ")
            if part.tag in blocks:
                pieces.append("\n")
            for child in part.parts:
                visit(child)
            if part.tag in blocks:
                pieces.append("\n")

    visit(node)
    text = ("" if prose else " ").join(pieces)
    return [line for segment in text.splitlines() if (line := clean(segment))]


def _visible(node):
    return not node.hidden() and not any(p.hidden() or p.tag in {"head", "nav", "footer"} for p in node.ancestors())


def _card_roots(doc):
    # Start with the deepest ID labels. Count labels upward to separate adjacent
    # cards even when Meta supplies only generated class names.
    ids, counts, descendants = {}, Counter(), set()
    for n in reversed(doc.nodes):
        if n in descendants or not _visible(n):
            continue
        direct = " ".join(s for s in n.parts if isinstance(s, str))
        if not re.search(r"\b(?:id|identyfikator|library|biblioteki)\b", direct, re.I):
            # The label and ID may be separate inline children.
            if not any(
                isinstance(s, Node)
                and re.search(
                    r"^(?:library id|identyfikator biblioteki|id biblioteki)\s*:?\s*$",
                    " ".join(t for t in s.parts if isinstance(t, str)).strip(),
                    re.I,
                )
                for s in n.parts
            ):
                continue
        match = ID.search(n.words())
        if match:
            ids[n] = match[1]
            for parent in n.ancestors():
                counts[parent] += 1
                descendants.add(parent)
    for leaf, ad_ref in sorted(ids.items(), key=lambda entry: entry[0].index):
        root = leaf
        for parent in leaf.ancestors():
            if (
                counts[parent] > 1
                or parent.tag in {"main", "html", "body", "", "nav"}
                or parent.attr("role") in {"main", "feed"}
            ):
                break
            # Chrome around a single result can otherwise swallow its toolbar.
            if any(isinstance(s, Node) and s.tag in {"nav", "header", "footer", "form"} for s in parent.parts) and root is not leaf:
                break
            root = parent
            if root.tag == "article" or root.attr("role") == "article":
                break
        yield ad_ref, root


def _html_card(ad_ref, root):
    lines = _lines(root)
    sponsor = next((i for i, s in enumerate(lines) if SPONSORED.fullmatch(s)), None)
    prefix = lines if sponsor is None else lines[:sponsor]
    card = {"id": ad_ref, "provider": "meta-ad-library"}
    for s in prefix:
        if STATUS.fullmatch(s):
            card["status"] = s
        elif DATE.search(s):
            card["daty_jak_na_karcie"] = s
        elif m := re.fullmatch(r"(?:reklamodawca|advertiser|page name|nazwa strony)\s*:\s*(.+)", s, re.I):
            card["page_name"] = m[1]
    if sponsor is not None and sponsor > 0 and "page_name" not in card:
        name = lines[sponsor - 1]
        if not (ID.search(name) or STATUS.fullmatch(name) or DATE.search(name) or CHROME.fullmatch(name)):
            card["page_name"] = name
    if "page_name" not in card:
        actors = set()
        for n in root.descendants():
            if n.tag != "a" or not n.attr("href"):
                continue
            link = urlsplit(urljoin(LIBRARY, n.attr("href")))
            path = link.path.strip("/")
            page_link = (
                link.hostname in {"www.facebook.com", "facebook.com", "m.facebook.com"}
                and (
                    path.startswith(("people/", "pages/"))
                    or path == "ads/library"
                    and "view_all_page_id" in parse_qs(link.query)
                    or re.fullmatch(r"[\w.]+", path)
                    and path not in {"ads", "privacy", "help", "login", "l.php"}
                )
            )
            name = n.words()
            if page_link and name and not CHROME.fullmatch(name):
                actors.add(name)
        if len(actors) == 1:
            card["page_name"] = actors.pop()
    notice = next((s for s in _lines(root, prose=True) if REMOVED.search(s)), None)
    if notice:
        card.update(removal_notice=notice, creative_state="withdrawn")
    else:
        card.update(card_cta(root))
        text = [
            s
            for s in (lines[sponsor + 1:] if sponsor is not None else ())
            if not (CHROME.fullmatch(s) or ID.search(s) or STATUS.fullmatch(s))
        ]
        if not text:
            text = [m[1] for ln in lines if (m := re.match(r"^(?:tekst reklamy|ad text)\s*:\s*(.+)", ln, re.I))]
        if not text and (root.tag == "article" or root.attr("role") == "article"):
            for child in root.descendants():
                if child.tag != "p":
                    continue
                value = child.words()
                if (
                    value
                    and value != card.get("page_name")
                    and not ID.search(value)
                    and not STATUS.fullmatch(value)
                    and not DATE.search(value)
                    and not CHROME.fullmatch(value)
                    and not re.match(r"^(?:reklamodawca|advertiser|page name|nazwa strony)\s*:", value, re.I)
                ):
                    text.append(value)
        if text:
            card.update(text=" ".join(text), creative_state="visible")
        else:
            card["creative_state"] = "not_observed"
    return card


def _parse_html(source, query, require_scope=False):
    doc = Document(source)
    saved = re.search(r"<!--\s*saved from url=\(\d+\)(https?://[^\s<>]+?)\s*-->", source[:4096], re.I)
    urls = [saved[1]] if saved else []
    urls.extend(
        n.attr("href") or n.attr("content")
        for n in doc.nodes
        if (n.tag == "link" and n.attr("rel").lower() == "canonical")
        or (n.tag == "meta" and n.attr("property") == "og:url")
    )
    bound = False
    for url in urls:
        if "q=" in url or "country=" in url:
            if not _scope(url, query):
                raise SourceError("Zapis HTML pochodzi z innego zapytania, kraju lub trybu wyszukiwania Meta.")
            bound = True
    if require_scope and not bound:
        raise SourceError("Brak opisu zapytania w HTML. Wskaż plik dla frazy i kraju w konfiguracji importu.")
    roots = list(_card_roots(doc))
    outside = _lines(doc.root, {node for _, node in roots})
    if any(BLOCKED.search(s) for s in outside):
        raise SourceError("Biblioteka Meta zgłosiła blokadę, wymagane logowanie lub błąd strony.")
    if not roots:
        if any(EMPTY.search(s) for s in outside):
            return []
        raise SourceError("Nierozpoznany układ Meta: brak kart z ID oraz komunikatu o pustym wyniku.")
    rows = []
    for ad_ref, node in roots[: query.limit]:
        media = [n.attr("src") for n in node.descendants() if n.tag in {"img", "video", "audio", "source"} and n.attr("src")]
        rows.append((_html_card(ad_ref, node), f"element:{node.index}", media))
    return rows


def _report(data, query):
    if not isinstance(data, dict) or not isinstance(data.get("wyszukiwania"), list):
        raise SourceError("Nieobsługiwany format zapisu wyników Meta JSON.")
    for index, search in enumerate(data["wyszukiwania"]):
        if not isinstance(search, dict) or search.get("fraza") != query.phrase or not _scope(search.get("url", ""), query):
            continue
        raw_cards = search.get("wybrane_karty")
        if not isinstance(raw_cards, list):
            raise SourceError("Niekompletny zapis Meta: brakuje listy kart.")
        if not raw_cards and (search.get("szacunkowa_liczba_wynikow") != 0 or search.get("liczba_kart_w_odczytanym_widoku") != 0):
            raise SourceError("Zapis nie zawiera kart ani potwierdzenia pustego wyniku.")
        rows = []
        for i, row in enumerate(raw_cards[: query.limit]):
            if not isinstance(row, dict) or not re.fullmatch(r"\d{1,30}", str(row.get("meta_ad_library_id", ""))):
                raise SourceError("Karta zapisu Meta nie zawiera poprawnego ID biblioteki.")
            card = {"id": str(row["meta_ad_library_id"]), "provider": "meta-ad-library"}
            for src, dest in (
                ("nazwa_na_karcie", "page_name"),
                ("daty_jak_na_karcie", "daty_jak_na_karcie"),
                ("status", "status"),
                ("tekst", "text"),
                ("komunikat_platformy", "removal_notice"),
                ("obserwacja", "observer_note"),
            ):
                if isinstance(row.get(src), str) and row[src].strip():
                    card[dest] = clean(row[src])
            card["creative_state"] = (
                "withdrawn"
                if "removal_notice" in card
                else "visible"
                if "text" in card
                else "withdrawn_reported"
                if REMOVED.search(card.get("observer_note", ""))
                else "not_observed"
            )
            if isinstance(data.get("data"), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["data"]):
                card["observation_date"] = data["data"]
            rows.append((card, f"/wyszukiwania/{index}/wybrane_karty/{i}", []))
        return rows
    raise SourceError("Brak zapisanego wyniku Meta dla tej frazy, kraju i wyszukiwania dokładnego.")


def _allowed_url(url, navigation):
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in {None, 443}:
        return False
    if navigation:
        return host == "www.facebook.com" and parsed.path.rstrip("/") == "/ads/library"
    return host in {"www.facebook.com", "facebook.com"} or host.endswith((".fbcdn.net", ".facebook.net"))


def _local_media(path, references):
    paths = []
    root = path.parent.resolve()
    for src in references:
        url = urlsplit(src)
        rel = Path(unquote(url.path))
        if url.scheme or url.netloc or rel.is_absolute() or rel.drive or ".." in rel.parts or len(rel.parts) < 2:
            continue
        if rel.parts[0] not in {path.stem + "_files", path.stem + ".files"} or rel.suffix.lower() not in IMAGES | AUDIO | VIDEO:
            continue
        actual = (root / rel).resolve()
        if actual.is_relative_to(root / rel.parts[0]) and actual.is_file() and actual not in paths:
            paths.append(actual)
    return tuple(paths)


def _archive(archive, raw, suffix):
    sha = hashlib.sha256(raw).hexdigest()
    path = archive / (sha + suffix)
    if not path.exists():
        temporary = archive / (uuid4().hex + ".tmp")
        temporary.write_bytes(raw)
        temporary.replace(path)
    return path, sha


def _card_screenshot(page, index, ad_ref, archive, deadline):
    if deadline - monotonic() < 1:
        return None, "Limit czasu pozyskania zrzutu"
    handle = page.evaluate_handle("index => window.__scamGraphVisibleNodes[index]", index)
    try:
        element = handle.as_element()
        if element is None:
            return None, "Element karty przestał być dostępny"
        boundary = element.evaluate(
            r"""el => {
          const box = el.getBoundingClientRect();
          if (!el.isConnected || box.width < 1 || box.height < 1 || box.width * box.height > 8000000) return false;
          if (el.matches('article,[role=article]')) return true;
          // For generic div layouts, require a repeated card container next to this one.
          return Array.from(el.parentElement?.children || []).some(sibling =>
            sibling !== el && sibling.tagName === el.tagName &&
            /(?:Library ID|Identyfikator biblioteki|ID biblioteki)\s*:\s*\d+/i.test(sibling.innerText || ''));
        }"""
        )
        if not boundary or ID.findall(element.inner_text()) != [ad_ref]:
            return None, "Brak jednoznacznej granicy widocznej karty z tym ID"
        raw = element.screenshot(type="png", timeout=1200, animations="disabled")
        if not element.evaluate("el => el.isConnected") or ID.findall(element.inner_text()) != [ad_ref]:
            return None, "Karta zmieniła się podczas zapisu zrzutu"
        path, _ = _archive(archive, raw, ".png")
        return path, None
    finally:
        handle.dispose()


def _live(options, query):
    if not isinstance(options.get("permission"), str) or not options["permission"].strip():
        raise SourceError("Brak potwierdzonego uprawnienia Meta do automatycznego odczytu WWW. Dostępny jest import ręczny.")
    headless = options.get("headless", True)
    if not isinstance(headless, bool):
        raise SourceError("Pole headless wymaga wartości JSON true lub false.")
    user_agent = options.get("user_agent")
    if "user_agent" in options and (not isinstance(user_agent, str) or not user_agent.strip() or "\n" in user_agent or "\r" in user_agent):
        raise SourceError("Pole user_agent musi zawierać poprawny, niepusty ciąg User-Agent.")
    if find_spec("playwright") is None:
        runtime = Path(__file__).resolve().parents[2] / ".private-discovery" / "playwright-runtime"
        if (runtime / "playwright" / "__init__.py").is_file() and str(runtime) not in sys.path:
            sys.path.append(str(runtime))
    try:
        from playwright.sync_api import sync_playwright, Error as BrowserError
    except ImportError as exc:
        raise SourceError(f"Nie udało się załadować Playwright w procesie pobierania (moduł: {exc.name or 'playwright'}).") from exc
    archive = Path(options.get("archive_dir", ".private-discovery/meta"))
    archive.mkdir(parents=True, exist_ok=True)
    phase = "uruchamianie lokalnego Chrome"
    navigation_error = []
    main_status = None
    with sync_playwright() as driver:
        try:
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-infobars",
            ]
            if options.get("no_sandbox"):
                launch_args.append("--no-sandbox")

            with driver.chromium.launch(
                channel=options.get("channel", "chrome"),
                headless=headless,
                args=launch_args,
                timeout=15000,
            ) as browser:
                context_kwargs = {
                    "service_workers": "block",
                    "locale": "pl-PL",
                    "timezone_id": "Europe/Warsaw",
                    "accept_downloads": False,
                    "viewport": {"width": 1366, "height": 900},
                    "screen": {"width": 1366, "height": 900},
                    "color_scheme": "light",
                    "extra_http_headers": {
                        "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
                        "Upgrade-Insecure-Requests": "1",
                    },
                }
                if user_agent:
                    context_kwargs["user_agent"] = user_agent
                if options.get("proxy"):
                    context_kwargs["proxy"] = options["proxy"]

                context = browser.new_context(**context_kwargs)
                context.add_init_script(
                    """
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.chrome = { runtime: {} };
                    Object.defineProperty(navigator, 'languages', {get: () => ['pl-PL', 'pl', 'en-US', 'en']});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                """
                )

                deadline = monotonic() + 32
                page = context.new_page()

                def route(request_route):
                    req = request_route.request
                    if monotonic() < deadline and _allowed_url(req.url, req.is_navigation_request()):
                        request_route.continue_()
                    else:
                        request_route.abort()

                session = context.new_cdp_session(page)
                frame_id = session.send("Page.getFrameTree")["frameTree"]["frame"]["id"]

                def check_response(event):
                    nonlocal main_status
                    params = {"requestId": event["requestId"]}
                    status = event.get("responseStatusCode", 0)
                    main_document = event.get("frameId") == frame_id and event["resourceType"] == "Document"
                    if main_document and status:
                        main_status = status
                    if 300 <= status < 400 and status != 304:
                        if main_document:
                            navigation_error.append(f"Meta zwróciła przekierowanie HTTP {status}.")
                        method, params = "Fetch.failRequest", {**params, "errorReason": "BlockedByClient"}
                    else:
                        method = "Fetch.continueRequest"
                    try:
                        session.send(method, params)
                    except BrowserError as exc:
                        # Żądanie anulowane w międzyczasie (nowa nawigacja, przerwane pobranie,
                        # zamknięcie strony): CDP zwraca "Invalid InterceptionId". Nie ma już czego
                        # wznawiać ani blokować, a wyjątek w obsłudze zdarzenia przerywał całą frazę.
                        if "Invalid InterceptionId" not in str(exc) and "closed" not in str(exc).lower():
                            raise

                session.on("Fetch.requestPaused", check_response)
                session.send("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Response"}]})
                context.route("**/*", route)
                page.set_default_timeout(10000)
                phase = "otwieranie strony wyników"

                target_url = search_url(query)
                response = page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
                if response is None:
                    raise SourceError("Brak odpowiedzi HTTP dla dokumentu Biblioteki Meta.")

                def page_error(message):
                    detail = f"Dokument Meta HTTP {getattr(response, 'status', '?')}. {message}"
                    try:
                        screenshot = page.screenshot(timeout=2000, full_page=False)
                        path, _ = _archive(archive, screenshot, ".png")
                    except (BrowserError, OSError):
                        return SourceError(detail + " Nie udało się zapisać zrzutu widoku.")
                    return SourceError(f"{detail} Zrzut widoku: {path.name}")

                # === Rozwiązywanie rd_challenge ===
                # === Rozwiązywanie rd_challenge (stabilna wersja) ===
                if response.status == 403:
                    body = ""
                    try:
                        body = page.content()
                    except BrowserError:
                        pass

                    challenge_match = re.search(
                        r"""fetch\s*\(\s*['"](/__rd_verify_[^'"]+)['"]""",
                        body,
                        re.I,
                    )
                    if not challenge_match:
                        try:
                            title = clean(page.title())[:120]
                        except BrowserError:
                            title = ""
                        raise page_error(f"Odmowa dostępu. Tytuł strony: {title or '(pusty)'}.")

                    challenge_path = challenge_match.group(1)
                    challenge_url = "https://www.facebook.com" + challenge_path
                    phase = "rozwiązywanie rd_challenge"

                    try:
                        # POST poza kontekstem strony – nie niszczy execution context
                        challenge_resp = context.request.post(
                            challenge_url,
                            headers={
                                "Origin": "https://www.facebook.com",
                                "Referer": target_url,
                                "Accept": "*/*",
                                "Sec-Fetch-Site": "same-origin",
                                "Sec-Fetch-Mode": "cors",
                                "Sec-Fetch-Dest": "empty",
                            },
                            timeout=10000,
                        )
                        # Cookie rd_challenge powinno być już w context
                        page.wait_for_timeout(600)

                        # Ponowne załadowanie strony wyników z cookie
                        response = page.goto(target_url, wait_until="domcontentloaded", timeout=18000)
                        if response is None:
                            raise SourceError("Brak odpowiedzi po rozwiązaniu challenge.")
                    except BrowserError as exc:
                        raise page_error(f"Nie udało się rozwiązać rd_challenge: {exc}") from exc

                if response.status == 403:
                    # Drugi raz 403 – challenge nie pomógł (prawdopodobnie IP)
                    raise page_error(
                        "Meta nadal zwraca 403 po próbie rozwiązania challenge. "
                        "Najpewniej blokada IP. Spróbuj headless=false + residential proxy "
                        "lub przejdź na tryb import (ręcznie zapisany HTML)."
                    )

                if response.status == 403:
                    raise page_error(
                        "Meta nadal zwraca 403 po próbie rozwiązania challenge. "
                        "Spróbuj headless=false + residential proxy lub ręczny import HTML."
                    )

                if response.status >= 400:
                    title = clean(page.title())[:120]
                    raise page_error(f"Błąd pobrania. Tytuł strony: {title or '(pusty)'}.")

                # Reszta logiki (odczyt DOM, scroll, screenshoty) – bez zmian
                phase = "odczyt wyrenderowanego dokumentu"
                seen = set()
                scrolls = 0
                while monotonic() < deadline:
                    source = page.evaluate(
                        """() => {
                      const nodes = [null, document.documentElement];
                      const copy = (node, parent) => {
                        if (node.nodeType === Node.TEXT_NODE) {parent.append(document.createTextNode(node.data));return}
                        if (node.nodeType !== Node.ELEMENT_NODE ||
                            node.matches('script,style,noscript,template,iframe,input,textarea,select,svg,canvas,[contenteditable]') ||
                            node.hidden || node.getAttribute('aria-hidden') === 'true') return;
                        const css = getComputedStyle(node);
                        if (css.display === 'none' || css.visibility === 'hidden') return;
                        const el = document.createElement(node.localName);
                        nodes.push(node);
                        if (node.hasAttribute('role')) el.setAttribute('role',node.getAttribute('role'));
                        if (node.hasAttribute('aria-label')) el.setAttribute('aria-label',node.getAttribute('aria-label'));
                        for (const key of ['title','alt','data-href','data-url'])
                          if (node.hasAttribute(key)) el.setAttribute(key,node.getAttribute(key));
                        if (node.localName === 'a' && node.hasAttribute('href') && /^https?:$/.test(node.protocol))
                          el.setAttribute('href', node.href);
                        parent.append(el);
                        for (const child of node.childNodes) copy(child, el);
                      };
                      const html = document.createElement('html'); copy(document.body, html);
                      window.__scamGraphVisibleNodes = nodes;
                      return html.outerHTML;
                    }"""
                    )
                    if len(source.encode("utf8")) > MAX_BYTES:
                        raise SourceError("Wyrenderowany dokument Meta przekracza limit rozmiaru.")
                    try:
                        rows = _parse_html(source, query)
                    except SourceError as exc:
                        if not str(exc).startswith("Nierozpoznany układ"):
                            raise page_error(str(exc)) from exc
                        page.wait_for_timeout(600)
                        continue
                    if not rows and not seen:
                        file, sha = _archive(archive, source.encode("utf8"), ".html")
                        observation = {
                            "observed_at": datetime.now(timezone.utc).isoformat(),
                            "url": search_url(query),
                            "main_document_http_status": response.status,
                            "result": "empty",
                            "visible_html": file.name,
                            "sha256": sha,
                        }
                        _archive(archive, json.dumps(observation, ensure_ascii=False).encode("utf8"), ".json")
                        return
                    new_rows = []
                    for row in rows:
                        ad_ref = row[0]["id"]
                        if ad_ref not in seen:
                            seen.add(ad_ref)
                            new_rows.append(row)
                        if len(seen) >= query.limit:
                            break
                    if new_rows:
                        raw = source.encode("utf-8")
                        file, sha = _archive(archive, raw, ".html")
                        for card, locator, media in new_rows:
                            card["main_document_http_status"] = response.status
                            try:
                                index = int(locator.split(":")[1])
                                image, reason = _card_screenshot(page, index, card["id"], archive, deadline)
                            except BrowserError:
                                image, reason = None, "Przeglądarka nie utrwaliła widocznego elementu karty"
                            if reason:
                                card["screenshot_missing_reason"] = reason
                            published_at = monotonic()
                            yield file, sha, [(card, locator, media)], image
                            deadline += monotonic() - published_at
                    if not new_rows or len(seen) >= query.limit or scrolls >= 3 or monotonic() + 1.2 >= deadline:
                        return
                    scrolls += 1
                    page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
                    page.wait_for_timeout(800)
                raise page_error("Limit czasu Meta: brak rozpoznanych kart lub potwierdzenia pustego wyniku.")
        except BrowserError as exc:
            error_code = re.search(r"net::(ERR_[A-Z0-9_]+)", str(exc))
            reason = error_code[1] if error_code else type(exc).__name__
            if main_status is not None:
                reason += f" (dokument HTTP {main_status})"
            raise SourceError(navigation_error[0] if navigation_error else f"Meta: {phase} — {reason}.") from exc

def fetch(options: dict, query: Query):
    """Yield one source-grounded finding per card in the observed results."""
    mode = options.get("mode", "import")
    if not 1 <= query.limit <= 500 or not query.phrase.strip() or not re.fullmatch(r"[A-Z]{2}", query.country):
        raise SourceError("Niepoprawne zapytanie Meta (fraza, kod kraju lub limit).")
    if mode == "live":
        batches = _live(options, query)
    elif mode in {"replay", "import"}:
        selected = options.get("imports", {}).get(query.phrase)
        value = selected or options.get("path")
        if not value:
            raise SourceError("Brak ręcznie zapisanego wyniku Meta dla tej frazy.")
        path = Path(value)
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise SourceError("Zapis wyników Meta przekracza limit 12 MiB.")
            sha = hashlib.sha256(raw).hexdigest()
            if path.suffix.lower() == ".json":
                rows = _report(json.loads(raw.decode("utf-8-sig")), query)
            elif path.suffix.lower() in {".html", ".htm"}:
                charset = re.search(br"""charset\s*=\s*["']?([\w-]+)""", raw[:4096], re.I)
                codec = charset[1].decode("ascii") if charset else "utf-8-sig"
                rows = _parse_html(raw.decode(codec), query, require_scope=not selected)
            else:
                raise SourceError("Import wyników Meta przyjmuje zapisany HTML lub raport JSON.")
        except (LookupError, UnicodeError, json.JSONDecodeError) as exc:
            raise SourceError("Uszkodzony zapis wyników Meta (kodowanie lub składnia JSON).") from exc
        except OSError as exc:
            raise SourceError(f"Nie można odczytać lokalnego zapisu Meta ({type(exc).__name__}).") from exc
        batches = [(path, sha, rows, None)]
    else:
        raise SourceError("Nieznany tryb adaptera Meta.")
    kind = "library" if mode == "live" else ("synthetic" if options.get("synthetic") is True else "upload")
    try:
        for path, sha, rows, image in batches:
            observed_at = datetime.now(timezone.utc).isoformat() if mode == "live" else None
            for card, locator, references in rows:
                missing = not all(card.get(key) for key in ("page_name", "status", "daty_jak_na_karcie", "text"))
                reason = f'Wynik wyszukiwania dokładnej frazy „{query.phrase}” ({query.country}).'
                yield Finding(
                    card["id"],
                    card,
                    reason,
                    missing,
                    path,
                    locator,
                    image=image,
                    observed_at=observed_at,
                    source_kind=kind,
                    source_sha256=sha,
                    media=_local_media(path, references),
                )
    finally:
        # Gdy konsument przestaje czytać przed końcem (limit kart, błąd zapisu), generator _live
        # trzyma otwarte sync_playwright() i nie jest zwalniany wraz z tym generatorem, więc
        # następna fraza w tym samym procesie dostawała "Playwright Sync API inside the asyncio loop".
        if mode == "live":
            batches.close()
