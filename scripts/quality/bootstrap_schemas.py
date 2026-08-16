#!/usr/bin/env python3
"""Materialize checksummed Kubernetes and CRD schemas for offline Kubeconform."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

import yaml


ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "schemas" / "schema-sources.lock.yaml"
CACHE = ROOT / ".local" / "schema-cache"


def download(url: str, expected_sha256: str) -> bytes:
    request = Request(url, headers={"User-Agent": "verda-platform-quality-bootstrap/1"})
    with urlopen(request, timeout=60) as response:  # noqa: S310 - locked HTTPS sources only
        payload = response.read()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected_sha256:
        raise RuntimeError(f"checksum mismatch for {url}: expected {expected_sha256}, got {actual}")
    return payload


def main() -> int:
    lock = yaml.safe_load(LOCK.read_text(encoding="utf-8"))
    CACHE.mkdir(parents=True, exist_ok=True)
    kubernetes = lock["kubernetes"]
    base = (
        "https://raw.githubusercontent.com/yannh/kubernetes-json-schema/"
        f"{kubernetes['commit']}/v{kubernetes['version']}-standalone-strict"
    )
    for item in kubernetes["files"]:
        payload = download(f"{base}/{item['name']}", item["sha256"])
        (CACHE / item["name"]).write_bytes(payload)
        print(f"[SCHEMA] core/{item['name']} checksum=verified")

    for item in lock["crds"]["materialized"]:
        payload = download(item["source"], item["source_sha256"])
        parse_payload = payload
        if item.get("normalization") == "longhorn-helm-labels-v1":
            marker = b'  labels: {{- include "longhorn.labels" . | nindent 4 }}\n'
            replacements = parse_payload.count(marker)
            if replacements < 1:
                raise RuntimeError("locked Longhorn normalization marker is absent")
            parse_payload = parse_payload.replace(marker, b"  labels:\n")
        documents = list(yaml.safe_load_all(parse_payload))
        selected = None
        for document in documents:
            if not isinstance(document, dict) or document.get("kind") != "CustomResourceDefinition":
                continue
            spec = document.get("spec", {})
            names = spec.get("names", {})
            if spec.get("group") != item["group"] or names.get("kind") != item["kind"]:
                continue
            for version in spec.get("versions", []):
                if version.get("name") == item["version"]:
                    selected = version.get("schema", {}).get("openAPIV3Schema")
                    break
        if selected is None:
            raise RuntimeError(f"locked CRD schema not found for {item['name']}")
        (CACHE / item["output"]).write_text(
            json.dumps(selected, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"[SCHEMA] crd/{item['output']} source-checksum=verified")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
