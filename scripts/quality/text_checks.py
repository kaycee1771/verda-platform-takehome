#!/usr/bin/env python3
"""Check-only text hygiene hooks; never rewrite candidate files."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: text_checks.py <trailing|eof> <file>...", file=sys.stderr)
        return 2
    mode = sys.argv[1]
    failed = False
    for raw_path in sys.argv[2:]:
        path = Path(raw_path)
        try:
            data = path.read_bytes()
        except OSError as exc:
            print(f"{path}: unable to read: {exc}")
            failed = True
            continue
        if b"\x00" in data:
            continue
        if mode == "eof" and data and not data.endswith(b"\n"):
            print(f"{path}: missing final newline")
            failed = True
        elif mode == "trailing":
            for number, line in enumerate(data.splitlines(), start=1):
                if line.endswith((b" ", b"\t")):
                    print(f"{path}:{number}: trailing whitespace")
                    failed = True
        elif mode not in {"eof", "trailing"}:
            print(f"unsupported mode: {mode}", file=sys.stderr)
            return 2
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
