from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.identity_database import IdentityDatabase


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the shared identity DB from a completed job DB")
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    with IdentityDatabase(args.source, readonly=True) as source:
        print(source.export_canonical(args.destination))


if __name__ == "__main__":
    main()
