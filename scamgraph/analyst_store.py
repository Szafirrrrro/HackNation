"""Private additions overlay a read-only reference corpus; never append to it."""
import hashlib
import json
import os
from pathlib import Path

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


def append_private_card(source: str | Path, card: dict) -> Path:
    target = private_corpus_path(source)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # O_NOFOLLOW also rejects a file symlink replaced after validation.
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(card, ensure_ascii=False) + "\n")
    return target
