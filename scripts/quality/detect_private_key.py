#!/usr/bin/env python3
"""Fast pre-commit defense for PEM private-key material."""

from __future__ import annotations

import re
import sys
from pathlib import Path


MARKER = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")


def main() -> int:
    failed = False
    for raw_path in sys.argv[1:]:
        path = Path(raw_path)
        try:
            content = path.read_bytes()
        except OSError:
            continue
        if MARKER.search(content):
            print(f"{path}: private-key material detected")
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
