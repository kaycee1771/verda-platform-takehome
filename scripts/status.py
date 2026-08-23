#!/usr/bin/env python3
"""Print the concise, non-secret submission readiness summary."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "config" / "submission-readiness.yaml"


def main() -> int:
    document = yaml.safe_load(READINESS.read_text(encoding="utf-8"))
    print(f"overall: {document['status']}")
    for name, gate in document["mandatory"].items():
        print(f"{name}: {gate['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
