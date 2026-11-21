"""snapshot_download z ponawianiem (wolne/zrywające się łącze; HF wznawia częściowe pliki)."""
import time

from huggingface_hub import snapshot_download


def fetch(repo_id: str, tries: int = 8, **kw):
    for i in range(tries):
        try:
            return snapshot_download(repo_id, **kw)
        except Exception as e:  # noqa: BLE001
            print(f"[{repo_id}] próba {i + 1}/{tries} nieudana: {e!r}", flush=True)
            time.sleep(min(60, 5 * 2 ** i))
    raise RuntimeError(f"nie udało się pobrać {repo_id}")
