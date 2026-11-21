"""Provider boundary for one configured query and one observed delivery."""
from dataclasses import dataclass
from pathlib import Path


class SourceError(ValueError):
    """Operator-readable reason without credentials or private HTTP bodies."""


@dataclass(frozen=True)
class Query:
    phrase: str
    country: str
    limit: int


@dataclass
class Finding:
    ad_ref: str
    card: dict
    reason: str
    missing: bool
    # Original file and JSON pointer, line number or HTML element locator.
    original: Path
    locator: str
    image: Path | None = None
    observed_at: str | None = None
    source_kind: str = "upload"
    source_sha256: str | None = None
    media: tuple[Path, ...] = ()
    skipped_domain: str | None = None


# Adapter signature: fetch(options: dict, query: Query) -> Iterable[Finding].
# An empty iteration means the source explicitly supports the empty result.
# SourceError means unavailable data, blocked access, or unsupported layout.
