"""Evidence for document coverage, available offer text and the saved viewport."""
from PIL import Image

from .sources import evidence


ANALYSIS_VERSION = "landing/3"
CONTENT_STATUS = {
    "usable": "Użyteczna treść", "pending": "Oczekuje na pobranie", "no_target": "Brak celu",
    "review": "Cel do potwierdzenia", "blocked": "Odmowa dostępu", "unavailable": "Cel niedostępny",
    "unsupported": "Nieobsługiwany typ", "error": "Błąd pobrania lub odczytu", "skipped": "Pominięto",
    "legacy": "Starszy zapis bez oceny treści", "unreadable": "Brak pakietu",
}
TARGET_TYPE = {"web": "WWW", "facebook_post": "Post Facebooka", "facebook_marketplace": "Marketplace",
               "facebook_video": "Wideo Facebooka", "facebook_other": "Inny cel Facebooka", "pdf": "PDF",
               "image": "Obraz", "video": "Wideo", "audio": "Audio"}
REASON = {"access_denied": "Odmowa dostępu lub ograniczenie liczby żądań", "access_screen": "Ekran dostępu lub logowania",
          "client_unsupported": "Platforma przekierowała klienta do ekranu nieobsługiwanej przeglądarki",
          "http_unavailable": "Dokument zwrócił status niedostępności", "unavailable_screen": "Ekran niedostępności treści",
          "target_mismatch": "Odpowiedź dotyczy innego obiektu", "unverified_facebook_object": "Brak treści powiązanej z ID obiektu",
          "content_missing": "Nie znaleziono treści głównej", "unsupported_mime": "Nieobsługiwany typ odpowiedzi",
          "error_screen": "Ekran błędu serwera",
          "unsupported_facebook_target": "Nieobsługiwany typ celu Facebooka", "invalid_file": "Zawartość nie odpowiada typowi pliku",
          "document_timeout": "Przekroczono czas pobrania dokumentu", "incomplete_response": "Niepełna odpowiedź główna",
          "invalid_document": "Brak treści odpowiedzi głównej", "worker_error": "Nie ukończono odczytu",
          "dead_domain": "Domena celu nie istnieje w DNS",
          "platform_internal": "Profil platformy lub kanał kontaktu zamiast strony WWW"}
TARGET_BASIS = {"label": "Przycisk CTA", "preview": "Podgląd reklamy", "analyst": "Analityk",
                "single_link": "Jedyny odnośnik", "dominant_domain": "Wspólna domena", "caption": "Podpis domeny"}
TARGET_CONFIDENCE = {"high": "Wysoka", "low": "Niska"}


def content_status(summary, job_status):
    status = summary.get("content_status")
    if job_status in {"queued", "running"}:
        return "pending"
    if status in {"pending", "review"} and job_status:
        return {"failed": "error", "skipped": "skipped", "superseded": "skipped"}.get(job_status, "pending")
    return status or "legacy"


def summarize(folder, artifacts, result):
    visit = result.get("landing_visit") or {}
    pages = result["pages"]
    summary = {"cta": bool(visit.get("attribute") or result.get("ad_page_links")),
               "document": bool(pages), "reason": visit.get("reason"),
               "issues": visit.get("issues", []), "offer": None, "dialog": None, "screen": None}
    if "content_status" in visit:
        summary.update({key: visit[key] for key in ("content_status", "target_kind", "reason_code", "http_status",
                                                     "target_basis", "target_confidence") if key in visit})
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
