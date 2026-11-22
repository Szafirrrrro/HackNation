"""Private additions overlay a read-only reference corpus; never append to it."""
import hashlib
import json
import os
from pathlib import Path

from .url_capture import reproject_saved_page

PRIVATE_ROOT = Path(__file__).resolve().parents[1] / ".private-discovery" / "analyst" / "corpora"


def private_corpus_path(source: str | Path) -> Path:
    root = PRIVATE_ROOT.absolute()
    if any(p.is_symlink() for p in (root, *list(root.parents)[:2])):
        raise ValueError("Prywatny katalog korpusu nie może być dowiązaniem symbolicznym.")
    key = hashlib.sha256(str(Path(source).resolve()).encode()).hexdigest()
    target = root / (key + ".jsonl")
    if target.is_symlink():
        raise ValueError("Prywatny plik korpusu nie może być dowiązaniem symbolicznym.")
    return target


def read_private_cards(path: Path) -> tuple[list[dict], int]:
    """Return readable cards and the number of skipped lines; one broken line must not stop the app."""
    cards, skipped = [], 0
    for line in Path(path).read_bytes().splitlines():
        if not line.strip():
            continue
        try:
            card = json.loads(line.decode("utf-8-sig"))
        except (ValueError, RecursionError):  # broken JSON or encoding, pathological nesting
            skipped += 1
            continue
        if (isinstance(card, dict) and isinstance(card.get("ad_id"), str)
                and all(isinstance(card.get(key, {}), dict)
                        for key in ("provenance", "extensions", "visual", "text", "extraction"))):
            cards.append(reproject_saved_page(card))
        else:
            skipped += 1
    return cards, skipped


def _ends_mid_line(path: Path) -> bool:
    if not path.is_file() or not path.stat().st_size:
        return False
    with path.open("rb") as stream:
        stream.seek(-1, os.SEEK_END)
        return stream.read(1) != b"\n"


def append_private_card(source: str | Path, card: dict) -> Path:
    target = private_corpus_path(source)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    separator = "\n" if _ends_mid_line(target) else ""  # an interrupted write must not swallow this card
    # O_NOFOLLOW also rejects a file symlink replaced after validation.
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as stream:
        if os.fstat(stream.fileno()).st_nlink > 1:
            raise ValueError("Prywatny plik korpusu nie może być twardym dowiązaniem.")
        stream.write(separator + json.dumps(card, ensure_ascii=False) + "\n")
    return target
