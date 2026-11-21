"""Start the discovery application from the project workspace."""
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    candidates = (root, root / ".worktrees" / "ad-discovery")
    application = next((p for p in candidates if (p / "scamgraph/discovery/engine.py").is_file()), None)
    if application is None:
        sys.exit("Brak aplikacji schedulera. Uruchom projekt z checkoutem codex/ad-discovery.")
    args = sys.argv[1:]
    if "--config" in args:
        pos = args.index("--config") + 1
        if pos < len(args):
            args[pos] = str(Path(args[pos]).resolve())
    elif not any(arg.startswith("--config=") for arg in args):
        args = ["--config", str(application / "discovery.live.json"), *args]
    for pos, arg in enumerate(args):
        if arg.startswith("--config="):
            args[pos] = "--config=" + str(Path(arg.split("=", 1)[1]).resolve())
    if not sys.argv[1:]:
        args.append("serve")
    return subprocess.call([sys.executable, "-m", "scamgraph.discovery", *args], cwd=application)


if __name__ == "__main__":
    raise SystemExit(main())
