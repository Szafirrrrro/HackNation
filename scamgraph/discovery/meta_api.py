"""Read Meta Ad Library with an operator-provided token."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

import urllib3

from ..capture import staging
from .types import Finding, SourceError

ENDPOINT = "https://graph.facebook.com/v27.0/ads_archive"
FIELDS = ("id", "page_id", "page_name", "ad_creative_bodies", "ad_creative_link_titles",
          "ad_creative_link_captions", "ad_delivery_start_time", "ad_delivery_stop_time",
          "publisher_platforms")


def fetch(options, query):
    token = os.environ.get("SCAMGRAPH_META_TOKEN", "").strip()
    if options["mode"] != "live" or not token:
        raise SourceError("Meta API wymaga trybu live i zmiennej SCAMGRAPH_META_TOKEN.")
    if len(query.phrase) > 100:
        raise SourceError("Fraza dla Meta API może mieć najwyżej 100 znaków.")
    root = Path(options["archive_dir"])
    root.mkdir(parents=True, exist_ok=True)
    params = {"fields": ",".join(FIELDS), "search_terms": query.phrase, "ad_type": "ALL",
              "ad_reached_countries": json.dumps([query.country]), "search_type": "KEYWORD_EXACT_PHRASE",
              "limit": query.limit, "ad_active_status": "ACTIVE"}
    seen, cursors = set(), set()
    with urllib3.PoolManager() as http:
        for _ in range(query.limit):
            response = http.request("GET", ENDPOINT, fields=params, headers={"Authorization": "Bearer " + token},
                                    retries=False, redirect=False, timeout=urllib3.Timeout(connect=5, read=15))
            if response.status != 200:
                raise SourceError(f"Meta API · HTTP {response.status}. Sprawdź dostęp i limit zapytań.")
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise SourceError("Meta API zwróciło nierozpoznaną odpowiedź.")
            for raw in payload["data"]:
                if not isinstance(raw, dict) or not raw.get("id"):
                    raise SourceError("Brak identyfikatora w rekordzie Meta API.")
                ref = str(raw["id"])
                if ref in seen:
                    continue
                seen.add(ref)
                row = {k: raw[k] for k in FIELDS if k in raw}
                data = json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf8")
                sha = hashlib.sha256(data).hexdigest()
                path = root / (sha + ".json")
                with staging(root) as tmp:
                    staged = tmp / "record.json"
                    staged.write_bytes(data)
                    os.replace(staged, path)
                card = {**row, "landing_missing_reason": "Odpowiedź Meta API nie zawiera docelowego URL przycisku."}
                yield Finding(ref, card, "Wynik zapytania Meta API", not bool(row.get("ad_creative_bodies")),
                              path, "", observed_at=datetime.now(timezone.utc).isoformat(),
                              source_kind="library", source_sha256=sha)
                if len(seen) >= query.limit:
                    return
            paging = payload.get("paging") or {}
            if not paging.get("next"):
                return
            cursor = (paging.get("cursors") or {}).get("after")
            if not cursor or cursor in cursors:
                raise SourceError("Nie można kontynuować paginacji Meta API.")
            params["after"] = cursor
            cursors.add(cursor)
        raise SourceError("Osiągnięto limit stron zapytania Meta API.")
