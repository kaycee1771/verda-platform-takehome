#!/usr/bin/env python3
"""Enforce the canonical repository topology and reject unexplained roots."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "tests" / "static" / "repository-contract.yaml"


def main() -> int:
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    missing: list[str] = []
    for relative in contract["required_directories"]:
        if not (ROOT / relative).is_dir():
            missing.append(f"missing directory: {relative}")
    for relative in contract["required_files"]:
        if not (ROOT / relative).is_file():
            missing.append(f"missing file: {relative}")

    allowed = set(contract["allowed_top_level_directories"])
    ignored = set(contract["ignored_local_directories"])
    unexplained = sorted(
        item.name
        for item in ROOT.iterdir()
        if item.is_dir() and item.name not in allowed and item.name not in ignored
    )
    missing.extend(f"unexplained top-level directory: {name}" for name in unexplained)

    if missing:
        print("Repository contract violations:")
        for item in missing:
            print(f"- {item}")
        return 1
    print(
        f"[PASS] repository contract: {len(contract['required_directories'])} directories, "
        f"{len(contract['required_files'])} files, no unexplained top-level directory"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
