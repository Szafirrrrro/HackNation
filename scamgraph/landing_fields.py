"""Context-sensitive fields in saved storefront markup."""
import re

from .sources import clean


def nodes_below(node):
    for child in node.parts:
        if not isinstance(child, str):
            yield child
            yield from nodes_below(child)


def rating_icons(svg):
    icons = [(n.attr("href") or n.attr("xlink:href")).split("#")[-1] for n in nodes_below(svg) if n.tag == "use"]
    weights = {"stars-full-star": 1, "stars-half-star": 0.5, "stars-empty-star": 0}
    if icons and all(i in weights for i in icons):
        return {"rating": f"{sum(weights[i] for i in icons):g}/{len(icons)}", "icons": icons}


def badge(node, ref):
    if not (node.keys & {"jdgm-preview-badge", "aggregate-rating", "aggregaterating"}
            or node.attr("itemtype").endswith("/AggregateRating")):
        return None
    children = [node, *nodes_below(node)]
    rating = count = None
    for part in children:
        rating = rating or part.attr("data-average-rating")
        count = count or part.attr("data-number-of-reviews")
        if part.attr("itemprop") in {"ratingValue", "reviewCount", "ratingCount"}:
            value = part.attr("content") or part.words()
            if part.attr("itemprop") == "ratingValue":
                rating = rating or value
            else:
                count = count or value
        if "jdgm-prev-badge__text" in part.keys:
            display = clean(" ".join(s for s in part.parts if isinstance(s, str)))
            match = re.search(r"(\d+(?:[.,]\d+)?)\s*/\s*(\d[\d\s]*)\s*(?:opini|review)", display, re.I)
            if match:
                return {"value": display, "rating": match[1], "count": int("".join(match[2].split())),
                        "evidence": ref(part)}
    if rating or count:
        return {"value": clean(f"{rating or '—'} · {count or '—'}"), "rating": rating,
                "count": int(count) if count and count.isdecimal() else None, "evidence": ref(node)}


def tile_name(node):
    for parent in node.ancestors():
        if (parent.attr("itemtype").endswith("/Product")
                or parent.keys & {"producttile", "product-card", "product-tile", "product-item", "product_card", "grid-view-item"}):
            return next((n for n in parent.descendants() if n.words() and (
                n.attr("itemprop") == "name" or n.keys & {"producttile__name", "product-name", "product-title",
                                                           "product-card__title", "product-link", "offer-name", "grid-view-item__title"}
                or n.tag in {"h2", "h3", "h4"})), None)


def cart_context(node):
    for p in (node, *node.ancestors()):
        if p.tag in {"body", "html", "main"}:
            break
        if re.search(r"(?:cart|basket)[_-]*(?:sub)?total|(?:sub)?total[_-]*(?:cart|basket)",
                     p.attr("id") + " " + p.attr("class"), re.I):
            return True
        if any(isinstance(t, str) and re.fullmatch(r"\s*(?:(?:mój|twój|my|your)\s+)?(?:koszyk|cart|basket)\s*", t, re.I)
               for t in p.parts):
            return True
        if p.tag in {"div", "a", "button"} and len(p.parts) <= 10 and any(
                getattr(t, "tag", "") in {"span", "strong", "b"} and
                re.fullmatch(r"(?:mój|twój|my|your)\s+(?:koszyk|cart|basket)", t.words(), re.I) for t in p.parts):
            return True
    return False


def claim_block(node, value):
    if any(p.tag == "nav" or p.attr("role") in {"menu", "navigation"}
           or p.keys & {"menu-item", "submenu", "dropdown-menu"} for p in (node, *node.ancestors())):
        return False
    if re.fullmatch(r"(?:zaloguj się\s*/\s*)?zarejestruj się|odchudzanie|weight loss", value, re.I):
        return False
    # Match the smallest prose block; wrappers around several paragraphs add no new occurrence.
    return not any(n.tag in {"li", "p", "ul", "section", "blockquote", "h2", "h3"} for n in node.descendants())
