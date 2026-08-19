#!/usr/bin/env python3
"""Compute the canonical fingerprint for inputs that affect offline quality caches."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


CACHE_AFFECTING_VERSION_SECTIONS = (
    "terraform",
    "providers",
    "quality_tools",
    "tool_delivery",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_payload(repository_root: Path, versions_lock: Path) -> dict[str, Any]:
    document = yaml.safe_load(versions_lock.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{versions_lock} must contain a YAML mapping")

    missing = [
        section
        for section in CACHE_AFFECTING_VERSION_SECTIONS
        if section not in document
    ]
    if missing:
        raise ValueError(
            "versions lock is missing cache-affecting sections: " + ", ".join(missing)
        )

    provider_locks = []
    for path in sorted(repository_root.glob("infra/terraform/**/.terraform.lock.hcl")):
        provider_locks.append(
            {
                "path": path.relative_to(repository_root).as_posix(),
                "sha256": sha256_file(path),
            }
        )

    return {
        "schema_version": 1,
        "versions": {
            section: document[section]
            for section in CACHE_AFFECTING_VERSION_SECTIONS
        },
        "terraform_provider_locks": provider_locks,
    }


def compute_fingerprint(repository_root: Path, versions_lock: Path) -> str:
    payload = build_payload(repository_root, versions_lock)
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "versions_lock",
        nargs="?",
        default="versions.lock.yaml",
        type=Path,
    )
    parser.add_argument(
        "--repository-root",
        default=Path.cwd(),
        type=Path,
    )
    args = parser.parse_args()

    repository_root = args.repository_root.resolve()
    versions_lock = args.versions_lock
    if not versions_lock.is_absolute():
        versions_lock = repository_root / versions_lock
    print(compute_fingerprint(repository_root, versions_lock.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
