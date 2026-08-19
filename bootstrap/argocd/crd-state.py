#!/usr/bin/env python3
"""Prepare or verify the exact retained Argo CD CRD bootstrap state."""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path

import yaml

EXPECTED_NAMES = {
    "applications.argoproj.io",
    "applicationsets.argoproj.io",
    "appprojects.argoproj.io",
}


def fail(message: str) -> None:
    raise SystemExit(f"[FAIL] {message}")


def load_bundle(path: Path) -> dict[str, dict]:
    documents = [
        item
        for item in yaml.safe_load_all(path.read_text(encoding="utf-8"))
        if item is not None
    ]
    if any(not isinstance(item, dict) for item in documents):
        fail("the validated Argo CD CRD bundle contains a non-object")
    result = {
        str(item.get("metadata", {}).get("name", "")): item for item in documents
    }
    if set(result) != EXPECTED_NAMES or len(documents) != len(EXPECTED_NAMES):
        fail("the validated Argo CD CRD bundle is not exact")
    if any(item.get("kind") != "CustomResourceDefinition" for item in documents):
        fail("the validated Argo CD CRD bundle contains a non-CRD")
    return result


def normalized_spec(document: dict) -> dict:
    spec = copy.deepcopy(document.get("spec", {}))
    if spec.get("conversion") == {"strategy": "None"}:
        spec.pop("conversion")
    return spec


def verify_existing(bundle: dict[str, dict], name: str, existing_path: Path) -> None:
    if name not in EXPECTED_NAMES:
        fail("the requested Argo CD CRD is not allowlisted")
    existing = json.loads(existing_path.read_text(encoding="utf-8"))
    expected = bundle[name]
    metadata = existing.get("metadata", {})
    labels = metadata.get("labels", {})
    annotations = metadata.get("annotations", {})
    if labels.get("app.kubernetes.io/managed-by") != "Helm":
        fail("an existing Argo CD CRD has foreign or incomplete ownership")
    for key, value in {
        "meta.helm.sh/release-name": "argocd",
        "meta.helm.sh/release-namespace": "argocd",
        "helm.sh/resource-policy": "keep",
    }.items():
        if annotations.get(key) != value:
            fail("an existing Argo CD CRD has foreign or incomplete ownership")
    if existing.get("apiVersion") != expected.get("apiVersion"):
        fail("an existing Argo CD CRD has drifted from the pinned chart")
    if existing.get("kind") != "CustomResourceDefinition":
        fail("an existing Argo CD CRD has drifted from the pinned chart")
    if metadata.get("name") != name:
        fail("an existing Argo CD CRD has drifted from the pinned chart")
    if normalized_spec(existing) != normalized_spec(expected):
        fail("an existing Argo CD CRD has drifted from the pinned chart")


def select_missing(bundle: dict[str, dict], names: list[str], output: Path) -> None:
    required = set(names)
    if not required or len(required) != len(names) or not required <= EXPECTED_NAMES:
        fail("the missing Argo CD CRD selection is not exact")
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        yaml.safe_dump_all(
            [bundle[name] for name in sorted(required)],
            stream,
            explicit_start=True,
            sort_keys=False,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--name", required=True)
    verify.add_argument("--existing", type=Path, required=True)
    select = subparsers.add_parser("select")
    select.add_argument("--output", type=Path, required=True)
    select.add_argument("names", nargs="+")
    args = parser.parse_args()

    bundle = load_bundle(args.bundle)
    if args.operation == "verify":
        verify_existing(bundle, args.name, args.existing)
    else:
        select_missing(bundle, args.names, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
