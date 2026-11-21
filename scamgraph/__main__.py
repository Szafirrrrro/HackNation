"""Command-line entry point for the offline evidence importer."""
import argparse
from pathlib import Path

from .capture import DEFAULT_STORE, capture


def main():
    parser = argparse.ArgumentParser(description="ScamGraph · import jednej obserwacji offline")
    parser.add_argument("source", type=Path, help="Katalog obserwacji lub pojedynczy plik")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--provider", help="Identyfikator dostawcy dla materiału bez metadanych")
    parser.add_argument("--collected-at", help="Znany czas pozyskania ze strefą (ISO 8601)")
    parser.add_argument("--asr-model", type=Path, help="Lokalny katalog modelu faster-whisper")
    parser.add_argument("--ad-card", action="store_true", help="Przyjmij pojedynczy HTML jako kartę reklamy")
    args = parser.parse_args()
    try:
        result = capture(args.source, args.store, args.provider, args.collected_at, args.asr_model, args.ad_card)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Import: {exc}\n")
    print(result)


if __name__ == "__main__":
    main()
