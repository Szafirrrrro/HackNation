"""Evidence for document coverage, available offer text and the saved viewport."""
from PIL import Image

from .sources import evidence


ANALYSIS_VERSION = "landing/3"


def summarize(folder, artifacts, result):
    visit = result.get("landing_visit") or {}
    pages = result["pages"]
    summary = {"cta": bool(visit.get("attribute") or result.get("ad_page_links")),
               "document": bool(pages), "reason": visit.get("reason"),
               "issues": visit.get("issues", []), "offer": None, "dialog": None, "screen": None}
    for page in pages:
        if page.get("consent_dialogs"):
            summary["dialog"] = page["consent_dialogs"][0]
        examples = [*page.get("prices", []), *page["products"], *page.get("offer_headings", [])]
        if examples and not summary["offer"]:
            summary["offer"] = examples[0]
    if not summary["offer"]:
        claim = next((row for row in result["signals"] if row.get("context") == "treść strony"
                      and row["kind"] in {"efekt_zdrowotny", "obietnica_zysku"}), None)
        if claim:
            summary["offer"] = {"value": claim["excerpt"], "evidence": claim["evidence"]}
    item = next((a for a in artifacts if a["path"] == "landing/screenshot.png"), None)
    if item:
        try:
            with Image.open(folder / item["path"]) as img:
                if img.width * img.height > 32_000_000:
                    return summary
                # Measure the centre of the viewport, excluding the outer navigation.
                box = [img.width//8, img.height//3, img.width*7//8, img.height*5//6]
                sample = img.crop(box).convert("RGB").resize((96, 48))
                counts = sample.getcolors(96*48) or []
                share = max((count for count, _ in counts), default=0) / (96*48)
                summary["screen"] = {"uniform_fraction": round(share, 3), "mostly_uniform": share >= 0.95,
                                     "evidence": evidence(item, bbox=box)}
        except (OSError, ValueError, Image.DecompressionBombError):
            pass
    return summary
