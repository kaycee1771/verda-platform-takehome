#!/usr/bin/env python3
"""Fail when the quality image differs from the exact repository version lock."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def version_present(expected: str, output: str) -> bool:
    pattern = rf"(?<![0-9])v?{re.escape(expected)}(?![0-9])"
    return re.search(pattern, output) is not None


def main() -> int:
    lock = yaml.safe_load((ROOT / "versions.lock.yaml").read_text(encoding="utf-8"))
    failures: list[str] = []
    for name, item in lock["quality_tools"].items():
        command = item["command"]
        expected = item["version"]
        if shutil.which(command) is None:
            failures.append(f"{name}: command '{command}' is missing")
            print(f"[FAIL] {name}: missing")
            continue
        result = subprocess.run(
            [command, *item["version_args"]],
            check=False,
            capture_output=True,
            text=True,
        )
        output = f"{result.stdout}\n{result.stderr}"
        if result.returncode != 0 or not version_present(expected, output):
            failures.append(f"{name}: expected {expected}; command returned {output.strip()!r}")
            print(f"[FAIL] {name}: expected={expected}")
        else:
            print(f"[PASS] {name}: {expected}")
    if failures:
        print("\nVersion lock violations:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
