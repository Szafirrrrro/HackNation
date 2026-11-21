"""Static HTML extraction. Document order and element numbers include hidden elements."""
import json
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from .sources import clean, evidence, fact, pixel_from_url, script_pixels
from .page_text import consent_candidate, transcript
from .landing_fields import badge, cart_context, claim_block, nodes_below, rating_icons, tile_name

VOID = set("area base br col embed hr img input link meta param source track wbr".split())
HIDDEN = set("script style template noscript textarea input select option iframe svg canvas".split())
ENTRY = {"comment", "fb-comment", "review", "testimonial", "reply", "comment-item", "review-item", "comment-reply",
         "review_box", "review-box"}
TEXT = {"fb-comment-text", "comment-text", "review-text", "comment-content", "review-body",
        "comment-body", "testimonial-text", "reviewbody", "description", "text"}
AUTHORS = {"author", "review-author", "comment-author", "fb-comment-author", "reviewer", "fn"}
TIME = {"time", "date", "timestamp", "comment-date", "review-date", "datepublished"}


class Node:
    def __init__(self, tag, attrs, parent, index, line, marker=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.index, self.line, self.marker = index, line, marker
        self.parts = []
        self.keys = set((self.attr("class") + " " + self.attr("itemprop")).lower().split())

    def attr(self, key):
        return self.attrs.get(key) or ""

    def hidden(self):
        return (self.tag in HIDDEN or "hidden" in self.attrs or "contenteditable" in self.attrs
                or self.attr("aria-hidden").lower() == "true"
                or re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", self.attr("style"), re.I))

    def words(self, skip_entries=False):
        if self.hidden():
            return ""
        parts = (p.words(skip_entries) if isinstance(p, Node) else p for p in self.parts
                 if not (skip_entries and isinstance(p, Node) and is_entry(p)))
        return clean(" ".join(parts))

    def descendants(self):
        for part in self.parts:
            if isinstance(part, Node) and not part.hidden() and not is_entry(part):
                yield part
                yield from part.descendants()

    def ancestors(self):
        node = self.parent
        while node:
            yield node
            node = node.parent


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Node("", [], None, 0, 1)
        self.current = self.root
        self.nodes = []
        self.marker = None
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs):
        if tag in {"p", "li"} and self.current.tag == tag:
            self.current = self.current.parent
        node = Node(tag, attrs, self.current, len(self.nodes) + 1, self.getpos()[0], self.marker)
        self.marker = None
        self.current.parts.append(node)
        self.nodes.append(node)
        if tag not in VOID:
            self.current = node

    def handle_endtag(self, tag):
        node = self.current
        while node.parent:
            if node.tag == tag:
                self.current = node.parent
                break
            node = node.parent

    def handle_data(self, data):
        self.current.parts.append(data)
        if data.strip():
            self.marker = None

    def handle_comment(self, text):
        self.marker = re.match(r"\s*(COMMENT|REPLY)\s+(\d+)([a-z]*)\s*:", text, re.I)


def is_entry(node):
    return bool(node.keys & ENTRY or node.attr("itemtype").rstrip("/").split("/")[-1] in {"Review", "Comment"})


def html_text(path):
    raw = path.read_bytes()
    charset = re.search(br"""charset\s*=\s*["']?([\w-]+)""", raw[:4096], re.I)
    try:
        return raw.decode(charset[1].decode() if charset else "utf-8-sig")
    except (UnicodeError, LookupError):
        return raw.decode("cp1250", errors="replace")


def library_identity(node):
    if node.tag == "link" and node.attr("rel").lower() == "canonical":
        attr = "href"
    elif node.tag == "meta" and node.attr("property") == "og:url":
        attr = "content"
    else:
        return None
    try:
        url = urlsplit(node.attr(attr))
        if (url.hostname not in {"facebook.com", "www.facebook.com", "m.facebook.com"} or
                url.path.rstrip("/") != "/ads/library"):
            return None
        ids = parse_qs(url.query).get("id", [])
        return attr, ids[0] if len(ids) == 1 and ids[0].isdecimal() else None
    except ValueError:
        return None


RULES = {
    "obietnica_zysku": r"\b(zarobi\w*|zysk\w*|dochód|dochodu|zwrot z inwestycji|guaranteed return|profit\w*)\b",
    "efekt_zdrowotny": r"\b(wylecz\w*|leczy|schud\w*|(?:pomaga|wsparcie) w odchudzaniu|waga spadła|cofa cukrzycę|cures?|weight loss|(?:obniż\w*|zmniejsz\w*|redukuj\w*)\s+(?:poziom\s+)?(?:cholesterol\w*|ciśnieni\w*|glikemi\w*)|(?:lowers?|reduces?) (?:blood pressure|cholesterol))\b",
    "presja_czasu": r"(ostatni[ae] (szansa|miejsca)|tylko (dziś|dzisiaj|do)|pozostało|kończy się|limited time|last chance)",
    "wezwanie_do_zapłaty": r"\b(wpłać|wpłacić|wpłat\w*|zapłać|depozyt\w*|pay now|deposit)\b",
    "wezwanie_do_podania_danych": r"(?:podaj|wpisz|prześlij|enter your)\s+(?:(?:swój|swoje|nam|your)\s+)?(?:dane|imię|adres|numer|telefon|e-?mail|pesel|name|phone)|wypełnij formularz",
}
AMOUNT = re.compile(r"(?<!\w)(\d+(?:[ .]\d{3})*(?:[,.]\d{1,2})?)\s*(zł(?:otych)?|PLN|EUR|USD|€|\$)(?!\w)", re.I)
NAME = re.compile(r"\b[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]{2,}(?:\s+(?:[A-ZĄĆĘŁŃÓŚŹŻ][\w.-]+|S\.A\.)){1,3}\b")
PRODUCT = re.compile(r"\b(?:platform(?:a|y|ie|ę)|produkt|preparat|program)\s+[„«\"]?([A-ZĄĆĘŁŃÓŚŹŻ][\w-]+(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][\w-]+){0,2})")


def landing(path, artifact, *, ad_card=False):
    source = html_text(path)
    doc = Document(source)
    result = {key: [] for key in ("titles", "headings", "content", "products", "prices", "amounts", "names",
                                  "opinions", "signals", "pixels", "rating_badges", "cart_balances", "consent_dialogs",
                                  "offer_headings")}
    local_ids, markers, deferred = {}, {}, []
    seen_names = set()

    def ref(n):
        return evidence(artifact, element=n.index, tag=n.tag, line=n.line)

    dialog_ids = set()
    amount_locations = {}

    def record_amount(rows, node, item, amount, product):
        value = ({"amount": amount[1], "currency": amount[2]} if amount else item["value"])
        signature = (id(rows), str(value), product.index if product else None)
        prior = amount_locations.setdefault(signature, set())
        if any(p.index in prior for p in node.ancestors()):
            return
        prior.add(node.index)
        row = {"field": node.attr("itemprop") or "price", **item, "value": value}
        if product:
            row.update(product=product.words(), product_evidence=ref(product))
        rows.append(row)

    def add_signals(value, location, context):
        for kind, rule in RULES.items():
            if re.search(rule, value, re.I):
                result["signals"].append({"kind": kind, "excerpt": value, "context": context, "evidence": location})

    for node in doc.nodes:
        if any(n.hidden() for n in node.ancestors()):
            continue
        if node.tag == "script":
            if node.attr("type").lower() == "application/ld+json":
                try:
                    start = len(result["opinions"])
                    structured(json.loads("".join(node.parts)), ref(node), result)
                    if ad_card:
                        for row in result["opinions"][start:]:
                            row["source_kind"] = "platform_comment" if row.pop("schema_type") == "Comment" else "creative_quote"
                except (ValueError, TypeError):
                    pass
            else:
                for hit in script_pixels("".join(node.parts), artifact):
                    result["pixels"].append(fact(hit["value"], evidence(artifact, **ref(node)["locator"], **hit["evidence"]["locator"])))
        for provider, pixel in pixel_from_url(node.attr("src")):
            result["pixels"].append(fact({"provider": provider, "id": pixel}, ref(node)))
        if node.hidden():
            continue
        aggregate = badge(node, ref)
        if aggregate:
            product_name = tile_name(node)
            if product_name:
                aggregate.update(product=product_name.words(), product_evidence=ref(product_name))
            result["rating_badges"].append(aggregate)
        if consent_candidate(node):
            title = node.words()[:250]
            if re.search(r"cookie|ciastecz", title, re.I) and not any(
                    p.index in dialog_ids for p in node.ancestors()):
                result["consent_dialogs"].append(fact(title, ref(node)))
                dialog_ids.add(node.index)
        if is_entry(node):
            record = opinion(node, ref)
            if ad_card:
                record["source_kind"] = "creative_quote" if node.keys & {"testimonial", "review"} else "platform_comment"
            result["opinions"].append(record)
            if not ad_card and record["text"]:
                add_signals(record["text"], record.get("text_evidence", record["evidence"]), "opinia na stronie")
            marker = node.marker
            if node.attr("id"):
                local_ids.setdefault(node.attr("id"), []).append(record["id"])
            if marker and marker[1].lower() == "comment":
                markers.setdefault(marker[2], []).append(record["id"])
            parent = next((p for p in node.ancestors() if is_entry(p)), None)
            if parent:
                record.update(is_reply=True, parent_id=f"el-{parent.index}")
            else:
                parent_id = node.attr("data-parent-id") or node.attr("data-parent")
                if parent_id:
                    deferred.append((record, local_ids, parent_id.lstrip("#")))
                elif marker and marker[1].lower() == "reply":
                    deferred.append((record, markers, marker[2]))
            continue
        if any(is_entry(p) for p in node.ancestors()):
            continue
        value = node.words(skip_entries=True)
        prop = node.attr("itemprop").lower()
        if prop in {"price", "pricecurrency", "name"} and node.tag == "meta":
            value = clean(node.attr("content"))
        if not value:
            continue
        item = fact(value, ref(node))
        if ad_card and node.tag in {"blockquote", "q"}:
            record = opinion(node, ref)
            record.update(source_kind="creative_quote", text=value)
            result["opinions"].append(record)
        if node.tag == "title":
            result["titles"].append(item)
        if node.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            result["headings"].append(item)
            if any(p.tag == "main" or p.attr("role") == "main" for p in node.ancestors()) and not any(
                    p.tag in {"nav", "header", "footer"} or p.attr("role") in {"dialog", "region", "navigation"}
                    for p in node.ancestors()) and re.search(r"produkt|ofert|tabletki|kapsułki|suplement|żelki", value, re.I):
                result["offer_headings"].append(item)
        if node.keys & {"product-name", "product-link", "platform-link", "offer-name"} or (
                prop == "name" and any(p.attr("itemtype").endswith("/Product") for p in node.ancestors())):
            result["products"].append(item)
        price_markup = prop in {"price", "pricecurrency"} or node.keys & {"price", "product-price"}
        normalized_amount = re.sub(r"(?<=\d)\s*([,.])\s*(?=\d)", r"\1", value)
        amount = AMOUNT.fullmatch(normalized_amount)
        if price_markup or (amount and not any(t.words() == value for t in node.parts if isinstance(t, Node))):
            product = tile_name(node) if amount or prop == "price" else None
            if cart_context(node):
                record_amount(result["cart_balances"], node, item, amount, None)
            elif price_markup or product:
                record_amount(result["prices"], node, item, amount, product)
        # Preserve prose in both semantic articles and leaf blocks of older layouts.
        block = node.tag in {"p", "li", "blockquote", "button", "label", "a", "h1", "h2", "h3", "td", "small"}
        if node.tag in {"div", "section", "main", "article", "span", "body"} and any(
                isinstance(p, str) and p.strip() for p in node.parts):
            block = not any(isinstance(p, Node) and p.tag in {"p", "div", "section", "article", "li", "main"} for p in node.parts)
        if not block:
            continue
        result["content"].append(item)
        if claim_block(node, value):
            add_signals(value, ref(node), "treść strony")
        for amount in AMOUNT.finditer(value):
            detail = fact({"amount": amount[1], "currency": amount[2]}, ref(node))
            result["amounts"].append(detail)
            if re.search(r"(?:cena|koszt|price)\s*[:–-]?\s*$", value[:amount.start()], re.I) and not cart_context(node):
                result["prices"].append(detail)
        for name in NAME.findall(value):
            if name not in seen_names:
                result["names"].append(fact(name, ref(node)))
                seen_names.add(name)
        for product in PRODUCT.findall(value):
            result["products"].append(fact(product, ref(node)))
    for record, mapping, key in deferred:
        record["is_reply"] = True
        if len(mapping.get(key, [])) == 1 and mapping[key][0] != record["id"]:
            record["parent_id"] = mapping[key][0]
    for order, record in enumerate(result["opinions"], 1):
        record["order"] = order
    if not ad_card:
        result["reading_text"] = transcript(doc, artifact, dialog_ids)
    return result


def opinion(node, ref):
    descendants = list(node.descendants())

    def select(keys):
        return next((n for n in descendants if n.keys & keys), None)

    def visible(n):
        if not n:
            return None
        return n.words(True) or clean(n.attr("content") or n.attr("datetime")) or None

    body = select(TEXT - {"comment-body"}) or select({"comment-body"})
    author = select(AUTHORS)
    product = None
    if node.keys & {"review_box", "review-box"}:
        body = body or select({"discription_aa", "review-description"})
        author = author or select({"second_pp"})
        product = select({"first_p", "product-name", "review-product"})
    stamp = select(TIME) or next((n for n in descendants if n.tag == "time"), None)
    if not stamp:
        meta = select({"fb-comment-meta", "comment-meta"})
        if meta:
            stamp = next((n for n in meta.descendants() if re.search(r"\b(temu|ago|wczoraj|yesterday)\b", n.words(), re.I)), None)
    rating = select({"rating", "ratingvalue", "review-rating", "stars"})
    reactions = []
    for n in descendants:
        keys = n.keys | {n.attr("data-reaction").lower()}
        kind = next((kind for kind, labels in {"like": {"like", "likes", "meta-likes", "like-count", "likes-count"},
                                               "love": {"love", "hearts"}, "helpful": {"helpful", "helpful-count"},
                                               "reaction": {"reaction-count"}}.items() if keys & labels), None)
        if kind or n.attr("data-reaction"):
            raw = visible(n)
            count = re.search(r"(?<![\d.,])\d+(?:[ \u00a0]\d{3})*(?![\d.,kKmM])\b", raw or "")
            reactions.append({"kind": kind or clean(n.attr("data-reaction")), "display": raw,
                              "count": int("".join(count[0].split())) if count else None, "evidence": ref(n)})
    if body:
        body_text = visible(body)
    else:
        excluded = {author, stamp, rating}
        def prose(n):
            if n in excluded or n.hidden() or (n is not node and is_entry(n)) or n.keys & {
                    "comment-meta", "fb-comment-meta", "meta-likes", "like-count", "likes", "helpful-count", "reaction-count"}:
                return ""
            return clean(" ".join(prose(p) if isinstance(p, Node) else p for p in n.parts))
        body_text = prose(node)
    record = {"id": f"el-{node.index}", "source_kind": "landing_review", "text": body_text or "",
            "signature": visible(author), "visible_time": visible(stamp), "rating": visible(rating),
            "reactions": reactions, "is_reply": bool(node.keys & {"reply", "fb-reply", "comment-reply"}),
            "parent_id": None, "authenticity": None, "purchase_verified": None, "evidence": ref(node)}
    if body:
        record["text_evidence"] = ref(body)
    if product:
        record.update(product=visible(product), product_evidence=ref(product))
    if author:
        record["signature_evidence"] = ref(author)
    if not record["rating"]:
        icon_group = next((n for n in nodes_below(node) if n.tag == "svg" and "rating" in n.keys), None)
        if icon_group:
            icons = rating_icons(icon_group)
            if icons:
                record.update(rating=icons["rating"], rating_evidence=ref(icon_group))
    return record


def structured(obj, source, result, pointer="", parent_id=None, product=None):
    if isinstance(obj, list):
        for i, child in enumerate(obj):
            structured(child, source, result, f"{pointer}/{i}", parent_id, product)
    if not isinstance(obj, dict):
        return
    kind = obj.get("@type")
    ref = {**source, "locator": {**source["locator"], "json_pointer": pointer}}
    if kind in ("Review", "Comment") and isinstance(obj.get("reviewBody") or obj.get("text"), str):
        author = obj.get("author")
        rating = obj.get("reviewRating")
        rating = rating.get("ratingValue") if isinstance(rating, dict) else None
        rid = f"ld-{source['locator']['element']}{pointer}"
        counts = []
        stats = obj.get("interactionStatistic") or []
        for stat in stats if isinstance(stats, list) else [stats]:
            if not isinstance(stat, dict):
                continue
            action = stat.get("interactionType")
            if isinstance(action, dict):
                action = action.get("@type")
            if isinstance(action, str) and action.rsplit("/", 1)[-1] in {"LikeAction", "DislikeAction"}:
                raw = stat.get("userInteractionCount")
                counts.append({"kind": "like" if action.endswith("LikeAction") else "dislike",
                               "count": int(raw) if str(raw).isdecimal() else None,
                               "display": clean(raw) if raw is not None else None, "evidence": ref})
        result["opinions"].append({"id": rid, "source_kind": "landing_review", "schema_type": kind,
                                   "text": clean(obj.get("reviewBody") or obj["text"]),
                                   "signature": clean(author.get("name", "")) if isinstance(author, dict) else clean(author or "") or None,
                                   "visible_time": clean(obj.get("datePublished", "")) or None,
                                   "rating": clean(rating) if rating is not None else None, "is_reply": parent_id is not None, "parent_id": parent_id,
                                   "reactions": counts, "authenticity": None, "purchase_verified": None, "evidence": ref})
        parent_id = rid
    if kind == "Product" and isinstance(obj.get("name"), str):
        product = fact(clean(obj["name"]), ref)
        result["products"].append(product)
    if kind == "Offer" and "price" in obj:
        price = fact({"amount": clean(obj["price"]), "currency": clean(obj.get("priceCurrency", "")) or None}, ref)
        if product:
            price.update(product=product["value"], product_evidence=product["evidence"])
        result["prices"].append(price)
    for key, value in obj.items():
        if isinstance(value, (dict, list)):
            structured(value, source, result, pointer + "/" + key.replace("~", "~0").replace("/", "~1"),
                       parent_id if key in {"comment", "reply", "replies"} else None,
                       product if key in {"offers", "offer"} else None)
