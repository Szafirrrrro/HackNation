"""Shared JSONL diagnostics and identity checks for the local importers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


def read_jsonl(path: Path, errors: list[dict]) -> list[tuple[int, dict]]:
    with path.open("rb") as stream:
        return parse_jsonl(stream, str(path), errors)


def parse_jsonl(lines: Iterable[bytes], file: str, errors: list[dict]) -> list[tuple[int, dict]]:
    rows = []
    for line, data in enumerate(lines, 1):
        if not data.strip():
            continue
        try:
            record = json.loads(data.decode("utf-8-sig"))
            if not isinstance(record, dict):
                raise ValueError("expected JSON object")
        except (ValueError, RecursionError) as exc:
            errors.append({"file": file, "line": line, "error": f"invalid_jsonl: {exc}"})
        else:
            rows.append((line, record))
    return rows


def source_identity(row: dict) -> tuple[str, str] | None:
    for field in ("source", "provenance"):
        source = row.get(field)
        if not isinstance(source, dict):
            continue
        provider = source.get("provider") or source.get("source")
        ref = source.get("ad_ref")
        if field == "provenance" and source.get("original_provider") and source.get("original_ad_ref"):
            provider, ref = source["original_provider"], source["original_ad_ref"]
        if not isinstance(provider, str) or not provider.strip():
            continue
        if isinstance(ref, int) and not isinstance(ref, bool):
            ref = str(ref)
        ad_id = row.get("ad_id")
        if not ref and "observation_seq" in source and isinstance(ad_id, str):
            prefix = provider + "/"
            if ad_id.startswith(prefix):
                ref = ad_id[len(prefix):]
        if isinstance(ref, str) and ref.strip():
            return provider.strip().casefold(), ref.strip()
    return None


def deduplicate_rows(rows: list[tuple[int, dict]], dataset_id: str, file: str,
                     errors: list[dict]) -> tuple[list[tuple[int, dict]], list[dict]]:
    """Keep the first record for each emission and retain both locations in diagnostics.

    Local aliases can point at the same provider emission. A row with conflicting
    local and provider identities cannot change the mappings of earlier rows.
    """
    by_local, by_source = {}, {}
    accepted, duplicates = [], []
    for line, row in rows:
        ad_id = row.get("ad_id")
        if not isinstance(ad_id, str) or not ad_id.strip():
            errors.append({"file": file, "line": line, "error": "missing_ad_id"})
            continue
        local = (dataset_id, ad_id)
        source = source_identity(row)
        local_entry = by_local.get(local)
        source_entry = by_source.get(source)
        earlier = local_entry or source_entry
        if earlier is None:
            entry = (line, row, source)
            by_local[local] = entry
            if source:
                by_source[source] = entry
            accepted.append((line, row))
            continue
        first_line, first_row, first_source = earlier
        note = {"file": file, "line": line, "ad_id": ad_id, "first_line": first_line,
                "first_ad_id": first_row["ad_id"], "dataset_id": dataset_id}
        if source:
            note.update(provider=source[0], ad_ref=source[1])
        if ((local_entry and first_source and source and first_source != source)
                or (local_entry and source_entry and local_entry is not source_entry)):
            if first_source:
                note["first_provider"], note["first_ad_ref"] = first_source
            if source_entry is not None and source_entry is not earlier:
                note["provider_line"] = source_entry[0]
            errors.append({**note, "error": "conflicting_emission_identity"})
            continue
        if row != first_row and local_entry and not (first_source and source == first_source):
            errors.append({**note, "error": "conflicting_local_record"})
            continue
        by_local[local] = earlier
        if source:
            by_source[source] = earlier
        duplicates.append({**note, "reason": "same_provider_emission" if source_entry else "same_local_id",
                           "different_payload": any(row.get(key) != first_row.get(key)
                                                    for key in row.keys() | first_row.keys() if key != "ad_id")})
    return accepted, duplicates
