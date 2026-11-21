"""A card describes one delivery. All field paths refer to the original JSON."""
import re

from .sources import address, clean, evidence, fact

FIELDS = {
    "ad_ref": ("id", "ad.id", "source.ad_ref", "meta_ad_library_id", "ad_archive_id"),
    "advertiser_ref": ("page_id", "advertiser.business_id", "advertiser_ref"),
    "page_name": ("page_name", "advertiser.business_name", "nazwa_na_karcie"),
    "text": ("ad_creative_bodies", "body", "text", "ad.text", "ad_creative_link_descriptions"),
    "title": ("ad_creative_link_titles", "title"), "caption": ("ad_creative_link_captions", "caption"),
    "cta": ("cta", "cta_text", "call_to_action", "call_to_action_type"),
    "status": ("ad.status", "status", "ad_status", "is_active"),
    "start_date": ("ad_delivery_start_time", "ad.first_shown_date", "start_date"),
    "end_date": ("ad_delivery_stop_time", "ad.last_shown_date", "end_date"),
    "creation_time": ("ad_creation_time",), "display_dates": ("daty_jak_na_karcie",),
    "observer_note": ("observer_note",), "creative_state": ("creative_state",), "library_ref": ("library_ref",),
    "screenshot_missing_reason": ("screenshot_missing_reason",),
    "observation_date": ("observation_date",), "query_phrase": ("query_phrase",), "query_country": ("query_country",),
    "platforms": ("publisher_platforms", "platforms"),
    "visible_domain": ("display_domain", "visible_domain", "link_caption"),
    "removal_notice": ("removal_notice", "withdrawal_notice", "platform_notice"),
    "image_reference": ("ad.image_urls", "image_urls", "image_url"),
    "video_reference": ("ad.videos", "videos", "video_url"),
}


def json_ref(artifact, path):
    pointer = "".join("/" + str(key).replace("~", "~0").replace("/", "~1") for key in path)
    return evidence(artifact, pointer=pointer)


def lookup(obj, path):
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def card(data, artifact):
    fields, opinions = [], []
    base = []
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        if len(data["data"]) != 1:
            raise ValueError("Pakiet wymaga jednej emisji")
        base, data = ["data", 0], data["data"][0]
    if not isinstance(data, dict):
        raise ValueError("Oczekiwano obiektu karty reklamy")
    provider = lookup(data, ["source", "provider"]) or data.get("provider")
    if not provider:
        if any(k in data for k in ("page_id", "page_name", "ad_creative_bodies", "meta_ad_library_id", "ad_archive_id")):
            provider = "meta-ad-library"
        elif "ad" in data and "advertiser" in data:
            provider = "tiktok-ad-library"

    def collect(record, prefix, variant=False):
        for field, keys in FIELDS.items():
            if variant and field in {"advertiser_ref", "ad_ref"}:
                continue
            for key in keys:
                path = key.split(".")
                value = lookup(record, path)
                if value is None:
                    continue
                items = enumerate(value) if isinstance(value, list) else [(None, value)]
                for index, item in items:
                    loc = prefix + path + ([index] if index is not None else [])
                    if isinstance(item, dict):
                        inner = next((k for k in ("text", "url", "type") if k in item), None)
                        if inner is None:
                            continue
                        item, loc = item[inner], loc + [inner]
                    if not isinstance(item, (str, int, float, bool)):
                        continue
                    ref = json_ref(artifact, loc)
                    fields.append({"field": field, **fact(clean(item), ref)})
                    if field == "text" and re.search(r"(?:ta reklama|this ad|treść reklamy).{0,45}(?:usunięt|wycofan|removed|withdrawn)", str(item), re.I):
                        fields.append({"field": "removal_notice", **fact(clean(item), ref)})
                    if field == "caption":
                        val = address(str(item) if "://" in str(item) else "https://" + str(item))
                        if val and re.fullmatch(r"[\w.-]+\.[\w-]{2,}", val["host"]):
                            fields.append({"field": "visible_domain", **fact(val["host"], ref)})

    collect(data, base)
    for key in ("cards", "creative_variants", "creatives"):
        for index, variant in enumerate(data.get(key) or []):
            if isinstance(variant, dict):
                collect(variant, base + [key, index], variant=True)

    def visit(rows, prefix, kind, parent=None):
        if isinstance(rows, dict):
            rows, prefix = rows.get("data"), prefix + ["data"]
        if not isinstance(rows, list):
            return
        for i, row in enumerate(rows):
            if isinstance(row, str):
                row = {"text": row}
            if not isinstance(row, dict):
                continue
            loc = prefix + [i]
            ref = json_ref(artifact, loc)
            author = row.get("author") or row.get("from")
            if isinstance(author, dict):
                author = author.get("name")
            rid = ref["locator"]["pointer"]
            reactions = row.get("reactions")
            counts = {}
            if isinstance(reactions, dict):
                counts.update({k: v for k, v in reactions.items() if k.lower() in
                               {"like", "love", "helpful", "wow", "sad", "angry", "haha"}})
            if "like_count" in row:
                counts["like"] = row["like_count"]
            opinions.append({"id": rid, "source_kind": kind, "text": clean(row.get("text") or row.get("message") or ""),
                             "signature": clean(author) if author else None,
                             "visible_time": clean(row.get("created_time") or row.get("time") or "") or None,
                             "rating": clean(row["rating"]) if row.get("rating") is not None else None,
                             "reactions": [{"kind": k, "count": int(v) if str(v).isdecimal() else None,
                                            "display": clean(v) if v is not None else None, "evidence": ref} for k, v in counts.items()],
                             "order": len(opinions)+1, "is_reply": parent is not None, "parent_id": parent,
                             "authenticity": None, "purchase_verified": None, "evidence": ref})
            visit(row.get("replies"), loc + ["replies"], kind, rid)
            visit(row.get("comments"), loc + ["comments"], kind, rid)

    for key, kind in (("comments", "platform_comment"), ("quotes", "creative_quote")):
        visit(data.get(key), base + [key], kind)
    return clean(provider) if provider else None, fields, opinions
